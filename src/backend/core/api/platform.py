"""
Collaborators: the platform as its managers, administrators and owners see
it (see core.platform_roles), and what they do to accounts (core.accounts).

    GET    /api/v1.0/platform/people/?q=&role=&status=&account=&page=
    POST   /api/v1.0/platform/people/<id>/suspend/      {reason}
    POST   /api/v1.0/platform/people/<id>/reinstate/
    GET    /api/v1.0/platform/people/<id>/removal/      what removing leaves
    POST   /api/v1.0/platform/people/<id>/remove/       {pages, recipient, reason, block}
    POST   /api/v1.0/platform/people/<id>/level/        {role}
    GET    /api/v1.0/platform/blocked/                  (owners)
    POST   /api/v1.0/platform/blocked/                  {email, reason} (owners)
    DELETE /api/v1.0/platform/blocked/<id>/             (owners)
    POST   /api/v1.0/documents/<id>/report/             {reason, details} (readers)
    GET    /api/v1.0/platform/reports/?status=open|decided   (administrators)
    POST   /api/v1.0/platform/reports/<id>/dismiss/     {note}
    POST   /api/v1.0/platform/reports/<id>/take-down/   {note}
    POST   /api/v1.0/platform/reports/<id>/put-back/
    GET    /api/v1.0/platform/settings/                 (owners)
    PATCH  /api/v1.0/platform/settings/                 {name: true|false|null}
    GET    /api/v1.0/platform/places/?q=                (owners)
    POST   /api/v1.0/platform/add-to-places/            {people, places, notify} (owners)
"""

from functools import partial

from django.db import transaction
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce

import rest_framework as drf
from rest_framework import serializers
from rest_framework.generics import ListAPIView
from rest_framework.views import APIView

from core import (
    accounts,
    models,
    placements,
    platform_roles,
    platform_settings,
    reports,
)
from core.api import permissions
from core.api.registrations import IsPlatformManager
from core.choices import PlatformRoleChoices, RegistrationStatusChoices, RoleChoices
from core.tasks.mail import send_added_to_places_mail


class PeoplePagination(drf.pagination.PageNumberPagination):
    """Fifty people a page."""

    page_size = 50


class PlatformPersonSerializer(serializers.ModelSerializer):
    """Someone on the platform, with their level and what they take part in."""

    email_verified = serializers.BooleanField(source="collaborator_email_verified")
    platform_role = serializers.CharField(source="platform_level")
    workspaces = serializers.IntegerField(source="nb_workspaces")
    pages = serializers.IntegerField(source="nb_pages")
    suspended = serializers.SerializerMethodField()
    # The requester may suspend or remove them
    can_manage = serializers.SerializerMethodField()
    # The levels the requester may put them at
    levels_you_may_give = serializers.SerializerMethodField()

    def get_suspended(self, person):
        """Suspended until reinstated."""
        return person.suspended_at is not None

    def get_can_manage(self, person):
        """Below the requester's level, and not the requester."""
        return accounts.can_manage(self.context["request"].user, person)

    def get_levels_you_may_give(self, person):
        """Up to manager for an administrator, any for an owner."""
        return accounts.levels_one_may_give(self.context["request"].user, person)

    class Meta:
        model = models.User
        fields = [
            "id",
            "full_name",
            "email",
            "email_verified",
            "platform_role",
            "registration_status",
            "created_at",
            "last_login",
            "workspaces",
            "pages",
            "suspended",
            "can_manage",
            "levels_you_may_give",
        ]
        read_only_fields = fields


def _count(queryset):
    """A count per person, as a subquery: no join multiplies the others."""
    return Coalesce(
        Subquery(
            queryset.values("user")
            .annotate(total=Count("pk", distinct=True))
            .values("total"),
            output_field=IntegerField(),
        ),
        0,
    )


class PlatformPeopleView(ListAPIView):
    """
    Everyone with an account, newest first, for platform managers and above:
    found by name or email, at one level, with one registration status, or
    active or suspended.
    """

    permission_classes = [IsPlatformManager]
    serializer_class = PlatformPersonSerializer
    pagination_class = PeoplePagination

    def get_queryset(self):
        params = self.request.query_params
        # The suspended ones too (other inactive accounts are merged ones)
        people = models.User.objects.filter(
            Q(is_active=True) | Q(suspended_at__isnull=False), is_device=False
        )
        query = (params.get("q") or "").strip()
        if query:
            people = people.filter(
                Q(full_name__unaccent__icontains=query) | Q(email__icontains=query)
            )
        role = params.get("role")
        if role:
            if role not in PlatformRoleChoices.values:
                raise drf.exceptions.ValidationError({"role": "unknown level"})
            if role == platform_roles.OWNER:
                people = people.filter(Q(platform_role=role) | Q(is_superuser=True))
            else:
                people = people.filter(platform_role=role, is_superuser=False)
        status = params.get("status")
        if status:
            if status not in RegistrationStatusChoices.values:
                raise drf.exceptions.ValidationError({"status": "unknown status"})
            people = people.filter(registration_status=status)
        account = params.get("account")
        if account == "active":
            people = people.filter(suspended_at__isnull=True)
        elif account == "suspended":
            people = people.filter(suspended_at__isnull=False)
        elif account:
            raise drf.exceptions.ValidationError({"account": "active or suspended"})
        return people.annotate(
            nb_workspaces=_count(
                models.WorkspaceAccess.objects.filter(user=OuterRef("pk"))
            ),
            nb_pages=_count(
                models.DocumentAccess.objects.filter(
                    user=OuterRef("pk"),
                    role=RoleChoices.OWNER,
                    document__deleted_at__isnull=True,
                    document__ancestors_deleted_at__isnull=True,
                )
            ),
        ).order_by("-created_at")


