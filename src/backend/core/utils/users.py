"""User sharing cache utilities."""

import logging
import time

from django.core.cache import cache
from django.db import models as db
from django.db.models import Subquery

from core import models

logger = logging.getLogger(__name__)


def forget_all_people():
    """
    Collaborators: who shares something with whom is computed again, for
    everyone (a role on a space reaches the people of all its pages, a
    group's members, a workspace's members).
    """
    cache.delete_many(
        [
            get_users_sharing_documents_with_cache_key(user_id)
            for user_id in models.User.objects.values_list("id", flat=True)
        ]
    )


def get_users_sharing_documents_with_cache_key(user_id):
    """Generate a unique cache key for each user."""
    return f"users_sharing_documents_with_{user_id}"


def _members_of_teams(teams):
    """
    The users each team string stands for, as {team: [user ids]}: one query
    per kind of team (groups, whole workspaces, workspace administrators),
    however many teams there are.
    """
    by_kind = {}
    for team in teams:
        kind, obj_id = models.parse_team(team)
        if kind is not None:
            by_kind.setdefault(kind, {})[obj_id] = team
    members = {team: [] for team in teams}
    groups = by_kind.get(models.TEAM_GROUP, {})
    if groups:
        for group_id, user_id in models.GroupMembership.objects.filter(
            group_id__in=list(groups)
        ).values_list("group_id", "user_id"):
            members[groups[group_id]].append(user_id)
    for kind, roles in (
        (models.TEAM_WORKSPACE, None),
        (models.TEAM_WORKSPACE_ADMINS, models.WORKSPACE_PRIVILEGED_ROLES),
    ):
        workspaces = by_kind.get(kind, {})
        if not workspaces:
            continue
        accesses = models.WorkspaceAccess.objects.filter(
            workspace_id__in=list(workspaces)
        )
        if roles is not None:
            accesses = accesses.filter(role__in=roles)
        for workspace_id, user_id in accesses.values_list("workspace_id", "user_id"):
            members[workspaces[workspace_id]].append(user_id)
    return members


def _related_paths_query(paths, steplen, field="document__path"):
    """Documents above, at or under any of these paths."""
    # under a path also under another one: covered by the higher one
    kept = sorted(set(paths), key=len)
    tops = []
    for path in kept:
        if not any(path.startswith(top) for top in tops):
            tops.append(path)
    above = {path[:end] for path in kept for end in range(steplen, len(path), steplen)}
    query = db.Q(**{f"{field}__in": above})
    for top in tops:
        query |= db.Q(**{f"{field}__startswith": top})
    return query


def users_sharing_documents_with(user_id):
    """
    Returns a map of users sharing documents with the given user,
    sorted by last shared date.

    Collaborators: "sharing" is having a role in the same tree, the one
    above or under the other (a space and its pages), directly or through a
    group or a workspace, or being members of the same workspace. A page
    linked into a space counts as in that space too (its people may read
    it). Pages in the trashbin don't count: the others lost them.
    """
    start_time = time.time()
    cache_key = get_users_sharing_documents_with_cache_key(user_id)
    cached_result = cache.get(cache_key)

    if cached_result is not None:
        elapsed = time.time() - start_time
        logger.info(
            "users_sharing_documents_with cache hit for user %s (took %.3fs)",
            user_id,
            elapsed,
        )
        return cached_result

    result = {}

    def note(other_id, when):
        if other_id and other_id != user_id:
            previous = result.get(other_id)
            if previous is None or when > previous:
                result[other_id] = when

    teams = (
        models.User.objects.filter(pk=user_id)
        .values_list("collaborator_teams", flat=True)
        .first()
    ) or []
    mine = db.Q(user_id=user_id) | db.Q(team__in=teams)
    steplen = models.Document.steplen
    my_paths = set(
        models.DocumentAccess.objects.filter(
            mine, document__ancestors_deleted_at__isnull=True
        ).values_list("document__path", flat=True)
    )
    # the pages linked into the spaces I have a role on: I may read them
    my_paths.update(
        models.PageSpaceLink.objects.filter(
            db.Q(space__accesses__user_id=user_id)
            | db.Q(space__accesses__team__in=teams),
            space__ancestors_deleted_at__isnull=True,
            page__ancestors_deleted_at__isnull=True,
        ).values_list("page__path", flat=True)
    )
    if my_paths:
        alive = db.Q(document__ancestors_deleted_at__isnull=True)
        # a role in the same tree: on my pages, above or under them
        shared = list(
            models.DocumentAccess.objects.filter(
                _related_paths_query(my_paths, steplen), alive
            )
            .values("user", "team")
            .annotate(last_shared=db.Max("created_at"))
        )
        # a role on a space into which a page of that tree is linked
        shared += list(
            models.DocumentAccess.objects.filter(
                document__in=models.PageSpaceLink.objects.filter(
                    _related_paths_query(my_paths, steplen, "page__path"),
                    page__ancestors_deleted_at__isnull=True,
                ).values("space_id"),
            )
            .filter(alive)
            .values("user", "team")
            .annotate(last_shared=db.Max("created_at"))
        )
        # a group or a workspace: each of its members
        members = _members_of_teams({item["team"] for item in shared if item["team"]})
        for item in shared:
            if item["user"]:
                note(item["user"], item["last_shared"])
            for member_id in members.get(item["team"], ()):
                note(member_id, item["last_shared"])

    # Collaborators: the members of my workspaces count as close too, so that
    # they can be found by name to share with or to mention
    my_workspaces_qs = models.WorkspaceAccess.objects.filter(
        user__id=user_id
    ).values_list("workspace_id", flat=True)
    co_members_qs = (
        models.WorkspaceAccess.objects.filter(
            workspace_id__in=Subquery(my_workspaces_qs)
        )
        .exclude(user__id=user_id)
        .values("user")
        .annotate(last_shared=db.Max("created_at"))
    )
    for item in co_members_qs:
        note(item["user"], item["last_shared"])

    cache.set(cache_key, result, 86400)  # Cache for 1 day
    elapsed = time.time() - start_time
    logger.info(
        "users_sharing_documents_with cache miss for user %s (took %.3fs)",
        user_id,
        elapsed,
    )
    return result


def findable_user_ids():
    """Those who let everyone on the platform find them (or the internet)."""
    return models.UserProfile.objects.filter(
        reach__in=[models.ProfileAudience.PLATFORM, models.ProfileAudience.PUBLIC],
        user__is_active=True,
    ).values_list("user_id", flat=True)


def can_find(viewer_id, other_id):
    """
    Collaborators: whether one may find, see and invite another: they share
    a workspace, a space or a page, or the other lets everyone find them.
    """
    if viewer_id == other_id:
        return True
    if other_id in users_sharing_documents_with(viewer_id):
        return True
    return models.UserProfile.objects.filter(
        user_id=other_id,
        reach__in=[models.ProfileAudience.PLATFORM, models.ProfileAudience.PUBLIC],
    ).exists()
