"""
Tests for "My Collaborators" (GET /api/v1.0/people/directory/): the people
one shares a workspace, a space or a page with, and only them (besides those
who let everyone find them).
"""

from django.db import connection
from django.test.utils import CaptureQueriesContext

import pytest
from rest_framework.test import APIClient

from core import factories, models

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.usefixtures("people_privacy"),
]

DIRECTORY = "/api/v1.0/people/directory/"


@pytest.fixture(name="people_privacy")
def fixture_people_privacy(settings):
    """Collaborators' rule on (Docs' own tests run without it)."""
    settings.COLLABORATORS_PEOPLE_PRIVACY = True


def directory(user):
    """What "My Collaborators" lists for the user."""
    client = APIClient()
    client.force_login(user)
    response = client.get(DIRECTORY)
    assert response.status_code == 200
    return response.json()


def colleagues(user):
    """The names of the people the user shares something with."""
    return sorted(
        person["full_name"] for person in directory(user) if person["is_colleague"]
    )


def person(name):
    """A collaborator with this name."""
    return factories.UserFactory(full_name=name)


def test_my_collaborators_is_empty_with_nobody_around():
    """A newcomer sees nobody, not even the other collaborators of the platform."""
    me = person("Me")
    person("Sam Stranger")
    factories.DocumentFactory(users=[(person("Other Owner"), "owner")])

    assert directory(me) == []


def test_my_collaborators_needs_authentication():
    """Signed out: nothing."""
    assert APIClient().get(DIRECTORY).status_code == 401


def test_my_collaborators_lists_workspace_co_members_with_the_workspace():
    """The workspaces both are members of are named; oneself is left out."""
    me, ada = person("Me"), person("Ada")
    person("Sam Stranger")
    for name in ("Acme", "Beta"):
        workspace = models.Workspace.objects.create(name=name)
        for user in (me, ada):
            models.WorkspaceAccess.objects.create(workspace=workspace, user=user)
    alone = models.Workspace.objects.create(name="Mine alone")
    models.WorkspaceAccess.objects.create(workspace=alone, user=me)

    people = directory(me)

    assert [(item["full_name"], item["workspaces"]) for item in people] == [
        ("Ada", ["Acme", "Beta"])
    ]
    assert people[0]["is_colleague"] is True


def test_my_collaborators_lists_people_of_the_same_page():
    """A page shared both ways; a page of someone else's doesn't count."""
    me, ada, bo = person("Me"), person("Ada"), person("Bo")
    factories.DocumentFactory(users=[(me, "owner"), (ada, "editor")])
    factories.DocumentFactory(users=[(bo, "owner")])

    assert colleagues(me) == ["Ada"]
    assert colleagues(ada) == ["Me"]
    assert colleagues(bo) == []


def test_my_collaborators_follows_the_page_tree():
    """A role on a space reaches its pages, down to the lowest, and back up."""
    me, reader, deep = person("Me"), person("Reader"), person("Deep")
    space = factories.DocumentFactory(kind="space", users=[(me, "owner")])
    page = factories.DocumentFactory(parent=space, users=[(reader, "reader")])
    factories.DocumentFactory(parent=page, users=[(deep, "editor")])

    assert colleagues(me) == ["Deep", "Reader"]
    assert colleagues(deep) == ["Me", "Reader"]


def test_my_collaborators_leaves_out_side_by_side_pages():
    """Two pages of a space, without a role on the space: nothing shared."""
    me, ada = person("Me"), person("Ada")
    space = factories.DocumentFactory(kind="space")
    factories.DocumentFactory(parent=space, users=[(me, "owner")])
    factories.DocumentFactory(parent=space, users=[(ada, "owner")])

    assert colleagues(me) == []
    assert colleagues(ada) == []


