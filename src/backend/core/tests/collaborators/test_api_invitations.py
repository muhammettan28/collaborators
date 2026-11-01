"""
Tests for invitations by email to workspaces, spaces and pages, the page
accepting them, and the logos standing for those items.
"""

import base64
import re

import pytest
from rest_framework.test import APIClient

from core import factories, models, registrations
from core.api.invitations import WORKSPACE, make_token

pytestmark = pytest.mark.django_db

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f"
    b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)
PNG_URL = "data:image/png;base64," + base64.b64encode(PNG).decode()


def client_for(user=None):
    """An API client, logged in as the user if given."""
    client = APIClient()
    if user:
        client.force_login(user)
    return client


def token_in(mail):
    """The token of the invitation link in an email."""
    return re.search(r"/invite/\?token=([\w:.\-]+)", mail.body).group(1)


def workspace_of(owner):
    """A workspace the user owns."""
    workspace = models.Workspace.objects.create(name="Acme", description="Rockets")
    models.WorkspaceAccess.objects.create(workspace=workspace, user=owner, role="owner")
    return workspace


def test_workspace_invitation_by_email_then_accepted(mailoutbox):
    """The email links to the page; signed in, accepting makes a member."""
    admin = factories.UserFactory(full_name="Ada")
    workspace = workspace_of(admin)
    response = client_for(admin).post(
        f"/api/v1.0/workspaces/{workspace.id}/invitations/",
        {"email": "New.Person@Example.com"},
        format="json",
    )
    assert response.status_code == 201
    assert response.json()["email"] == "new.person@example.com"
    assert len(mailoutbox) == 1
    assert "Ada invited you to the workspace Acme" in mailoutbox[0].subject
    token = token_in(mailoutbox[0])

    info = client_for().get(f"/api/v1.0/invitations/{token}/").json()
    assert info["kind"] == "workspace"
    assert info["name"] == "Acme"
    assert info["issuer"] == "Ada"
    assert info["has_logo"] is False

    # Signed up with another email: the link still lets them in
    newcomer = factories.UserFactory(email="other@example.com")
    response = client_for(newcomer).post(f"/api/v1.0/invitations/{token}/accept/")
    assert response.json() == {"kind": "workspace", "id": str(workspace.id)}
    assert workspace.get_role(newcomer) == "member"
    assert not models.WorkspaceInvitation.objects.exists()
    assert client_for().get(f"/api/v1.0/invitations/{token}/").status_code == 404


def test_signing_up_with_the_invited_email_joins_the_workspace():
    """And skips the approval of the registration."""
    admin = factories.UserFactory()
    workspace = workspace_of(admin)
    models.WorkspaceInvitation.objects.create(
        workspace=workspace, email="joiner@example.com", role="administrator"
    )
    joiner = factories.UserFactory(email="joiner@example.com")
    assert workspace.get_role(joiner) == "administrator"
    joiner.refresh_from_db()
    assert joiner.collaborator_invited is True


def test_invited_newcomer_waits_for_no_approval(settings):
    """Even signed up under another email, accepting lets them in."""
    settings.COLLABORATORS_SIGNUP_APPROVAL = True
    admin = factories.UserFactory()
    workspace = workspace_of(admin)
    invitation = models.WorkspaceInvitation.objects.create(
        workspace=workspace, email="someone@example.com", issuer=admin
    )
    newcomer = factories.UserFactory(registration_status=registrations.PENDING)
    token = make_token(WORKSPACE, invitation)
    response = client_for(newcomer).post(f"/api/v1.0/invitations/{token}/accept/")
    assert response.status_code == 200
    newcomer.refresh_from_db()
    assert newcomer.registration_status == registrations.APPROVED


def test_page_invitation_email_leads_to_the_invite_page(mailoutbox):
    """Anyone, even with an account, can be invited to a page by email."""
    owner = factories.UserFactory(full_name="Ada")
    page = factories.DocumentFactory(title="Plan", users=[(owner, "owner")])
    existing = factories.UserFactory(email="known@example.com")
    response = client_for(owner).post(
        f"/api/v1.0/documents/{page.id}/invitations/",
        {"email": "known@example.com", "role": "editor"},
        format="json",
    )
    assert response.status_code == 201
    token = token_in(mailoutbox[0])
    assert client_for().get(f"/api/v1.0/invitations/{token}/").json()["kind"] == "page"

    client_for(existing).post(f"/api/v1.0/invitations/{token}/accept/")
    assert page.get_role(existing) == "editor"


def test_invitation_email_shows_the_logo_of_what_it_invites_to(mailoutbox):
    """A space's or page's logo is in its email; without one, nothing is."""
    owner = factories.UserFactory()
    page = factories.DocumentFactory(users=[(owner, "owner")])

    def invite(email):
        client_for(owner).post(
            f"/api/v1.0/documents/{page.id}/invitations/",
            {"email": email, "role": "reader"},
            format="json",
        )

    invite("first@example.com")
    assert "/logo/" not in mailoutbox[0].alternatives[0][0]

    models.ItemLogo.objects.create(document=page, content_type="image/png", data=PNG)
    invite("second@example.com")
    logo = f"/api/v1.0/invitations/{token_in(mailoutbox[1])}/logo/"
    assert logo in mailoutbox[1].alternatives[0][0]
    assert client_for().get(logo).content == PNG


