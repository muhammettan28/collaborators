"""
Mentions and assignments, and the notifications they send.

A mention or an assignment targets a collaborator or a group (a team string,
see `core.models.make_team`). A group is expanded to its members who can see
the document: each gets their own Mention, so the email cooldown works per
person, and their own Notification in the in-app inbox.

One action leaves one inbox entry per person, however many groups reached
them: a comment, or the mentions written in a block within the cooldown (each
is its own request). The entry shows the first group, and naming the person
directly wins over a group.
"""

import uuid
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from core import choices, models
from core.tasks.mail import send_mention_notification_mail


def team_members(team):
    """The users a team string stands for."""
    kind, obj_id = models.parse_team(team)
    if kind == models.TEAM_GROUP:
        return models.User.objects.filter(group_memberships__group_id=obj_id)
    if kind == models.TEAM_WORKSPACE:
        return models.User.objects.filter(workspace_accesses__workspace_id=obj_id)
    if kind == models.TEAM_WORKSPACE_ADMINS:
        return models.User.objects.filter(
            workspace_accesses__workspace_id=obj_id,
            workspace_accesses__role__in=choices.WORKSPACE_PRIVILEGED_ROLES,
        )
    return models.User.objects.none()


def can_be_notified(document, user, in_thread):
    """
    Comments need a commenting role to be seen; the page and its tables only
    need to be readable.
    """
    # A fresh instance: a document from a request carries the roles of the
    # requesting user (`user_roles`), which `get_role` would return for anyone
    role = models.Document.objects.get(pk=document.pk).get_role(user)
    if in_thread:
        return role in choices.COMMENTING_ROLES
    return role is not None


def _inbox_entry(mention, kind, inbox):
    """
    The entry this mention's action already put in the recipient's inbox:
    from `inbox` (the entries of the action, by recipient) when given,
    else one left at the same place by the same person within the cooldown.
    """
    if inbox is not None:
        return inbox.get(mention.mentioned_user_id)
    cooldown_start = timezone.now() - timedelta(
        minutes=settings.MENTION_NOTIFICATION_COOLDOWN_MINUTES
    )
    return models.Notification.objects.filter(
        recipient_id=mention.mentioned_user_id,
        actor_id=mention.mentioned_by_user_id,
        kind=kind,
        document_id=mention.document_id,
        anchor_id=mention.anchor_id,
        thread_id=mention.thread_id,
        created_at__gt=cooldown_start,
    ).first()


def notify(mention, inbox=None):
    """
    Put a mention in its recipient's inbox, unless its action already did,
    and email them after commit (the email has its own cooldown).
    """
    if mention.mentioned_user_id is None or (
        mention.mentioned_user_id == mention.mentioned_by_user_id
    ):
        return
    if mention.reason == "assignment":
        kind = models.Notification.KIND_ASSIGNMENT
    elif mention.thread_id:
        kind = models.Notification.KIND_COMMENT_MENTION
    else:
        kind = models.Notification.KIND_MENTION
    entry = _inbox_entry(mention, kind, inbox)
    if entry is None:
        entry = models.Notification.objects.create(
            recipient_id=mention.mentioned_user_id,
            actor_id=mention.mentioned_by_user_id,
            kind=kind,
            document_id=mention.document_id,
            anchor_id=mention.anchor_id,
            thread_id=mention.thread_id,
            team=mention.mentioned_team,
        )
    elif entry.team and not mention.mentioned_team:
        entry.team = ""
        entry.save(update_fields=["team", "updated_at"])
    if inbox is not None:
        inbox[mention.mentioned_user_id] = entry
    send_mention_notification_mail.delay(str(mention.id))


def mention_team(document, actor, team, anchor_id, **options):
    """
    Mention every member of a group who can see the document. Options:
    `thread` (a mention in a comment), `reason` ("mention" or "assignment")
    and `inbox` (see `notify`).
    """
    thread = options.get("thread")
    reason = options.get("reason", "mention")
    mentions = []
    for member_id in team_members(team).distinct().values_list("pk", flat=True):
        # Fresh instance: the role check reads the member's own teams
        member = models.User.objects.get(pk=member_id)
        if member.pk == actor.pk or not can_be_notified(
            document, member, thread is not None
        ):
            continue
        mention = models.Mention.objects.create(
            document=document,
            anchor_id=anchor_id,
            thread=thread,
            mentioned_user=member,
            mentioned_by_user=actor,
            mentioned_team=team,
            reason=reason,
        )
        notify(mention, options.get("inbox"))
        mentions.append(mention)
    return mentions


# -- Mentions inside comment bodies


def _walk_inline(content):
    """Yield every inline node of a BlockNote content list."""
    if not isinstance(content, list):
        return
    for node in content:
        if isinstance(node, dict):
            yield node
            yield from _walk_inline(node.get("content"))


def mentions_in_body(body):
    """The (kind, id) of every mention of a BlockNote comment body."""
    found = []
    blocks = body if isinstance(body, list) else [body]
    stack = list(blocks)
    while stack:
        block = stack.pop()
        if not isinstance(block, dict):
            continue
        for node in _walk_inline(block.get("content")):
            if node.get("type") == "mention":
                props = node.get("props") or {}
                target = (props.get("kind"), props.get("targetId"))
                if target[1] and target not in found:
                    found.append(target)
        stack.extend(block.get("children") or [])
    return found


def notify_comment_mentions(comment, actor, previous_body=None):
    """Notify the people and groups newly mentioned in a comment."""
    if actor is None:
        return
    thread = comment.thread
    document = thread.document
    already = set(mentions_in_body(previous_body)) if previous_body else set()
    anchor_id = str(thread.id)
    # A comment is one action: one inbox entry per person
    inbox = {}
    for kind, target in mentions_in_body(comment.body):
        if (kind, target) in already:
            continue
        if kind == "group":
            mention_team(document, actor, target, anchor_id, thread=thread, inbox=inbox)
            continue
        try:
            user = models.User.objects.filter(pk=uuid.UUID(str(target))).first()
        except ValueError:
            continue
        if user is None or not can_be_notified(document, user, True):
            continue
        mention = models.Mention.objects.create(
            document=document,
            anchor_id=anchor_id,
            thread=thread,
            mentioned_user=user,
            mentioned_by_user=actor,
        )
        notify(mention, inbox)
