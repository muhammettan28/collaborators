"""
The people a collaborator works with (themselves first), to mention or to
put in a table's Person cell straight away: no minimum length to type, since only people
already close to them are listed (people they share pages with, members of
their workspaces), never the whole platform.
"""

import rest_framework as drf
from rest_framework.views import APIView

from core import models
from core.api import permissions
from core.api.filters import remove_accents
from core.api.profiles import Viewer
from core.api.serializers import UserSerializer
from core.choices import WORKSPACE_PRIVILEGED_ROLES
from core.utils.users import findable_user_ids, users_sharing_documents_with

# Everyone one works with, as a scrolling list; a safety bound only
PEOPLE_LIMIT = 500


class KnownPeopleView(APIView):
    """GET /api/v1.0/people/?q=<any text> — closest first."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """The people the requester works with whose name or email match."""
        closeness = users_sharing_documents_with(request.user.id)
        query = remove_accents((request.query_params.get("q") or "").strip()).lower()
        people = [
            person
            for person in models.User.objects.filter(
                id__in=list(closeness), is_active=True
            )
            if not query
            or query in remove_accents(person.full_name or "").lower()
            or query in (person.email or "").lower()
        ]
        people.sort(key=lambda person: closeness[person.id], reverse=True)
        # Oneself first: to mention oneself, or take a row in a Person cell
        me = request.user
        if (
            not query
            or query in remove_accents(me.full_name or "").lower()
            or query in (me.email or "").lower()
        ):
            people.insert(0, me)
        return drf.response.Response(
            UserSerializer(people[:PEOPLE_LIMIT], many=True).data
        )


class PersonCardView(APIView):
    """
    GET /api/v1.0/people/<id>/ — the card shown when hovering a mention.

    For someone the requester works with: their name, email, the workspaces
    they share and their groups there. For anyone else, only the name (which
    the mention shows anyway).
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, user_id):
        """A person's card, as much as the requester may see."""
        person = models.User.objects.filter(id=user_id, is_active=True).first()
        if person is None:
            raise drf.exceptions.NotFound()
        me = request.user
        card = {
            "id": str(person.id),
            "full_name": person.full_name or "",
            "short_name": person.short_name or "",
            "is_me": person.id == me.id,
            "known": False,
            "email": "",
            "workspaces": [],
            "groups": [],
        }
        known = person.id == me.id or person.id in users_sharing_documents_with(me.id)
        if not known:
            return drf.response.Response(card)
        shared = models.Workspace.objects.filter(accesses__user=me).filter(
            accesses__user=person
        )
        card.update(
            {
                "known": True,
                "email": person.email or "",
                "workspaces": [
                    {"id": str(workspace.id), "name": workspace.name}
                    for workspace in shared.distinct().order_by("name")
                ],
                "groups": [
                    {"id": str(group.id), "name": group.name}
                    for group in models.Group.objects.filter(
                        workspace__in=shared, memberships__user=person
                    )
                    .distinct()
                    .order_by("name")
                ],
            }
        )
        return drf.response.Response(card)


# Members listed on a group's card; the count gives the rest
TEAM_CARD_MEMBERS = 50