class IsPlatformAdministrator(permissions.IsAuthenticated):
    """Platform administrators and owners."""

    def has_permission(self, request, view):
        return super().has_permission(request, view) and platform_roles.has_level(
            request.user, platform_roles.ADMINISTRATOR
        )


class IsPlatformOwner(permissions.IsAuthenticated):
    """Platform owners."""

    def has_permission(self, request, view):
        return super().has_permission(request, view) and platform_roles.has_level(
            request.user, platform_roles.OWNER
        )


def _reason(request):
    return str(request.data.get("reason") or "").strip()[:500]


class AccountActionView(APIView):
    """Suspend, reinstate, remove or appoint someone below one's level."""

    permission_classes = [IsPlatformAdministrator]
    action = None

    def _target(self, request, user_id):
        target = (
            models.User.objects.filter(id=user_id, is_device=False)
            .filter(Q(is_active=True) | Q(suspended_at__isnull=False))
            .first()
        )
        if target is None:
            raise drf.exceptions.NotFound()
        # Owners give levels to other owners too (core.accounts)
        if self.action == "level":
            if not accounts.levels_one_may_give(request.user, target):
                raise drf.exceptions.PermissionDenied(
                    "You can't change this person's level."
                )
        elif not accounts.can_manage(request.user, target):
            raise drf.exceptions.PermissionDenied(
                "Only people below your own level, never yourself."
            )
        return target

    def get(self, request, user_id):
        """What removing them would leave without an owner."""
        if self.action != "remove":
            raise drf.exceptions.MethodNotAllowed("GET")
        return drf.response.Response(
            accounts.removal_preview(self._target(request, user_id))
        )

    def post(self, request, user_id):
        """Do it, and say what became of the sign-in server's account."""
        target = self._target(request, user_id)
        try:
            if self.action == "suspend":
                server = accounts.suspend(target, request.user, _reason(request))
            elif self.action == "reinstate":
                server = accounts.reinstate(target, request.user)
            elif self.action == "level":
                accounts.appoint(target, request.user, request.data.get("role"))
                return drf.response.Response({"platform_role": target.platform_level})
            else:
                recipient = None
                recipient_id = request.data.get("recipient")
                if recipient_id:
                    recipient = models.User.objects.filter(
                        id=recipient_id, is_active=True
                    ).first()
                    if recipient is None:
                        raise accounts.AccountError("This person can't receive pages.")
                server = accounts.remove(
                    target,
                    request.user,
                    pages=request.data.get("pages") or accounts.HAND_OVER,
                    recipient=recipient,
                    reason=_reason(request),
                    block=bool(request.data.get("block")),
                )
        except accounts.AccountError as err:
            raise drf.exceptions.ValidationError({"detail": str(err)}) from err
        return drf.response.Response({"sign_in_server": server})


def _blocked(blocked):
    return {
        "id": str(blocked.id),
        "email": blocked.email,
        "reason": blocked.reason,
        "blocked_by": platform_roles.display_name(blocked.blocked_by),
        "created_at": blocked.created_at,
        # Someone with an account here
        "has_account": models.User.objects.filter(email__iexact=blocked.email).exists(),
    }


class BlockedEmailListView(APIView):
    """The blocked emails, newest first; block one more."""

    permission_classes = [IsPlatformOwner]

    def get(self, request):
        """List them."""
        return drf.response.Response(
            [_blocked(blocked) for blocked in models.BlockedEmail.objects.all()]
        )

    def post(self, request):
        """Block an email, with or without an account here."""
        try:
            accounts.block_email(
                request.data.get("email"), request.user, _reason(request)
            )
        except accounts.AccountError as err:
            raise drf.exceptions.ValidationError({"detail": str(err)}) from err
        blocked = models.BlockedEmail.objects.get(
            email=accounts.normalize(request.data.get("email"))
        )
        return drf.response.Response(_blocked(blocked), status=201)


class BlockedEmailView(APIView):
    """Unblock an email."""

    permission_classes = [IsPlatformOwner]

    def delete(self, request, blocked_id):
        """It may sign in again."""
        blocked = models.BlockedEmail.objects.filter(id=blocked_id).first()
        if blocked is None:
            raise drf.exceptions.NotFound()
        accounts.unblock_email(blocked, request.user)
        return drf.response.Response(status=204)


