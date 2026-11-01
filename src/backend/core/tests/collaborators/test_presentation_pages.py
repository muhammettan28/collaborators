"""
Collaborators: one's AI assistant launches a page with a presentation at its
top (core.api.mcp's create_presentation_page): a page of one's own, straight
in a workspace, or in a space; shared by link and with people, as one may.
"""

from unittest import mock

import pytest

from core import factories, models
from core.services.yhub_services import YHubError
from core.tests.collaborators.test_assistants import (  # pylint: disable=unused-import
    fixture_mcp_settings,
)
from core.tests.collaborators.test_presentations import (  # pylint: disable=unused-import
    DECK,
    _call,
    fixture_pages,
    fixture_storage,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(name="new_page")
def fixture_new_page():
    """A new page's content, without the collaboration server."""
    with (
        mock.patch("core.presentations.YHubService.create_ydoc") as seed,
        mock.patch(
            "core.presentations.YdocConverter.append_blocks", return_value=b"upd"
        ) as build,
    ):
        yield build, seed


@pytest.mark.usefixtures("pages")
def test_an_assistant_launches_a_page_of_ones_own_with_the_presentation_on_top(
    new_page,
):
    """A page the person owns, the block alone in it, public as asked."""
    build, seed = new_page
    user = factories.UserFactory(email="ada@example.org")

    result = _call(
        user,
        "create_presentation_page",
        {"html": DECK, "share": "public", "pdf_base64": "JVBERi0xLjcKJSB0d2luCg=="},
    )

    assert not result.get("isError")
    presentation = models.Presentation.objects.get()
    page = presentation.document
    assert page.is_root()
    assert page.title == "Q4 & beyond"
    assert page.link_reach == "public"
    assert page.link_role == "reader"
    assert page.accesses.get().user == user
    assert page.get_abilities(user)["link_configuration"]
    assert models.PublicationLog.objects.get(document=page).actor == user
    assert build.call_args.args == (
        b"",
        [
            {
                "type": "presentation",
                "props": {
                    "presentationId": str(presentation.pk),
                    "title": "Q4 & beyond",
                },
            }
        ],
    )
    assert seed.call_args.args == (page, b"upd")
    shown = result["structuredContent"]
    assert shown["page"]["url"] == f"https://app.example.org/page/{page.pk}/"
    assert shown["presentation"]["pdf"]["state"] == "current"
    text = result["content"][0]["text"]
    assert text.startswith("Created the page “Q4 & beyond”")
    assert "anyone with its link (public)" in text


def test_an_assistant_launches_a_page_in_a_space_one_edits(new_page):
    """Under the space, as its people see it; its own title."""
    _build, seed = new_page
    user = factories.UserFactory(email="ada@example.org")
    space = factories.DocumentFactory(
        kind="space", title="Product", link_reach="restricted", users=[(user, "editor")]
    )

    result = _call(
        user,
        "create_presentation_page",
        {"place_id": str(space.pk), "html": DECK, "title": "Launch plan"},
    )

    assert not result.get("isError")
    page = models.Presentation.objects.get().document
    assert page.get_parent() == space
    assert page.title == "Launch plan"
    assert page.link_reach == "restricted"
    assert not page.accesses.exists()
    seed.assert_called_once()
    assert "the people of “Product”" in result["content"][0]["text"]


def test_an_assistant_launches_a_page_straight_in_a_workspace(new_page):
    """Found by name; its members read it, its administrators manage it."""
    _build, seed = new_page
    user = factories.UserFactory(email="ada@example.org")
    workspace = models.Workspace.objects.create(name="New WorkSpace")
    models.WorkspaceAccess.objects.create(workspace=workspace, user=user)
    models.Workspace.objects.create(name="Elsewhere")

    found = _call(user, "find_pages", {"query": "workspace"})
    assert found["structuredContent"]["pages"] == [
        {
            "id": str(workspace.pk),
            "title": "New WorkSpace",
            "kind": "workspace",
            "url": f"https://app.example.org/workspace/{workspace.pk}/",
        }
    ]

    result = _call(
        user,
        "create_presentation_page",
        {"place_id": str(workspace.pk), "html": DECK, "title": "New Page"},
    )

    assert not result.get("isError")
    page = models.Presentation.objects.get().document
    assert page.is_root()
    assert page.title == "New Page"
    assert page.workspace_links.get().workspace == workspace
    assert page.get_role(user) == "owner"
    member = factories.UserFactory()
    models.WorkspaceAccess.objects.create(workspace=workspace, user=member)
    member.refresh_from_db()
    assert page.get_abilities(member)["retrieve"]
    assert not page.get_abilities(member)["update"]
    seed.assert_called_once()
    assert "the members of “New WorkSpace”" in result["content"][0]["text"]

    # Not a member: not a place for one's pages
    outsider = factories.UserFactory(email="eve@example.org")
    refused = _call(
        outsider,
        "create_presentation_page",
        {"place_id": str(workspace.pk), "html": DECK},
    )
    assert refused["isError"]
    assert models.Presentation.objects.count() == 1


@pytest.mark.usefixtures("new_page")
def test_an_assistant_adds_people_to_the_page_it_launches(settings, mailoutbox):
    """Those one may find added and told; the others invited by email."""
    settings.COLLABORATORS_PEOPLE_PRIVACY = True
    user = factories.UserFactory(email="ada@example.org")
    workspace = models.Workspace.objects.create(name="New WorkSpace")
    models.WorkspaceAccess.objects.create(workspace=workspace, user=user)
    colleague = factories.UserFactory(email="user1@example.org")
    models.WorkspaceAccess.objects.create(workspace=workspace, user=colleague)
    stranger = factories.UserFactory(email="user2@example.org")

    result = _call(
        user,
        "create_presentation_page",
        {
            "place_id": str(workspace.pk),
            "title": "New Page",
            "html": DECK,
            "members": [
                {"email": "User1@example.org", "role": "editor"},
                {"email": "user2@example.org"},
                "user3@example.org",
                "ada@example.org",
            ],
        },
    )

    assert not result.get("isError")
    page = models.Document.objects.get(title="New Page")
    assert page.accesses.get(user=colleague).role == "editor"
    assert not page.accesses.filter(user=stranger).exists()
    assert set(page.invitations.values_list("email", "role")) == {
        ("user2@example.org", "reader"),
        ("user3@example.org", "reader"),
    }
    assert result["structuredContent"]["page"]["members"] == [
        {"email": "user1@example.org", "role": "editor", "status": "added"},
        {"email": "user2@example.org", "role": "reader", "status": "invited"},
        {"email": "user3@example.org", "role": "reader", "status": "invited"},
    ]
    text = result["content"][0]["text"]
    assert "- user1@example.org added as editor, and told by email" in text
    assert "- user3@example.org invited by email as reader, to accept" in text
    assert {mail.to[0] for mail in mailoutbox} >= {
        "user1@example.org",
        "user2@example.org",
        "user3@example.org",
    }

    # Invitations by email turned off: said, not done
    settings.COLLABORATORS_EMAIL_INVITATIONS = False
    later = _call(
        user,
        "create_presentation_page",
        {"html": DECK, "title": "Another", "members": ["user4@example.org"]},
    )
    assert later["structuredContent"]["page"]["members"][0]["status"] == "not_added"
    assert not models.Invitation.objects.filter(email="user4@example.org").exists()


@pytest.mark.usefixtures("new_page")
def test_a_page_is_launched_only_where_and_as_one_may():
    """Creating, sharing and publishing follow the person's rights there."""
    user = factories.UserFactory(email="ada@example.org")
    read_only = factories.DocumentFactory(
        kind="space", link_reach="restricted", users=[(user, "reader")]
    )
    edited = factories.DocumentFactory(
        kind="space", link_reach="restricted", users=[(user, "editor")]
    )
    administered = factories.DocumentFactory(
        kind="space", link_reach="restricted", users=[(user, "administrator")]
    )
    workspace = models.Workspace.objects.create(
        name="Acme", publishing_policy="workspace_admins"
    )
    models.WorkspaceAccess.objects.create(workspace=workspace, user=user)
    models.SpaceWorkspaceLink.objects.create(
        space=administered, workspace=workspace, is_home=True
    )
    count = models.Document.objects.count()

    for arguments in (
        {"place_id": str(read_only.pk)},
        {"place_id": "nope"},
        {"place_id": str(edited.pk), "share": "authenticated"},
        {"place_id": str(administered.pk), "share": "public"},
        {"share": "everyone"},
        {"place_id": str(edited.pk), "members": ["user1@example.org"]},
        {"members": ["not an address"]},
        {"members": [{"email": "user1@example.org", "role": "owner"}]},
        {},
    ):
        refused = _call(
            user,
            "create_presentation_page",
            {"html": DECK, **arguments} if arguments else {},
        )
        assert refused["isError"], arguments

    assert models.Document.objects.count() == count
    assert not models.Presentation.objects.exists()

    # Signed-in readers only: no publishing needed
    shared = _call(
        user,
        "create_presentation_page",
        {"place_id": str(administered.pk), "html": DECK, "share": "authenticated"},
    )
    assert not shared.get("isError")
    assert models.Presentation.objects.get().document.link_reach == "authenticated"


def test_a_page_that_cant_be_started_is_not_kept(new_page, storage):
    """The collaboration server down: no page, no presentation, no file."""
    _build, seed = new_page
    seed.side_effect = YHubError("down")
    user = factories.UserFactory(email="ada@example.org")
    count = models.Document.objects.count()

    result = _call(user, "create_presentation_page", {"html": DECK})

    assert result["isError"]
    assert models.Document.objects.count() == count
    assert not models.Presentation.objects.exists()
    assert not storage.files
