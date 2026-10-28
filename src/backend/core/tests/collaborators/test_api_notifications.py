"""
Tests for Collaborators notifications: mentions of people and groups in
pages, comments and table cells, assignments, and the inbox API.
"""

from uuid import uuid4

from django.core import mail

import pytest
from rest_framework.test import APIClient

from core import factories, models
from core.choices import WorkspaceRoleChoices

pytestmark = pytest.mark.django_db


def client_for(user):
    """An API client logged in as the user."""
    client = APIClient()
    client.force_login(user)
    return client


def make_group(owner, members, name="Q4 Launch"):
    """A workspace owned by `owner` with a group of `members`."""
    workspace = models.Workspace.objects.create(name="Acme")
    models.WorkspaceAccess.objects.create(
        workspace=workspace, user=owner, role=WorkspaceRoleChoices.OWNER
    )
    group = models.Group.objects.create(workspace=workspace, name=name)
    for member in members:
        if member != owner:
            models.WorkspaceAccess.objects.create(workspace=workspace, user=member)
        models.GroupMembership.objects.create(group=group, user=member)
    return group


def test_api_mention_user_lands_in_their_inbox():
    """A mention creates an unread notification pointing at the block."""
    author, reader = factories.UserFactory.create_batch(2)
    document = factories.DocumentFactory(
        users=[(author, "editor"), (reader, "reader")], title="Plan"
    )
    anchor = str(uuid4())

    response = client_for(author).post(
        f"/api/v1.0/documents/{document.id}/mention/",
        {"anchor_id": anchor, "mentioned_user_id": str(reader.id)},
    )

    assert response.status_code == 201
    inbox = client_for(reader).get("/api/v1.0/notifications/").json()
    assert [(n["kind"], n["anchor_id"], n["document"]["title"]) for n in inbox] == [
        ("mention", anchor, "Plan")
    ]
    assert inbox[0]["actor"]["id"] == str(author.id)
    count = client_for(reader).get("/api/v1.0/notifications/unread-count/").json()
    assert count == {"count": 1}


def test_api_mention_group_reaches_members_with_access():
    """A group mention notifies each member who can see the page, once."""
    author, member, other = factories.UserFactory.create_batch(3)
    group = make_group(author, [author, member, other])
    document = factories.DocumentFactory(
        users=[(author, "editor")], link_reach="restricted"
    )
    models.DocumentAccess.objects.create(document=document, user=member, role="reader")

    response = client_for(author).post(
        f"/api/v1.0/documents/{document.id}/mention/",
        {"anchor_id": str(uuid4()), "mentioned_team": group.team},
    )

    assert response.status_code == 201
    assert [m["mentioned_user_id"] for m in response.json()] == [str(member.id)]
    notification = models.Notification.objects.get()
    assert (notification.recipient, notification.team) == (member, group.team)
    assert len(mail.outbox) == 1
    # Docs capitalizes email subjects, lowercasing the rest
    assert "q4 launch" in mail.outbox[0].subject


def test_api_mention_in_a_table_cell_and_assignment():
    """Table cells are valid anchors, and assignments have their own kind."""
    author, assignee = factories.UserFactory.create_batch(2)
    document = factories.DocumentFactory(
        users=[(author, "editor"), (assignee, "editor")]
    )
    cell = f"cell:{uuid4()}:{uuid4()}:{uuid4()}"

    response = client_for(author).post(
        f"/api/v1.0/documents/{document.id}/mention/",
        {
            "anchor_id": cell,
            "mentioned_user_id": str(assignee.id),
            "reason": "assignment",
        },
    )

    assert response.status_code == 201
    notification = models.Notification.objects.get()
    assert (notification.kind, notification.anchor_id) == ("assignment", cell)
    assert "assigned you" in mail.outbox[0].subject


def test_api_mention_needs_exactly_one_target():
    """Mention a person or a group, not both, not neither."""
    author = factories.UserFactory()
    document = factories.DocumentFactory(users=[(author, "editor")])

    response = client_for(author).post(
        f"/api/v1.0/documents/{document.id}/mention/", {"anchor_id": str(uuid4())}
    )

    assert response.status_code == 400