def test_my_collaborators_counts_groups_and_whole_workspaces():
    """A page shared with a group, or with a workspace: each of its members."""
    me, grace, gail = person("Me"), person("Grace"), person("Gail")
    admin = person("Admin")
    workspace = models.Workspace.objects.create(name="Acme")
    models.WorkspaceAccess.objects.create(workspace=workspace, user=grace)
    models.WorkspaceAccess.objects.create(workspace=workspace, user=gail)
    models.WorkspaceAccess.objects.create(
        workspace=workspace, user=admin, role="administrator"
    )
    group = models.Group.objects.create(workspace=workspace, name="Q4")
    models.GroupMembership.objects.create(group=group, user=grace)
    page = factories.DocumentFactory(users=[(me, "owner")])
    models.DocumentAccess.objects.create(
        document=page, team=models.make_team(models.TEAM_GROUP, group.id), role="reader"
    )
    assert colleagues(me) == ["Grace"]

    other = factories.DocumentFactory(users=[(me, "owner")])
    models.DocumentAccess.objects.create(
        document=other,
        team=models.make_team(models.TEAM_WORKSPACE_ADMINS, workspace.id),
        role="editor",
    )
    assert colleagues(me) == ["Admin", "Grace"]

    models.DocumentAccess.objects.create(
        document=other,
        team=models.make_team(models.TEAM_WORKSPACE, workspace.id),
        role="reader",
    )
    assert colleagues(me) == ["Admin", "Gail", "Grace"]
    # the other way round: the member sees the owner of the page
    assert colleagues(gail) == ["Admin", "Grace", "Me"]


def test_my_collaborators_counts_a_page_linked_into_a_space():
    """The people of a space into which a page is linked may read it."""
    me, linker, stranger = person("Me"), person("Linker"), person("Stranger")
    home = factories.DocumentFactory(kind="space", users=[(me, "owner")])
    page = factories.DocumentFactory(parent=home)
    other = factories.DocumentFactory(kind="space", users=[(linker, "reader")])
    factories.DocumentFactory(kind="space", users=[(stranger, "owner")])
    assert colleagues(me) == []

    link = models.PageSpaceLink.objects.create(page=page, space=other)

    assert colleagues(me) == ["Linker"]
    assert colleagues(linker) == ["Me"]
    assert colleagues(stranger) == []

    link.delete()

    assert colleagues(me) == []
    assert colleagues(linker) == []


def test_my_collaborators_leaves_out_pages_in_the_trashbin():
    """A trashed page is lost to the others; restored, it connects them again."""
    me, ada = person("Me"), person("Ada")
    page = factories.DocumentFactory(users=[(me, "owner"), (ada, "editor")])
    assert colleagues(me) == ["Ada"]

    page.soft_delete()
    assert colleagues(me) == []
    assert colleagues(ada) == []

    page.refresh_from_db()
    page.restore()
    assert colleagues(me) == ["Ada"]


def test_my_collaborators_leaves_out_suspended_accounts():
    """An account no longer active doesn't show."""
    me, gone = person("Me"), person("Gone")
    factories.DocumentFactory(users=[(me, "owner"), (gone, "editor")])
    gone.is_active = False
    gone.save()

    assert directory(me) == []


def test_my_collaborators_open_people_come_after_colleagues():
    """Who lets everyone find them shows too, apart, with no workspace named."""
    me, ada, olga = person("Me"), person("Ada"), person("Olga Open")
    models.UserProfile.objects.create(user=olga, reach="platform")
    models.UserProfile.objects.create(user=me, reach="platform")
    factories.DocumentFactory(users=[(me, "owner"), (ada, "editor")])

    people = directory(me)

    assert [(item["full_name"], item["is_colleague"]) for item in people] == [
        ("Ada", True),
        ("Olga Open", False),
    ]
    assert people[1]["workspaces"] == []


def _queries_for(size):
    """The queries "My Collaborators" makes for this many colleagues."""
    me = person(f"Me {size}")
    workspace = models.Workspace.objects.create(name=f"Acme {size}")
    models.WorkspaceAccess.objects.create(workspace=workspace, user=me)
    group = models.Group.objects.create(workspace=workspace, name=f"G {size}")
    page = factories.DocumentFactory(kind="space", users=[(me, "owner")])
    for index in range(size):
        member = person(f"Member {size} {index}")
        models.WorkspaceAccess.objects.create(workspace=workspace, user=member)
        models.UserProfile.objects.create(user=member, headline="Hi")
        sharer = person(f"Sharer {size} {index}")
        factories.DocumentFactory(parent=page, users=[(sharer, "editor")])
        grouped = person(f"Grouped {size} {index}")
        models.GroupMembership.objects.create(group=group, user=grouped)
        other = factories.DocumentFactory(users=[(me, "reader")])
        models.DocumentAccess.objects.create(
            document=other,
            team=models.make_team(models.TEAM_GROUP, group.id),
            role="reader",
        )
    client = APIClient()
    client.force_login(me)
    with CaptureQueriesContext(connection) as queries:
        response = client.get(DIRECTORY)
    assert len(response.json()) == 3 * size
    return len(queries)


def test_my_collaborators_makes_no_query_per_person():
    """As many queries for 2 people of each kind as for 8."""
    assert _queries_for(2) == _queries_for(8)