class TeamCardView(APIView):
    """
    GET /api/v1.0/teams/<team>/ — the card shown when hovering a mentioned
    group (team string "group:<id>", "workspace:<id>" for all the members of
    a workspace, or "workspace-admins:<id>").

    People of the group's workspace see who is in it (managers first); anyone
    else only the group's name, which the mention shows anyway.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, team):
        """A group's card, as much as the requester may see."""
        kind, obj_id = models.parse_team(team)
        group = workspace = None
        if kind == models.TEAM_GROUP:
            group = (
                models.Group.objects.filter(id=obj_id)
                .select_related("workspace")
                .first()
            )
            workspace = group.workspace if group else None
        elif kind is not None:
            workspace = models.Workspace.objects.filter(id=obj_id).first()
        if workspace is None:
            raise drf.exceptions.NotFound()

        me = request.user
        known = workspace.accesses.filter(user=me).exists()
        card = {
            "team": team,
            "kind": group.kind if group else kind,
            "name": group.name if group else "",
            "known": known,
            "workspace": None,
            "member_count": 0,
            "members": [],
        }
        if not known:
            return drf.response.Response(card)

        if group:
            memberships = group.memberships.filter(user__is_active=True)
            managers = set(
                memberships.filter(is_manager=True).values_list("user_id", flat=True)
            )
            people = models.User.objects.filter(id__in=memberships.values("user_id"))
        else:
            accesses = workspace.accesses.filter(user__is_active=True)
            if kind == models.TEAM_WORKSPACE_ADMINS:
                accesses = accesses.filter(role__in=WORKSPACE_PRIVILEGED_ROLES)
            managers = set(
                accesses.filter(role__in=WORKSPACE_PRIVILEGED_ROLES).values_list(
                    "user_id", flat=True
                )
            )
            people = models.User.objects.filter(id__in=accesses.values("user_id"))
            card["name"] = models.get_team_label(team)

        people = sorted(
            people.only("id", "full_name", "short_name", "email"),
            key=lambda person: (
                person.id not in managers,
                (person.full_name or person.email or "").lower(),
            ),
        )
        card.update(
            {
                "workspace": {"id": str(workspace.id), "name": workspace.name},
                "member_count": len(people),
                "members": [
                    {
                        "id": str(person.id),
                        "full_name": person.full_name or person.email or "",
                        "short_name": person.short_name or "",
                        "is_me": person.id == me.id,
                        "is_manager": person.id in managers,
                    }
                    for person in people[:TEAM_CARD_MEMBERS]
                ],
            }
        )
        return drf.response.Response(card)


class PeopleDirectoryView(APIView):
    """
    GET /api/v1.0/people/directory/?q=<text> — "My Collaborators": everyone
    the requester may see, the people they share a workspace, space or page
    with first (with the workspaces they share), then those who let everyone
    find them. Each shows what their profile lets the requester see.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """The people, closest first."""
        me = request.user
        closeness = users_sharing_documents_with(me.id)
        open_ids = set(findable_user_ids()) - set(closeness) - {me.id}
        query = remove_accents((request.query_params.get("q") or "").strip()).lower()
        people = [
            person
            for person in models.User.objects.filter(
                id__in=[*closeness, *open_ids], is_active=True
            )
            if not query
            or query in remove_accents(person.full_name or "").lower()
            or query in (person.email or "").lower()
        ]
        known = sorted(
            (person for person in people if person.id in closeness),
            key=lambda person: closeness[person.id],
            reverse=True,
        )
        others = sorted(
            (person for person in people if person.id not in closeness),
            key=lambda person: (person.full_name or person.email or "").lower(),
        )
        people = (known + others)[:PEOPLE_LIMIT]

        ids = [person.id for person in people]
        profiles = {
            profile.user_id: profile
            for profile in models.UserProfile.objects.filter(user_id__in=ids)
        }
        shared = {}
        for user_id, name in (
            models.WorkspaceAccess.objects.filter(
                user_id__in=ids,
                workspace__accesses__user=me,
            )
            .order_by("workspace__name")
            .values_list("user_id", "workspace__name")
        ):
            shared.setdefault(user_id, []).append(name)

        result = []
        for person in people:
            profile = profiles.get(person.id) or models.UserProfile(user=person)
            relation = Viewer(person, me)
            # known already: not looked up again for each person
            relation.is_colleague = person.id in closeness
            result.append(
                {
                    "id": str(person.id),
                    "full_name": person.full_name or "",
                    "email": person.email if relation.can_see(profile, "email") else "",
                    "headline": profile.headline
                    if relation.can_see(profile, "headline")
                    else "",
                    "organization": profile.organization
                    if relation.can_see(profile, "organization")
                    else "",
                    "is_colleague": person.id in closeness,
                    "workspaces": shared.get(person.id, []),
                }
            )
        return drf.response.Response(result)