def test_api_comment_mentions_notify_once():
    """Mentions written in a comment notify, and editing it doesn't repeat them."""
    author, mentioned = factories.UserFactory.create_batch(2)
    document = factories.DocumentFactory(
        users=[(author, "editor"), (mentioned, "commenter")]
    )
    mention = {
        "type": "mention",
        "props": {"kind": "user", "targetId": str(mentioned.id), "label": "M"},
    }
    body = [{"type": "paragraph", "content": [mention]}]

    response = client_for(author).post(
        f"/api/v1.0/documents/{document.id}/threads/", {"body": body}, format="json"
    )
    assert response.status_code == 201
    thread_id = response.json()["id"]
    notification = models.Notification.objects.get()
    assert notification.kind == "comment_mention"
    assert str(notification.thread_id) == thread_id

    comment = models.Comment.objects.get()
    edited = [
        {
            "type": "paragraph",
            "content": [mention, {"type": "text", "text": " thanks", "styles": {}}],
        }
    ]
    response = client_for(author).patch(
        f"/api/v1.0/documents/{document.id}/threads/{thread_id}/comments/{comment.id}/",
        {"body": edited},
        format="json",
    )
    assert response.status_code == 200
    assert models.Notification.objects.count() == 1


def test_api_notifications_read_and_preferences():
    """Notifications can be read one by one or all at once; email can be turned off."""
    author, reader = factories.UserFactory.create_batch(2)
    document = factories.DocumentFactory(users=[(author, "editor"), (reader, "reader")])
    url = f"/api/v1.0/documents/{document.id}/mention/"
    for _ in range(2):
        client_for(author).post(
            url, {"anchor_id": str(uuid4()), "mentioned_user_id": str(reader.id)}
        )
    client = client_for(reader)
    first = client.get("/api/v1.0/notifications/").json()[0]

    assert (
        client.post(f"/api/v1.0/notifications/{first['id']}/read/").status_code == 200
    )
    assert client.get("/api/v1.0/notifications/unread-count/").json() == {"count": 1}
    assert client.post("/api/v1.0/notifications/read-all/").status_code == 204
    assert client.get("/api/v1.0/notifications/?unread=true").json() == []

    assert client.patch(
        "/api/v1.0/notifications/preferences/", {"email": False}, format="json"
    ).json() == {"email": False}
    mail.outbox.clear()
    client_for(author).post(
        url, {"anchor_id": str(uuid4()), "mentioned_user_id": str(reader.id)}
    )
    assert models.Notification.objects.filter(recipient=reader).count() == 3
    assert not mail.outbox


def test_api_notifications_are_private():
    """Nobody reads or marks someone else's notifications."""
    author, reader, stranger = factories.UserFactory.create_batch(3)
    document = factories.DocumentFactory(users=[(author, "editor"), (reader, "reader")])
    client_for(author).post(
        f"/api/v1.0/documents/{document.id}/mention/",
        {"anchor_id": str(uuid4()), "mentioned_user_id": str(reader.id)},
    )
    notification = models.Notification.objects.get()

    assert client_for(stranger).get("/api/v1.0/notifications/").json() == []
    response = client_for(stranger).post(
        f"/api/v1.0/notifications/{notification.id}/read/"
    )
    assert response.status_code == 404


def test_api_mention_in_the_first_block():
    """BlockNote's first block has the fixed id "initialBlockId"."""
    author, reader = factories.UserFactory.create_batch(2)
    document = factories.DocumentFactory(users=[(author, "editor"), (reader, "reader")])

    response = client_for(author).post(
        f"/api/v1.0/documents/{document.id}/mention/",
        {"anchor_id": "initialBlockId", "mentioned_user_id": str(reader.id)},
    )

    assert response.status_code == 201


def test_new_accounts_get_no_notification_emails_until_they_ask():
    """Off by default: the in-app inbox only."""
    assert models.User().collaborator_email_notifications is False


