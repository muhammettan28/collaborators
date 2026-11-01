"""
Tests for the Collaborators spaces API: creating spaces with a visibility and
editors, listing them per workspace, independent spaces, sharing a space with
other workspaces, and the grants those workspaces make to their groups.
"""

import pytest
from rest_framework.test import APIClient

from core import factories, models
from core.choices import RoleChoices, WorkspaceRoleChoices

pytestmark = pytest.mark.django_db


def make_workspace(owner, name="Acme", members=()):
    """Create a workspace with its owner and members."""
    workspace = models.Workspace.objects.create(name=name)
    models.WorkspaceAccess.objects.create(
        workspace=workspace, user=owner, role=WorkspaceRoleChoices.OWNER
    )
    for user in members:
        models.WorkspaceAccess.objects.create(workspace=workspace, user=user)
    return workspace


def client_for(user):
    """An API client logged in as the user."""
    client = APIClient()
    client.force_login(user)
    return client


def fresh(user):
    """Reload a user so that its cached teams are recomputed."""
    return models.User.objects.get(pk=user.pk)


# -- Creation


def test_api_spaces_create_visible_to_workspace_members():
    """
    "All workspace members" lets members read the space and its pages, the
    chosen group edit it, and the workspace administrators own it.
    """
    owner, member, editor, outsider = factories.UserFactory.create_batch(4)
    workspace = make_workspace(owner, members=[member, editor])
    group = models.Group.objects.create(workspace=workspace, name="Q4 Launch")
    models.GroupMembership.objects.create(group=group, user=editor)

    response = client_for(member).post(
        "/api/v1.0/spaces/",
        {
            "title": "Engineering",
            "workspace_id": str(workspace.id),
            "visibility": "workspace",
            "editor_group_ids": [str(group.id)],
        },
        format="json",
    )

    assert response.status_code == 201
    data = response.json()
    assert data["kind"] == "space"
    assert data["home_workspace"]["id"] == str(workspace.id)
    space = models.Document.objects.get(id=data["id"])
    page = factories.DocumentFactory(parent=space)

    assert space.get_role(fresh(member)) == RoleChoices.OWNER
    assert page.get_role(fresh(editor)) == RoleChoices.EDITOR
    assert page.get_role(fresh(owner)) == RoleChoices.OWNER  # workspace owner
    assert page.get_role(fresh(outsider)) is None
    assert space.link_reach == "restricted"


def test_api_spaces_create_public_is_read_only_for_everyone():
    """A public space is readable by anyone, editable by nobody through its link."""
    owner = factories.UserFactory()
    workspace = make_workspace(owner)

    response = client_for(owner).post(
        "/api/v1.0/spaces/",
        {
            "title": "Handbook",
            "workspace_id": str(workspace.id),
            "visibility": "public",
        },
        format="json",
    )

    space = models.Document.objects.get(id=response.json()["id"])
    assert (space.link_reach, space.link_role) == ("public", "reader")
    anonymous = APIClient().get(f"/api/v1.0/documents/{space.id}/")
    assert anonymous.status_code == 200
    assert anonymous.json()["abilities"]["update"] is False


def test_api_spaces_create_invited_with_editors():
    """An invite-only space is only open to its creator and chosen editors."""
    owner, editor, member = factories.UserFactory.create_batch(3)
    workspace = make_workspace(owner, members=[editor, member])

    response = client_for(owner).post(
        "/api/v1.0/spaces/",
        {
            "title": "Board",
            "workspace_id": str(workspace.id),
            "visibility": "invited",
            "editor_user_ids": [str(editor.id)],
        },
        format="json",
    )

    space = models.Document.objects.get(id=response.json()["id"])
    assert space.get_role(fresh(editor)) == RoleChoices.EDITOR
    assert space.get_role(fresh(member)) is None


def test_api_spaces_create_needs_workspace_membership():
    """Nobody creates a space in a workspace they don't belong to."""
    owner, outsider = factories.UserFactory.create_batch(2)
    workspace = make_workspace(owner)

    response = client_for(outsider).post(
        "/api/v1.0/spaces/",
        {"title": "X", "workspace_id": str(workspace.id)},
        format="json",
    )

    assert response.status_code == 400
    assert not models.Document.objects.exists()