class ReportPageView(APIView):
    """Report a page one reads to the platform administrators."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        """Why, and in a few words what is wrong."""
        document = models.Document.objects.filter(pk=pk).first()
        if document is None or not document.get_abilities(request.user).get("retrieve"):
            raise drf.exceptions.NotFound()
        try:
            reports.report(
                document,
                request.user,
                request.data.get("reason"),
                str(request.data.get("details") or "").strip(),
            )
        except reports.ReportError as err:
            raise drf.exceptions.ValidationError({"detail": str(err)}) from err
        return drf.response.Response(status=201)


def _report(content_report):
    document = content_report.document
    return {
        "id": str(content_report.id),
        "document": {
            "id": str(document.id),
            "title": document.title or "",
            "deleted": bool(document.deleted_at or document.ancestors_deleted_at),
            "taken_down": document.taken_down_at is not None,
            "owners": [
                platform_roles.display_name(owner) for owner in reports.owners(document)
            ],
        }
        if document
        else None,
        "document_title": content_report.document_title,
        "excerpt": content_report.excerpt,
        "reporter": content_report.reporter_name,
        "reason": content_report.reason,
        "details": content_report.details,
        "status": content_report.status,
        "resolved_by": content_report.resolved_by_name,
        "resolved_at": content_report.resolved_at,
        "resolution_note": content_report.resolution_note,
        "created_at": content_report.created_at,
    }


class PlatformReportsView(APIView):
    """The reports to decide on (oldest first), or those decided (newest)."""

    permission_classes = [IsPlatformAdministrator]

    def get(self, request):
        """List them."""
        status = request.query_params.get("status") or "open"
        found = models.ContentReport.objects.select_related("document")
        if status == "open":
            found = found.filter(status="open").order_by("created_at")
        elif status == "decided":
            found = found.exclude(status="open").order_by("-resolved_at")[:200]
        else:
            raise drf.exceptions.ValidationError({"status": "open or decided"})
        return drf.response.Response([_report(item) for item in found])


class ReportDecisionView(APIView):
    """Dismiss a report, take its page down, or put the page back."""

    permission_classes = [IsPlatformAdministrator]
    decision = None

    def post(self, request, report_id):
        """Decide; the people concerned are told by email."""
        content_report = (
            models.ContentReport.objects.select_related("document")
            .filter(id=report_id)
            .first()
        )
        if content_report is None:
            raise drf.exceptions.NotFound()
        note = str(request.data.get("note") or "").strip()[:500]
        try:
            if self.decision == "dismiss":
                reports.dismiss(content_report, request.user, note)
            elif self.decision == "take_down":
                reports.take_down(content_report, request.user, note)
            else:
                reports.put_back(content_report, request.user)
        except reports.ReportError as err:
            raise drf.exceptions.ValidationError({"detail": str(err)}) from err
        content_report.refresh_from_db()
        return drf.response.Response(_report(content_report))


class PlatformSettingsView(APIView):
    """The settings platform owners change in the app."""

    permission_classes = [IsPlatformOwner]

    def get(self, request):
        """Each setting, with the server's own."""
        return drf.response.Response(platform_settings.describe())

    def patch(self, request):
        """Change some; null follows the server again."""
        try:
            platform_settings.update(dict(request.data), request.user)
        except ValueError as err:
            raise drf.exceptions.ValidationError({"detail": str(err)}) from err
        return drf.response.Response(platform_settings.describe())


class PlacesView(APIView):
    """
    Workspaces, spaces and pages of the whole platform, found by name, for
    platform owners to add people to (core.placements).
    """

    permission_classes = [IsPlatformOwner]

    def get(self, request):
        """Up to twenty of each kind, newest first."""
        return drf.response.Response(
            placements.find_places(request.query_params.get("q"))
        )


class AddToPlacesView(APIView):
    """
    Platform owners add people to places, apart from invitations: each one
    gets the role chosen there (never lowered), and an email unless `notify`
    is false.
    """

    permission_classes = [IsPlatformOwner]

    def post(self, request):
        """What it did, for each person and place."""
        people = request.data.get("people")
        places = request.data.get("places")
        if not isinstance(people, list) or not isinstance(places, list):
            raise drf.exceptions.ValidationError(
                {"detail": "people and places are lists"}
            )
        notify = request.data.get("notify", True) is not False
        try:
            outcomes = placements.add_to_places(request.user, people, places, notify)
        except placements.PlacementError as err:
            raise drf.exceptions.ValidationError({"detail": str(err)}) from err
        for outcome in outcomes:
            changed = placements.to_tell(outcome)
            if notify and changed:
                transaction.on_commit(
                    partial(
                        send_added_to_places_mail.delay,
                        outcome["id"],
                        str(request.user.id),
                        changed,
                    )
                )
        return drf.response.Response(outcomes)
