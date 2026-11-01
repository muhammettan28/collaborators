"""
Collaborators: platform owners add people straight into workspaces, spaces
and pages, apart from invitations (core.placements).
"""

from django.core import mail

import pytest
from rest_framework.test import APIClient

from core import factories, models
from core.choices import PlatformLogActionChoices

pytestmark = pytest.mark.django_db

PLACES = "/api/v1.0/platform/places/"
ADD = "/api/v1.0/platform/add-to-places/"


def _client(user):
    client = APIClient()
    client.force_login(user)
    return client


def _owner():
    return factories.UserFactory(platform_role="owner", full_name="Ada")


def _workspace(name="Acme"):
    workspace = models.Workspace.objects.create(name=name, slug=name.lower())
    models.WorkspaceAccess.objects.create(
        workspace=workspace, user=factories.UserFactory(), role="owner"
    )
    return workspace


def test_placements_only_platform_owners():
    """Administrators and below neither search places nor add people."""
    administrator = factories.UserFactory(platform_role="administrator")
    client = _client(administrator)

    assert client.get(PLACES).status_code == 403
    assert client.post(ADD, {}, format="json").status_code == 403


def test_placements_find_places_of_the_whole_platform():
    """Owners find any workspace, space or page by its name, not being in it."""
    _workspace("Research")
    space = factories.DocumentFactory(title="Research notes", kind="space")
    factories.DocumentFactory(parent=space, title="Research plan")
    factories.DocumentFactory(title="Holidays")
    deleted = factories.DocumentFactory(title="Research gone")
    deleted.soft_delete()

    response = _client(_owner()).get(PLACES, {"q": "research"})

    assert response.status_code == 200
    assert [(place["kind"], place["name"]) for place in response.json()] == [
        ("workspace", "Research"),
        ("space", "Research notes"),
        ("page", "Research plan"),
    ]
    assert response.json()[2]["inside"] == "Research notes"


def test_placements_add_people_with_their_roles_and_one_email(
    django_capture_on_commit_callbacks,
):
    """
    Each person gets the role chosen on each place, without an invitation,
    one email listing them, and a line in the platform log.
    """
    owner = _owner()
    workspace = _workspace()
    space = factories.DocumentFactory(title="Plans", kind="space")
    page = factories.DocumentFactory(title="Budget")
    first, second = factories.UserFactory.create_batch(2, language="en-us")

    with django_capture_on_commit_callbacks(execute=True):
        response = _client(owner).post(
            ADD,
            {
                "people": [str(first.id), str(second.id)],
                "places": [
                    {"kind": "workspace", "id": str(workspace.id), "role": "member"},
                    {"kind": "space", "id": str(space.id), "role": "editor"},
                    {"kind": "page", "id": str(page.id), "role": "reader"},
                ],
            },
            format="json",
        )

    assert response.status_code == 200
    for user in (first, second):
        assert workspace.accesses.get(user=user).role == "member"
        assert space.accesses.get(user=user).role == "editor"
        assert page.accesses.get(user=user).role == "reader"
    assert not models.WorkspaceInvitation.objects.exists()
    assert not models.Invitation.objects.exists()
    assert sorted(message.to[0] for message in mail.outbox) == sorted(
        [first.email, second.email]
    )
    assert mail.outbox[0].subject == "Ada added you to Acme and 2 more"
    assert "The space “Plans”, as editor" in mail.outbox[0].body
    log = models.PlatformLog.objects.filter(
        action=PlatformLogActionChoices.ADDED_TO_PLACES
    )
    assert log.count() == 2
    assert log.first().actor == owner


def test_placements_one_place_email_links_to_it(django_capture_on_commit_callbacks):
    """Added to one place, the email opens it."""
    page = factories.DocumentFactory(title="Budget")
    user = factories.UserFactory()

    with django_capture_on_commit_callbacks(execute=True):
        _client(_owner()).post(
            ADD,
            {
                "people": [str(user.id)],
                "places": [{"kind": "page", "id": str(page.id), "role": "editor"}],
            },
            format="json",
        )

    assert mail.outbox[0].subject == "Ada added you to the page Budget"
    assert f"/page/{page.id}/" in mail.outbox[0].body


def test_placements_never_lower_a_role(django_capture_on_commit_callbacks):
    """
    Someone there with a higher role keeps it, and isn't told; a lower one
    is raised.
    """
    workspace = _workspace()
    page = factories.DocumentFactory()
    user = factories.UserFactory()
    models.WorkspaceAccess.objects.create(
        workspace=workspace, user=user, role="administrator"
    )
    factories.UserDocumentAccessFactory(document=page, user=user, role="reader")

    with django_capture_on_commit_callbacks(execute=True):
        response = _client(_owner()).post(
            ADD,
            {
                "people": [str(user.id)],
                "places": [
                    {"kind": "workspace", "id": str(workspace.id), "role": "member"},
                    {"kind": "page", "id": str(page.id), "role": "editor"},
                ],
            },
            format="json",
        )

    results = [place["result"] for place in response.json()[0]["places"]]
    assert results == ["already", "raised"]
    assert workspace.accesses.get(user=user).role == "administrator"
    assert page.accesses.get(user=user).role == "editor"
    assert len(mail.outbox) == 1
    assert "the workspace" not in mail.outbox[0].subject


def test_placements_without_email(django_capture_on_commit_callbacks):
    """The owner may add people without telling them."""
    page = factories.DocumentFactory()
    user = factories.UserFactory()

    with django_capture_on_commit_callbacks(execute=True):
        response = _client(_owner()).post(
            ADD,
            {
                "people": [str(user.id)],
                "places": [{"kind": "page", "id": str(page.id), "role": "editor"}],
                "notify": False,
            },
            format="json",
        )

    assert response.status_code == 200
    assert page.accesses.get(user=user).role == "editor"
    assert not mail.outbox


@pytest.mark.parametrize(
    "place",
    [
        {"kind": "page", "role": "member"},
        {"kind": "workspace", "role": "editor"},
        {"kind": "space", "role": "editor"},
        {"kind": "folder", "role": "editor"},
    ],
)
def test_placements_refuse_wrong_places(place):
    """A role of another kind, a page given as a space, an unknown kind."""
    page = factories.DocumentFactory()
    workspace = _workspace()
    place["id"] = str(workspace.id if place["kind"] == "workspace" else page.id)
    user = factories.UserFactory()

    response = _client(_owner()).post(
        ADD, {"people": [str(user.id)], "places": [place]}, format="json"
    )

    assert response.status_code == 400
    assert not models.PlatformLog.objects.exists()


def test_placements_refuse_inactive_people():
    """Suspended or merged accounts aren't added."""
    page = factories.DocumentFactory()
    user = factories.UserFactory(is_active=False)

    response = _client(_owner()).post(
        ADD,
        {
            "people": [str(user.id)],
            "places": [{"kind": "page", "id": str(page.id), "role": "editor"}],
        },
        format="json",
    )

    assert response.status_code == 400
    assert not page.accesses.filter(user=user).exists()
