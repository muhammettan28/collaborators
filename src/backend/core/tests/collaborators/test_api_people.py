"""Tests for the people a collaborator works with (mentions without typing)."""

import pytest
from rest_framework.test import APIClient

from core import factories, models

pytestmark = pytest.mark.django_db


def test_people_lists_close_people_without_a_minimum_length():
    """Co-members and people sharing a page show, filtered by any text."""
    # (a fixed email: a random one could match the letters searched below)
    user = factories.UserFactory(full_name="Ada Lovelace", email="ada@z.test")
    sharer = factories.UserFactory(full_name="Bo Li", email="bo@x.test")
    co_member = factories.UserFactory(full_name="Cy Ng", email="cy@y.test")
    stranger = factories.UserFactory(full_name="Bo Stranger")
    factories.DocumentFactory(users=[(user, "owner"), (sharer, "editor")])
    workspace = models.Workspace.objects.create(name="Acme")
    models.WorkspaceAccess.objects.create(workspace=workspace, user=user)
    models.WorkspaceAccess.objects.create(workspace=workspace, user=co_member)
    client = APIClient()
    client.force_login(user)

    everyone = client.get("/api/v1.0/people/").json()
    # Oneself first, then the people around
    assert everyone[0]["id"] == str(user.id)
    assert {person["id"] for person in everyone} == {
        str(user.id),
        str(sharer.id),
        str(co_member.id),
    }

    by_letter = client.get("/api/v1.0/people/?q=b").json()
    assert [person["id"] for person in by_letter] == [str(sharer.id)]
    myself = client.get("/api/v1.0/people/?q=ada").json()
    assert [person["id"] for person in myself] == [str(user.id)]
    assert str(stranger.id) not in {person["id"] for person in everyone}


def test_people_shows_a_newcomer_to_everyone_on_the_page_at_once():
    """Sharing a page with someone puts them in the owner's list right away."""
    owner = factories.UserFactory()
    newcomer = factories.UserFactory()
    document = factories.DocumentFactory(users=[(owner, "owner")])
    client = APIClient()
    client.force_login(owner)
    # The owner's list is computed (and kept) before the page is shared
    assert str(newcomer.id) not in {
        person["id"] for person in client.get("/api/v1.0/people/").json()
    }

    factories.UserDocumentAccessFactory(document=document, user=newcomer)

    assert str(newcomer.id) in {
        person["id"] for person in client.get("/api/v1.0/people/").json()
    }


def test_people_needs_authentication():
    """Only signed-in collaborators have people around them."""
    assert APIClient().get("/api/v1.0/people/").status_code == 401


def test_person_card_for_someone_one_works_with():
    """Name, email, shared workspaces and their groups there."""
    me, ada = factories.UserFactory(), factories.UserFactory(full_name="Ada L")
    acme = models.Workspace.objects.create(name="Acme")
    other = models.Workspace.objects.create(name="Other")
    for user in (me, ada):
        models.WorkspaceAccess.objects.create(workspace=acme, user=user)
    models.WorkspaceAccess.objects.create(workspace=other, user=ada)
    q4 = models.Group.objects.create(workspace=acme, name="Q4")
    hidden = models.Group.objects.create(workspace=other, name="Hidden")
    for group in (q4, hidden):
        models.GroupMembership.objects.create(group=group, user=ada)
    client = APIClient()
    client.force_login(me)

    card = client.get(f"/api/v1.0/people/{ada.id}/").json()

    assert card["known"] is True
    assert card["full_name"] == "Ada L"
    assert card["email"] == ada.email
    assert card["workspaces"] == [{"id": str(acme.id), "name": "Acme"}]
    assert card["groups"] == [{"id": str(q4.id), "name": "Q4"}]


def test_person_card_of_a_stranger_shows_only_the_name():
    """No email nor workspaces for someone one doesn't work with."""
    me, stranger = factories.UserFactory(), factories.UserFactory(full_name="Zed")
    client = APIClient()
    client.force_login(me)

    card = client.get(f"/api/v1.0/people/{stranger.id}/").json()

    assert card["known"] is False
    assert card["full_name"] == "Zed"
    assert card["email"] == ""
    assert card["workspaces"] == []
    assert APIClient().get(f"/api/v1.0/people/{stranger.id}/").status_code == 401


