"""
Tests for the user groups of pages and spaces: made outside any workspace,
for mentions only, offered on their page and below it, and following the
page wherever it moves.
"""

from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from core import factories, models

pytestmark = pytest.mark.django_db


def client_for(user):
    """An API client logged in as the user."""
    client = APIClient()
    client.force_login(user)
    return client


def make_page_group(page, creator, members, name="Reviewers"):
    """A user group of a page, with its members."""
    group = models.Group.objects.create(document=page, name=name, created_by=creator)
    for member in members:
        models.GroupMembership.objects.create(group=group, user=member)
    return group


def mention_teams(user, document):
    """The teams the @ menu offers the user on a document."""
    response = client_for(user).get(
        f"/api/v1.0/groups/?document_id={document.id}"
        "&include_granted=true&every_workspace=true"
    )
    assert response.status_code == 200
    return [(team["label"], team["place"]["name"]) for team in response.json()]


def test_page_owners_create_user_groups_on_an_independent_page():
    """The owners and administrators of a page create its user groups."""
    owner, admin, editor = factories.UserFactory.create_batch(3)
    page = factories.DocumentFactory(
        title="Introduction",
        link_reach="restricted",
        users=[(owner, "owner"), (admin, "administrator"), (editor, "editor")],
    )
    url = f"/api/v1.0/documents/{page.id}/user-groups/"

    response = client_for(owner).post(
        url, {"name": "Reviewers", "kind": "organization"}
    )
    assert response.status_code == 201
    created = response.json()
    assert created["document"] == str(page.id)
    assert created["workspace"] is None
    # Only teams: an organization belongs to a workspace
    assert created["kind"] == "team"
    assert created["abilities"]["update"] is True

    assert client_for(admin).post(url, {"name": "Writers"}).status_code == 201
    assert client_for(editor).post(url, {"name": "Others"}).status_code == 403
    duplicate = client_for(admin).post(url, {"name": "Reviewers"})
    assert duplicate.status_code == 400

    listed = client_for(editor).get(url).json()
    assert [group["name"] for group in listed] == ["Reviewers", "Writers"]
    assert listed[0]["abilities"]["update"] is False


def test_people_who_cannot_see_the_page_cannot_see_its_groups():
    """A page's user groups are as private as the page."""
    owner, stranger = factories.UserFactory.create_batch(2)
    page = factories.DocumentFactory(link_reach="restricted", users=[(owner, "owner")])
    group = make_page_group(page, owner, [owner])

    url = f"/api/v1.0/documents/{page.id}/user-groups/"
    assert client_for(stranger).get(url).status_code == 404
    members_url = f"/api/v1.0/groups/{group.id}/members/"
    assert client_for(stranger).get(members_url).status_code == 404
    card = client_for(stranger).get(f"/api/v1.0/teams/{group.team}/").json()
    assert (card["known"], card["members"]) == (False, [])


def test_anyone_can_join_a_page_group():
    """No workspace needed: the page's owners add anyone they can find."""
    owner, ada, editor = factories.UserFactory.create_batch(3)
    page = factories.DocumentFactory(
        link_reach="restricted", users=[(owner, "owner"), (editor, "editor")]
    )
    group = make_page_group(page, owner, [])
    url = f"/api/v1.0/groups/{group.id}/members/"

    assert client_for(owner).post(url, {"user_id": str(ada.id)}).status_code == 201
    assert client_for(editor).post(url, {"user_id": str(editor.id)}).status_code == 403
    assert [m["user"]["id"] for m in client_for(editor).get(url).json()] == [
        str(ada.id)
    ]
    card = client_for(editor).get(f"/api/v1.0/teams/{group.team}/").json()
    assert card["known"] is True
    assert card["place"]["name"] == page.title
    assert [member["id"] for member in card["members"]] == [str(ada.id)]