def test_a_newcomers_link_opens_what_their_account_already_took(mailoutbox):
    """
    Signing up takes one's invitations: back to the link, the newcomer is
    led to the page (it said the invitation could no longer be used).
    """
    owner = factories.UserFactory(full_name="Ada")
    page = factories.DocumentFactory(title="Plan", users=[(owner, "owner")])
    workspace = workspace_of(owner)
    for url in (
        f"/api/v1.0/documents/{page.id}/invitations/",
        f"/api/v1.0/workspaces/{workspace.id}/invitations/",
    ):
        response = client_for(owner).post(
            url, {"email": "new@example.com"}, format="json"
        )
        assert response.status_code == 201
    page_token, workspace_token = (token_in(mail) for mail in mailoutbox)

    # Signing up with the invited email: the account takes both invitations
    newcomer = factories.UserFactory(email="new@example.com")
    assert page.get_role(newcomer) is not None
    assert not models.Invitation.objects.exists()

    for token, kind, item in (
        (page_token, "page", page),
        (workspace_token, "workspace", workspace),
    ):
        info = client_for(newcomer).get(f"/api/v1.0/invitations/{token}/")
        assert info.status_code == 200
        assert info.json()["is_accepted"] is True
        assert info.json()["kind"] == kind
        accepted = client_for(newcomer).post(f"/api/v1.0/invitations/{token}/accept/")
        assert accepted.status_code == 200
        assert accepted.json() == {"kind": kind, "id": str(item.id)}
        # Nobody else, nor signed out, learns anything from the link
        stranger = factories.UserFactory()
        assert (
            client_for(stranger).get(f"/api/v1.0/invitations/{token}/").status_code
            == 404
        )
        assert client_for().get(f"/api/v1.0/invitations/{token}/").status_code == 404


def test_only_administrators_invite_to_a_workspace():
    """Members can't; nor can they see the invitations."""
    admin, member = factories.UserFactory.create_batch(2)
    workspace = workspace_of(admin)
    models.WorkspaceAccess.objects.create(workspace=workspace, user=member)
    url = f"/api/v1.0/workspaces/{workspace.id}/invitations/"
    assert client_for(member).get(url).status_code == 403
    assert (
        client_for(member).post(url, {"email": "a@b.org"}, format="json").status_code
        == 403
    )
    assert (
        client_for(admin)
        .post(url, {"email": "not an email"}, format="json")
        .status_code
        == 400
    )


def test_a_tampered_token_finds_nothing():
    """Signed tokens only."""
    assert client_for().get("/api/v1.0/invitations/forged/").status_code == 404


def test_workspace_logo_set_by_administrators_shown_on_the_invite_page(mailoutbox):
    """A small image in the database, read back as it was given."""
    admin, member = factories.UserFactory.create_batch(2)
    workspace = workspace_of(admin)
    models.WorkspaceAccess.objects.create(workspace=workspace, user=member)
    url = f"/api/v1.0/workspaces/{workspace.id}/logo/"

    assert client_for(admin).get(url).status_code == 404
    assert (
        client_for(member).put(url, {"data": PNG_URL}, format="json").status_code == 403
    )
    assert (
        client_for(admin).put(url, {"data": PNG_URL}, format="json").status_code == 200
    )
    response = client_for(member).get(url)
    assert response["Content-Type"] == "image/png"
    assert response.content == PNG

    client_for(admin).post(
        f"/api/v1.0/workspaces/{workspace.id}/invitations/",
        {"email": "new@example.com"},
        format="json",
    )
    token = token_in(mailoutbox[0])
    assert client_for().get(f"/api/v1.0/invitations/{token}/").json()["has_logo"]
    assert client_for().get(f"/api/v1.0/invitations/{token}/logo/").content == PNG
    # Shown in its email too, not in the plain text version
    logo = f"/api/v1.0/invitations/{token}/logo/"
    assert logo in mailoutbox[0].alternatives[0][0]
    assert logo not in mailoutbox[0].body

    assert client_for(admin).delete(url).status_code == 204
    assert client_for(admin).get(url).status_code == 404


def test_page_logo_set_by_editors_and_checked():
    """Only real images, small ones."""
    owner, reader = factories.UserFactory.create_batch(2)
    page = factories.DocumentFactory(
        link_reach="restricted", users=[(owner, "owner"), (reader, "reader")]
    )
    url = f"/api/v1.0/documents/{page.id}/logo/"
    assert (
        client_for(reader).put(url, {"data": PNG_URL}, format="json").status_code == 403
    )
    fake = "data:image/png;base64," + base64.b64encode(b"<svg></svg>").decode()
    assert client_for(owner).put(url, {"data": fake}, format="json").status_code == 400
    svg = "data:image/svg+xml;base64," + base64.b64encode(b"<svg/>").decode()
    assert client_for(owner).put(url, {"data": svg}, format="json").status_code == 400
    assert (
        client_for(owner).put(url, {"data": PNG_URL}, format="json").status_code == 200
    )
    assert client_for(reader).get(url).content == PNG