def _acme_with_q4():
    """A workspace with a group: Ada manages it, Bob is in it."""
    acme = models.Workspace.objects.create(name="Acme")
    ada = factories.UserFactory(full_name="Ada L")
    bob = factories.UserFactory(full_name="Bob M")
    models.WorkspaceAccess.objects.create(
        workspace=acme, user=ada, role=models.WorkspaceRoleChoices.ADMIN
    )
    models.WorkspaceAccess.objects.create(workspace=acme, user=bob)
    q4 = models.Group.objects.create(workspace=acme, name="Q4")
    models.GroupMembership.objects.create(group=q4, user=bob)
    models.GroupMembership.objects.create(group=q4, user=ada, is_manager=True)
    return acme, q4, ada, bob


def test_group_card_lists_the_members_managers_first():
    """People of the workspace see who is in a mentioned group."""
    acme, q4, _ada, bob = _acme_with_q4()
    client = APIClient()
    client.force_login(bob)

    card = client.get(f"/api/v1.0/teams/group:{q4.id}/").json()

    assert card["known"] is True
    assert card["name"] == "Q4"
    assert card["kind"] == "team"
    assert card["workspace"] == {"id": str(acme.id), "name": "Acme"}
    assert card["member_count"] == 2
    assert [
        (member["full_name"], member["is_manager"], member["is_me"])
        for member in card["members"]
    ] == [("Ada L", True, False), ("Bob M", False, True)]


def test_group_card_of_a_whole_workspace_and_its_administrators():
    """ "All members of Acme" lists everyone; its administrators, only them."""
    acme, _q4, ada, bob = _acme_with_q4()
    client = APIClient()
    client.force_login(bob)

    everyone = client.get(f"/api/v1.0/teams/workspace:{acme.id}/").json()
    admins = client.get(f"/api/v1.0/teams/workspace-admins:{acme.id}/").json()

    assert everyone["name"] == "All members of Acme"
    assert everyone["kind"] == "workspace"
    assert {member["id"] for member in everyone["members"]} == {
        str(ada.id),
        str(bob.id),
    }
    assert admins["kind"] == "workspace-admins"
    assert [member["id"] for member in admins["members"]] == [str(ada.id)]


def test_group_card_outside_the_workspace_shows_only_the_name():
    """Someone not in the group's workspace doesn't see its members."""
    _acme, q4, _ada, _bob = _acme_with_q4()
    client = APIClient()
    client.force_login(factories.UserFactory())

    card = client.get(f"/api/v1.0/teams/group:{q4.id}/").json()

    assert card["known"] is False
    assert card["name"] == "Q4"
    assert card["workspace"] is None
    assert card["members"] == []
    assert card["member_count"] == 0


def test_group_card_unknown_or_signed_out():
    """An unknown team is not found; signed out, nothing is shown."""
    _acme, q4, _ada, bob = _acme_with_q4()
    client = APIClient()
    client.force_login(bob)

    assert client.get("/api/v1.0/teams/group:nope/").status_code == 404
    assert (
        client.get(f"/api/v1.0/teams/group:{factories.UserFactory().id}/").status_code
        == 404
    )
    assert APIClient().get(f"/api/v1.0/teams/group:{q4.id}/").status_code == 401


def test_people_show_the_address_chosen_on_the_profile():
    """The card, the pickers and My Collaborators: the profile's address."""
    me, ada = factories.UserFactory(), factories.UserFactory(full_name="Ada L")
    acme = models.Workspace.objects.create(name="Acme")
    for user in (me, ada):
        models.WorkspaceAccess.objects.create(workspace=acme, user=user)
    models.SignInIdentity.objects.create(
        user=ada, provider="google", sub="g-2", account="ada@work.example"
    )
    models.UserProfile.objects.create(user=ada, shown_email="ada@work.example")
    client = APIClient()
    client.force_login(me)

    card = client.get(f"/api/v1.0/people/{ada.id}/").json()
    assert card["email"] == "ada@work.example"

    people = client.get("/api/v1.0/people/?q=work.example").json()
    assert [(person["id"], person["email"]) for person in people] == [
        (str(ada.id), "ada@work.example")
    ]

    directory = client.get("/api/v1.0/people/directory/?q=work.example").json()
    assert [(person["id"], person["email"]) for person in directory] == [
        (str(ada.id), "ada@work.example")
    ]