def test_the_creator_manages_their_page_group():
    """Like in a workspace, the creator manages the group they made."""
    owner, creator, editor = factories.UserFactory.create_batch(3)
    page = factories.DocumentFactory(
        link_reach="restricted",
        users=[(owner, "owner"), (creator, "editor"), (editor, "editor")],
    )
    group = make_page_group(page, creator, [])
    url = f"/api/v1.0/documents/{page.id}/user-groups/{group.id}/"

    assert client_for(editor).patch(url, {"name": "X"}).status_code == 403
    assert client_for(creator).patch(url, {"name": "Proofreaders"}).status_code == 200
    assert client_for(editor).delete(url).status_code == 403
    assert client_for(creator).delete(url).status_code == 204
    assert not models.Group.objects.exists()


def test_page_groups_never_give_access():
    """Joining a page's group gives no role; it cannot be shared with."""
    owner, member = factories.UserFactory.create_batch(2)
    page = factories.DocumentFactory(link_reach="restricted", users=[(owner, "owner")])
    group = make_page_group(page, owner, [member])

    assert group.team not in models.User.objects.get(pk=member.pk).teams
    response = client_for(owner).post(
        f"/api/v1.0/documents/{page.id}/accesses/",
        {"team": group.team, "role": "editor"},
    )
    assert response.status_code == 400
    assert not models.DocumentAccess.objects.filter(team=group.team).exists()
    # Not offered for sharing either
    shared = client_for(owner).get(f"/api/v1.0/groups/?document_id={page.id}")
    assert shared.json() == []


def test_mentioning_a_page_group_notifies_its_members_who_can_see_it():
    """Mentions only: members without access to the page are not notified."""
    owner, reader, outsider = factories.UserFactory.create_batch(3)
    page = factories.DocumentFactory(
        link_reach="restricted", users=[(owner, "owner"), (reader, "reader")]
    )
    group = make_page_group(page, owner, [reader, outsider])

    response = client_for(owner).post(
        f"/api/v1.0/documents/{page.id}/mention/",
        {"anchor_id": str(uuid4()), "mentioned_team": group.team},
    )

    assert response.status_code == 201
    assert [m["mentioned_user_id"] for m in response.json()] == [str(reader.id)]


def test_a_page_group_is_mentioned_only_on_its_page_and_below():
    """Its group is offered on the page and its sub-pages, nowhere else."""
    owner, member = factories.UserFactory.create_batch(2)
    page = factories.DocumentFactory(
        title="Introduction", link_reach="restricted", users=[(owner, "owner")]
    )
    child = factories.DocumentFactory(parent=page, title="Chapter 1")
    other = factories.DocumentFactory(
        title="Elsewhere", link_reach="restricted", users=[(owner, "owner")]
    )
    models.DocumentAccess.objects.create(document=other, user=member, role="reader")
    models.DocumentAccess.objects.create(document=page, user=member, role="reader")
    make_page_group(page, owner, [member])
    make_page_group(child, owner, [member], name="Chapter team")

    assert mention_teams(owner, page) == [("Reviewers", "Introduction")]
    # The closest first
    assert mention_teams(owner, child) == [
        ("Chapter team", "Chapter 1"),
        ("Reviewers", "Introduction"),
    ]
    assert mention_teams(owner, other) == []

    # Mentioned elsewhere by its id, it notifies nobody
    group = models.Group.objects.get(name="Reviewers")
    response = client_for(owner).post(
        f"/api/v1.0/documents/{other.id}/mention/",
        {"anchor_id": str(uuid4()), "mentioned_team": group.team},
    )
    assert response.status_code == 201
    assert response.json() == []


def test_page_groups_follow_their_page_into_a_space():
    """Moved into a space, a page keeps its groups, offered on it as before."""
    owner = factories.UserFactory()
    page = factories.DocumentFactory(
        title="Introduction", link_reach="restricted", users=[(owner, "owner")]
    )
    space = factories.DocumentFactory(
        title="Handbook",
        kind="space",
        link_reach="restricted",
        users=[(owner, "owner")],
    )
    make_page_group(space, owner, [owner], name="Handbook team")
    make_page_group(page, owner, [owner])

    page.move(space, pos="last-child")
    page.refresh_from_db()

    assert mention_teams(owner, page) == [
        ("Reviewers", "Introduction"),
        ("Handbook team", "Handbook"),
    ]
    assert models.Group.objects.get(name="Reviewers").document == page
