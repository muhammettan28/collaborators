"""
Tests for invitations by email someone sends one person within a few
minutes: one email for them all, whose link lists them to accept.
"""

import re
from unittest import mock

import pytest
from rest_framework.test import APIClient

from core import factories, models
from core.invitations import send_bundle

pytestmark = pytest.mark.django_db

PNG = b"\x89PNG\r\n\x1a\n"


def client_for(user=None):
    """An API client, logged in as the user if given."""
    client = APIClient()
    if user:
        client.force_login(user)
    return client


def token_in(mail):
    """The token of the invitation link in an email."""
    return re.search(r"/invite/\?token=([\w:.\-]+)", mail.body).group(1)


@pytest.fixture(name="queued")
def queued_fixture():
    """
    The emails queued, instead of sent at once as Celery runs its tasks
    inline in tests: `send()` sends them as the worker would, later.
    """
    with mock.patch(
        "core.api.invitations.send_invitation_bundle.apply_async"
    ) as apply_async:

        def send():
            for call in apply_async.call_args_list:
                send_bundle(*call.kwargs["args"])
            apply_async.reset_mock()

        yield send


def invite_all(owner, email):
    """A workspace, a space and a page the owner invites the email to."""
    workspace = models.Workspace.objects.create(name="Acme")
    models.WorkspaceAccess.objects.create(workspace=workspace, user=owner, role="owner")
    space = factories.DocumentFactory(
        title="Launches", kind="space", users=[(owner, "owner")]
    )
    page = factories.DocumentFactory(title="Plan", users=[(owner, "owner")])
    client = client_for(owner)
    # The page first: the email lists workspaces, then spaces, then pages
    for url, role in (
        (f"/api/v1.0/documents/{page.id}/invitations/", "reader"),
        (f"/api/v1.0/workspaces/{workspace.id}/invitations/", "member"),
        (f"/api/v1.0/documents/{space.id}/invitations/", "editor"),
    ):
        response = client.post(url, {"email": email, "role": role}, format="json")
        assert response.status_code == 201
    return workspace, space, page


def test_invitations_sent_together_go_out_as_one_email(mailoutbox, queued):
    """Each one puts the email off: only the last one's task sends it."""
    owner = factories.UserFactory(full_name="Ada", language="en-us")
    workspace, space, _page = invite_all(owner, "new@example.com")
    models.ItemLogo.objects.create(
        workspace=workspace, content_type="image/png", data=PNG
    )
    assert not mailoutbox

    queued()
    assert len(mailoutbox) == 1
    mail = mailoutbox[0]
    assert mail.to == ["new@example.com"]
    assert mail.subject == "Ada invited you to Acme and 2 more"
    body = re.sub(r"\s+", " ", mail.body)
    assert (
        "The workspace “Acme”, as member The space “Launches”, as editor "
        "The page “Plan”, as reader"
    ) in body
    html = mail.alternatives[0][0]
    assert html.count("/logo/") == 1

    info = client_for().get(f"/api/v1.0/invitations/{token_in(mail)}/").json()
    assert info["is_bundle"] is True
    assert info["issuer"] == "Ada"
    assert [(i["kind"], i["name"], i["role"]) for i in info["invitations"]] == [
        ("workspace", "Acme", "member"),
        ("space", "Launches", "editor"),
        ("page", "Plan", "reader"),
    ]
    first = info["invitations"][0]
    assert first["has_logo"] is True
    logo = client_for().get(f"/api/v1.0/invitations/{first['token']}/logo/")
    assert logo.content == PNG
    assert space.get_role(owner) == "owner"


def test_accepting_all_of_them_then_the_link_opens_each(mailoutbox, queued):
    """One button for all; the link then leads to each of them."""
    owner = factories.UserFactory(language="en-us")
    workspace, space, page = invite_all(owner, "new@example.com")
    queued()
    token = token_in(mailoutbox[0])

    newcomer = factories.UserFactory(email="elsewhere@example.com")
    response = client_for(newcomer).post(f"/api/v1.0/invitations/{token}/accept/")
    assert response.json() == {"kind": "bundle", "accepted": 3}
    assert workspace.get_role(newcomer) == "member"
    assert space.get_role(newcomer) == "editor"
    assert page.get_role(newcomer) == "reader"

    info = client_for(newcomer).get(f"/api/v1.0/invitations/{token}/").json()
    assert [(i["is_accepted"], i["id"]) for i in info["invitations"]] == [
        (True, str(workspace.id)),
        (True, str(space.id)),
        (True, str(page.id)),
    ]
    # Nothing left to show to anyone else
    assert client_for().get(f"/api/v1.0/invitations/{token}/").status_code == 404


def test_one_of_them_accepted_alone(mailoutbox, queued):
    """Each invitation of the list keeps its own token."""
    owner = factories.UserFactory(language="en-us")
    workspace, space, _page = invite_all(owner, "new@example.com")
    queued()
    token = token_in(mailoutbox[0])
    invitations = (
        client_for().get(f"/api/v1.0/invitations/{token}/").json()["invitations"]
    )

    someone = factories.UserFactory()
    client_for(someone).post(f"/api/v1.0/invitations/{invitations[1]['token']}/accept/")
    assert space.get_role(someone) == "editor"
    assert workspace.get_role(someone) is None

    info = client_for(someone).get(f"/api/v1.0/invitations/{token}/").json()
    assert [i["is_accepted"] for i in info["invitations"]] == [False, True, False]


def test_a_cancelled_one_leaves_the_list(mailoutbox, queued):
    """Cancelled after the email was sent: its link no longer shows it."""
    owner = factories.UserFactory(language="en-us")
    workspace, _space, _page = invite_all(owner, "new@example.com")
    queued()
    token = token_in(mailoutbox[0])
    workspace.invitations.all().delete()

    info = client_for().get(f"/api/v1.0/invitations/{token}/").json()
    assert [i["kind"] for i in info["invitations"]] == ["space", "page"]


def test_bundles_are_per_sender_and_close_once_sent(mailoutbox, queued):
    """Another sender's invitation, or one sent later, has its own email."""
    ada, bob = factories.UserFactory.create_batch(2, language="en-us")
    page = factories.DocumentFactory(title="Plan", users=[(ada, "owner")])
    other = factories.DocumentFactory(title="Notes", users=[(bob, "owner")])
    later = factories.DocumentFactory(title="Later", users=[(ada, "owner")])

    def invite(user, document):
        client_for(user).post(
            f"/api/v1.0/documents/{document.id}/invitations/",
            {"email": "new@example.com", "role": "reader"},
            format="json",
        )

    invite(ada, page)
    invite(bob, other)
    queued()
    invite(ada, later)
    queued()

    # One invitation each: the email as it always was (capitalized subject)
    assert len(mailoutbox) == 3
    assert [mail.subject for mail in mailoutbox] == [
        f"{ada.full_name} shared a page with you: Plan".capitalize(),
        f"{bob.full_name} shared a page with you: Notes".capitalize(),
        f"{ada.full_name} shared a page with you: Later".capitalize(),
    ]
    token = token_in(mailoutbox[0])
    assert client_for().get(f"/api/v1.0/invitations/{token}/").json()["kind"] == "page"


def test_a_tampered_bundle_token_finds_nothing():
    """A bundle's token is signed like an invitation's."""
    assert client_for().get("/api/v1.0/invitations/b:forged/").status_code == 404