def test_api_notifications_unread_and_read_apart():
    """The Notifications screen's two tabs: unread ones, and read ones."""
    author, reader = factories.UserFactory.create_batch(2)
    document = factories.DocumentFactory(users=[(author, "editor"), (reader, "reader")])
    url = f"/api/v1.0/documents/{document.id}/mention/"
    for _ in range(2):
        client_for(author).post(
            url, {"anchor_id": str(uuid4()), "mentioned_user_id": str(reader.id)}
        )
    client = client_for(reader)
    first, second = client.get("/api/v1.0/notifications/").json()
    client.post(f"/api/v1.0/notifications/{first['id']}/read/")

    unread = client.get("/api/v1.0/notifications/?unread=true").json()
    read = client.get("/api/v1.0/notifications/?read=true").json()

    assert [item["id"] for item in unread] == [second["id"]]
    assert [item["id"] for item in read] == [first["id"]]


def test_api_mention_overlapping_groups_in_a_block_notify_once():
    """
    "@Product @Engineering" in one block: someone in both groups gets one
    inbox entry, which shows the first group; each group keeps its mention.
    """
    author, both, only_second = factories.UserFactory.create_batch(3)
    product = make_group(author, [both], name="Product")
    engineering = make_group(author, [both, only_second], name="Engineering")
    document = factories.DocumentFactory(
        users=[(author, "editor"), (both, "reader"), (only_second, "reader")]
    )
    anchor = str(uuid4())
    url = f"/api/v1.0/documents/{document.id}/mention/"

    for group in (product, engineering):
        response = client_for(author).post(
            url, {"anchor_id": anchor, "mentioned_team": group.team}
        )
        assert response.status_code == 201

    assert sorted(
        models.Notification.objects.values_list("recipient_id", "team")
    ) == sorted([(both.id, product.team), (only_second.id, engineering.team)])
    assert models.Mention.objects.filter(mentioned_user=both).count() == 2


def test_api_mention_group_and_person_in_a_block_notify_once():
    """Named directly and through a group in one block: one entry, as a person."""
    author, member = factories.UserFactory.create_batch(2)
    group = make_group(author, [member])
    document = factories.DocumentFactory(users=[(author, "editor"), (member, "reader")])
    url = f"/api/v1.0/documents/{document.id}/mention/"
    group_first, person_first = str(uuid4()), str(uuid4())

    client = client_for(author)
    client.post(url, {"anchor_id": group_first, "mentioned_team": group.team})
    client.post(url, {"anchor_id": group_first, "mentioned_user_id": str(member.id)})
    client.post(url, {"anchor_id": person_first, "mentioned_user_id": str(member.id)})
    client.post(url, {"anchor_id": person_first, "mentioned_team": group.team})

    assert sorted(
        models.Notification.objects.filter(recipient=member).values_list(
            "anchor_id", "team"
        )
    ) == sorted([(group_first, ""), (person_first, "")])


def test_api_comment_mentions_of_groups_and_person_notify_once():
    """A comment naming two groups and a member of both: one inbox entry."""
    author, member = factories.UserFactory.create_batch(2)
    product = make_group(author, [member], name="Product")
    engineering = make_group(author, [member], name="Engineering")
    document = factories.DocumentFactory(
        users=[(author, "editor"), (member, "commenter")]
    )

    def mention(kind, target):
        return {"type": "mention", "props": {"kind": kind, "targetId": target}}

    body = [
        {
            "type": "paragraph",
            "content": [
                mention("group", product.team),
                mention("group", engineering.team),
                mention("user", str(member.id)),
            ],
        }
    ]
    url = f"/api/v1.0/documents/{document.id}/threads/"

    response = client_for(author).post(url, {"body": body}, format="json")

    assert response.status_code == 201
    notification = models.Notification.objects.get()
    assert (notification.recipient, notification.kind, notification.team) == (
        member,
        "comment_mention",
        "",
    )
    assert models.Mention.objects.filter(mentioned_user=member).count() == 3

    # A reply mentioning them again is another action: another entry
    thread_id = response.json()["id"]
    response = client_for(author).post(
        f"{url}{thread_id}/comments/", {"body": body}, format="json"
    )
    assert response.status_code == 201
    assert models.Notification.objects.count() == 2