def test_api_spaces_create_rejects_groups_of_other_workspaces():
    """Editor groups must belong to the space's workspace."""
    owner = factories.UserFactory()
    workspace = make_workspace(owner)
    other = make_workspace(owner, name="Other")
    group = models.Group.objects.create(workspace=other, name="G")

    response = client_for(owner).post(
        "/api/v1.0/spaces/",
        {
            "title": "X",
            "workspace_id": str(workspace.id),
            "editor_group_ids": [str(group.id)],
        },
        format="json",
    )

    assert response.status_code == 400


def test_api_spaces_create_independent():
    """Without a workspace, the space is independent and private to its creator."""
    user = factories.UserFactory()

    response = client_for(user).post(
        "/api/v1.0/spaces/", {"title": "Research"}, format="json"
    )

    assert response.status_code == 201
    assert response.json()["home_workspace"] is None
    listed = client_for(user).get("/api/v1.0/spaces/?independent=true").json()
    assert [s["title"] for s in listed] == ["Research"]


def test_api_spaces_create_independent_cant_target_workspace_members():
    """An independent space has no workspace members to open to."""
    user = factories.UserFactory()

    response = client_for(user).post(
        "/api/v1.0/spaces/",
        {"title": "Research", "visibility": "workspace"},
        format="json",
    )

    assert response.status_code == 400


# -- Listing


def test_api_spaces_list_per_workspace_only_readable_ones():
    """Members see the spaces of the workspace they can read."""
    owner, member = factories.UserFactory.create_batch(2)
    workspace = make_workspace(owner, members=[member])
    client = client_for(owner)
    for title, visibility in [("Open", "workspace"), ("Private", "invited")]:
        client.post(
            "/api/v1.0/spaces/",
            {
                "title": title,
                "workspace_id": str(workspace.id),
                "visibility": visibility,
            },
            format="json",
        )

    url = f"/api/v1.0/spaces/?workspace={workspace.id}"
    assert [s["title"] for s in client_for(member).get(url).json()] == ["Open"]
    assert [s["title"] for s in client.get(url).json()] == ["Open", "Private"]


def test_api_spaces_list_per_workspace_says_what_members_get():
    """
    Each space of a workspace's list says the role all its members have on
    it (to invite someone to it only for more), none when only invited.
    """
    owner = factories.UserFactory()
    workspace = make_workspace(owner)
    client = client_for(owner)
    for title, visibility in [("Open", "workspace"), ("Private", "invited")]:
        client.post(
            "/api/v1.0/spaces/",
            {
                "title": title,
                "workspace_id": str(workspace.id),
                "visibility": visibility,
            },
            format="json",
        )
    space = models.Document.objects.get(title="Open")
    models.DocumentAccess.objects.filter(
        document=space, team=f"workspace:{workspace.id}"
    ).update(role=RoleChoices.EDITOR)

    listed = client.get(f"/api/v1.0/spaces/?workspace={workspace.id}").json()
    assert [(s["title"], s["members_role"]) for s in listed] == [
        ("Open", "editor"),
        ("Private", None),
    ]
    # Not about any workspace elsewhere
    assert client.get(f"/api/v1.0/spaces/{space.id}/").json()["members_role"] is None


def test_api_spaces_list_hidden_from_non_members():
    """Listing the spaces of a workspace needs to belong to it."""
    owner, outsider = factories.UserFactory.create_batch(2)
    workspace = make_workspace(owner)
    client_for(owner).post(
        "/api/v1.0/spaces/",
        {"title": "Public", "workspace_id": str(workspace.id), "visibility": "public"},
        format="json",
    )

    response = client_for(outsider).get(f"/api/v1.0/spaces/?workspace={workspace.id}")

    assert response.json() == []


def test_api_documents_list_excludes_spaces():
    """The documents list keeps to pages; spaces are listed by the spaces API."""
    user = factories.UserFactory()
    factories.DocumentFactory(users=[(user, "owner")], title="Page")
    factories.DocumentFactory(users=[(user, "owner")], title="Space", kind="space")

    response = client_for(user).get("/api/v1.0/documents/")

    assert [d["title"] for d in response.json()["results"]] == ["Page"]


def test_api_documents_list_independent_pages():
    """independent=true keeps the pages in no space, nor under another page."""
    user = factories.UserFactory()
    factories.DocumentFactory(users=[(user, "owner")], title="Free page")
    space = factories.DocumentFactory(title="Space", kind="space")
    factories.DocumentFactory(parent=space, users=[(user, "owner")], title="In space")

    client = client_for(user)
    every = client.get("/api/v1.0/documents/").json()["results"]
    independent = client.get("/api/v1.0/documents/?independent=true").json()

    assert sorted(d["title"] for d in every) == ["Free page", "In space"]
    assert [d["title"] for d in independent["results"]] == ["Free page"]


def test_api_documents_move_rejects_spaces():
    """A space stays a root: it can't be moved under another document."""
    user = factories.UserFactory()
    space = factories.DocumentFactory(users=[(user, "owner")], kind="space")
    target = factories.DocumentFactory(users=[(user, "owner")])

    response = client_for(user).post(
        f"/api/v1.0/documents/{space.id}/move/",
        {"target_document_id": str(target.id), "position": "first-child"},
        format="json",
    )

    assert response.status_code == 400


# -- Moving an independent space into a workspace


def test_api_spaces_move_to_workspace():
    """The owner of an independent space places it in one of their workspaces."""
    user, admin = factories.UserFactory.create_batch(2)
    workspace = make_workspace(user)
    models.WorkspaceAccess.objects.create(
        workspace=workspace, user=admin, role=WorkspaceRoleChoices.ADMIN
    )
    space_id = (
        client_for(user)
        .post("/api/v1.0/spaces/", {"title": "Research"}, format="json")
        .json()["id"]
    )

    response = client_for(user).post(
        f"/api/v1.0/spaces/{space_id}/move-to-workspace/",
        {"workspace_id": str(workspace.id)},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["home_workspace"]["id"] == str(workspace.id)
    space = models.Document.objects.get(id=space_id)
    assert space.get_role(fresh(admin)) == RoleChoices.OWNER


# -- Shared spaces


def test_api_spaces_links_share_and_grant_groups():
    """
    Home administrators share a space with another workspace, whose
    administrators then grant it to their own groups.
    """
    home_owner, partner_owner, partner_member = factories.UserFactory.create_batch(3)
    home = make_workspace(home_owner, name="Acme")
    partner = make_workspace(partner_owner, name="Partner", members=[partner_member])
    models.WorkspaceAccess.objects.create(workspace=partner, user=home_owner)
    group = models.Group.objects.create(workspace=partner, name="Partner Q4")
    models.GroupMembership.objects.create(group=group, user=partner_member)
    space_id = (
        client_for(home_owner)
        .post(
            "/api/v1.0/spaces/",
            {"title": "Q4 Launch", "workspace_id": str(home.id)},
            format="json",
        )
        .json()["id"]
    )

    response = client_for(home_owner).post(
        f"/api/v1.0/spaces/{space_id}/links/",
        {"workspace_id": str(partner.id)},
        format="json",
    )
    assert response.status_code == 201
    linked = client_for(partner_owner).get(f"/api/v1.0/spaces/?workspace={partner.id}")
    assert linked.json() == []  # shared, but not granted to anyone there yet

    grants_url = f"/api/v1.0/spaces/{space_id}/workspace-grants/"
    response = client_for(partner_member).post(
        grants_url, {"team": group.team, "role": "editor"}, format="json"
    )
    assert response.status_code == 403  # not a partner administrator

    response = client_for(partner_owner).post(
        grants_url, {"team": group.team, "role": "editor"}, format="json"
    )
    assert response.status_code == 201
    space = models.Document.objects.get(id=space_id)
    assert space.get_role(fresh(partner_member)) == RoleChoices.EDITOR
    assert [g["team"] for g in client_for(partner_owner).get(grants_url).json()] == [
        group.team
    ]

    # Unlinking removes what the partner granted
    response = client_for(partner_owner).delete(
        f"/api/v1.0/spaces/{space_id}/links/",
        {"workspace_id": str(partner.id)},
        format="json",
    )
    assert response.status_code == 204
    assert space.get_role(fresh(partner_member)) is None


def test_api_spaces_workspace_grants_reject_unlinked_workspaces():
    """Administrators can't grant their groups on spaces not shared with them."""
    home_owner, other_owner = factories.UserFactory.create_batch(2)
    home = make_workspace(home_owner)
    other = make_workspace(other_owner, name="Other")
    group = models.Group.objects.create(workspace=other, name="G")
    space_id = (
        client_for(home_owner)
        .post(
            "/api/v1.0/spaces/",
            {"title": "S", "workspace_id": str(home.id)},
            format="json",
        )
        .json()["id"]
    )

    response = client_for(other_owner).post(
        f"/api/v1.0/spaces/{space_id}/workspace-grants/",
        {"team": group.team, "role": "editor"},
        format="json",
    )

    assert response.status_code == 403


# -- Grantable teams (share modal)


def test_api_groups_grantable_teams_for_a_page_in_a_space():
    """The share modal offers the groups and members of the space's workspaces."""
    owner = factories.UserFactory()
    workspace = make_workspace(owner)
    group = models.Group.objects.create(workspace=workspace, name="Q4 Launch")
    space_id = (
        client_for(owner)
        .post(
            "/api/v1.0/spaces/",
            {"title": "S", "workspace_id": str(workspace.id)},
            format="json",
        )
        .json()["id"]
    )
    page = factories.DocumentFactory(parent=models.Document.objects.get(id=space_id))

    results = (
        client_for(owner).get(f"/api/v1.0/groups/?document_id={page.id}&q=q4").json()
    )

    assert [(r["team"], r["label"]) for r in results] == [(group.team, "Q4 Launch")]


def test_api_document_accesses_show_team_labels():
    """Team accesses come with a readable label."""
    owner = factories.UserFactory()
    workspace = make_workspace(owner)
    group = models.Group.objects.create(workspace=workspace, name="Q4 Launch")
    document = factories.DocumentFactory(users=[(owner, "owner")])
    models.DocumentAccess.objects.create(document=document, team=group.team)

    accesses = client_for(owner).get(f"/api/v1.0/documents/{document.id}/accesses/")

    labels = {a["team_label"] for a in accesses.json() if a["team"]}
    assert labels == {"Q4 Launch (Acme)"}


def test_api_groups_grantable_teams_leave_out_granted_ones():
    """Teams that already have a role on the document are not offered again."""
    owner = factories.UserFactory()
    workspace = make_workspace(owner)
    group = models.Group.objects.create(workspace=workspace, name="Q4 Launch")
    space_id = (
        client_for(owner)
        .post(
            "/api/v1.0/spaces/",
            {
                "title": "S",
                "workspace_id": str(workspace.id),
                "visibility": "workspace",
            },
            format="json",
        )
        .json()["id"]
    )

    results = client_for(owner).get(f"/api/v1.0/groups/?document_id={space_id}")

    # "All members of Acme" already reads the space
    assert [r["team"] for r in results.json()] == [group.team]


def test_api_groups_for_mentions_cover_every_workspace_of_the_user():
    """For "@", the groups of all my workspaces show, the page's own first."""
    owner = factories.UserFactory()
    home = make_workspace(owner, name="Zeta")
    other = make_workspace(owner, name="Acme")
    stranger_workspace = models.Workspace.objects.create(name="Elsewhere")
    home_group = models.Group.objects.create(workspace=home, name="Q4 Launch")
    other_group = models.Group.objects.create(workspace=other, name="Design")
    models.Group.objects.create(workspace=stranger_workspace, name="Hidden")
    space_id = (
        client_for(owner)
        .post(
            "/api/v1.0/spaces/",
            {"title": "S", "workspace_id": str(home.id)},
            format="json",
        )
        .json()["id"]
    )

    results = (
        client_for(owner)
        .get(
            f"/api/v1.0/groups/?document_id={space_id}"
            "&include_granted=true&every_workspace=true"
        )
        .json()
    )

    assert [r["team"] for r in results] == [
        models.make_team(models.TEAM_WORKSPACE, home.id),
        home_group.team,
        models.make_team(models.TEAM_WORKSPACE, other.id),
        other_group.team,
    ]
    # Without a page, too (e.g. a page of no workspace)
    without = client_for(owner).get("/api/v1.0/groups/?every_workspace=true").json()
    assert {r["team"] for r in without} == {r["team"] for r in results}
