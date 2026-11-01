"""
Collaborators: invitations by email to workspaces, spaces and pages, for
people without an account (or whom the inviter can't find by name), and the
logos standing for those items.

The invitation's email links to /invite/?token=…, a page showing what one is
invited to (name and logo) with the ways to sign in or sign up; once signed
in, the page accepts the invitation (whatever email they signed up with).

GET  /api/v1.0/invitations/<token>/          — what it invites to (anyone)
GET  /api/v1.0/invitations/<token>/logo/     — the item's logo (anyone)
POST /api/v1.0/invitations/<token>/accept/   — join it (signed in)

GET, POST    /api/v1.0/workspaces/<id>/invitations/        — administrators
DELETE       /api/v1.0/workspaces/<id>/invitations/<id>/

GET, PUT, DELETE /api/v1.0/workspaces/<id>/logo/   — {"data": "data:image/…"}
GET, PUT, DELETE /api/v1.0/documents/<id>/logo/
"""

import base64
import binascii
import smtplib
from logging import getLogger

from django.conf import settings
from django.contrib.sites.models import Site
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import get_language, override
from django.utils.translation import gettext_lazy as _

import rest_framework as drf
from rest_framework.views import APIView

from core import choices, models, platform_settings, registrations
from core.api import permissions

logger = getLogger(__name__)

SALT = "collaborators-invitation"
WORKSPACE = "w"
DOCUMENT = "d"


def make_token(kind, invitation):
    """
    A signed token naming the invitation, for the link of its email.
    Collaborators: and what it is to, so the link still leads there once
    the invitation was used (a newcomer's account takes their invitations
    when it is made, before they come back to the link).
    """
    return signing.dumps(
        {
            "k": kind,
            "i": str(invitation.id),
            "t": str(item_of(kind, invitation).id),
        },
        salt=SALT,
    )


def invite_link(kind, invitation):
    """The page to accept the invitation."""
    domain = settings.EMAIL_URL_APP or Site.objects.get_current().domain
    return f"{domain}/invite/?token={make_token(kind, invitation)}"


def invite_logo_url(kind, invitation):
    """
    The logo of what the invitation is to, for its email; None without one.
    Shown while the invitation lasts, as on the page accepting it.
    """
    item = item_of(kind, invitation)
    if not models.ItemLogo.objects.filter(
        **{"workspace" if kind == WORKSPACE else "document": item}
    ).exists():
        return None
    domain = settings.EMAIL_URL_APP or Site.objects.get_current().domain
    return f"{domain}/api/v1.0/invitations/{make_token(kind, invitation)}/logo/"


def find_invitation(token):
    """(kind, invitation) for a token; 404 when unknown, used or tampered."""
    try:
        data = signing.loads(token, salt=SALT)
    except signing.BadSignature as error:
        raise drf.exceptions.NotFound() from error
    model = {
        WORKSPACE: models.WorkspaceInvitation,
        DOCUMENT: models.Invitation,
    }.get(data.get("k"))
    invitation = model and model.objects.filter(id=data.get("i")).first()
    if invitation is None:
        raise drf.exceptions.NotFound()
    return data["k"], invitation


def accepted_item(token, user):
    """
    Collaborators: what a used invitation was to, when the user may open it
    now (they accepted it, or their account took it when it was made).
    """
    if not user.is_authenticated:
        return None
    try:
        data = signing.loads(token, salt=SALT)
    except signing.BadSignature:
        return None
    item_id = data.get("t")
    if not item_id:
        return None
    try:
        if data.get("k") == WORKSPACE:
            return models.Workspace.objects.filter(
                id=item_id, accesses__user=user
            ).first()
        document = models.Document.objects.filter(
            id=item_id, ancestors_deleted_at__isnull=True
        ).first()
    except DjangoValidationError:
        return None
    return document if document and document.get_role(user) else None


def accepted_answer(item, **fields):
    """Collaborators: what a used invitation's link answers."""
    is_workspace = isinstance(item, models.Workspace)
    return drf.response.Response(
        {"kind": kind_label(WORKSPACE if is_workspace else DOCUMENT, item), **fields}
    )


def item_of(kind, invitation):
    """The workspace or document an invitation is to."""
    return invitation.workspace if kind == WORKSPACE else invitation.document


def kind_label(kind, item):
    """ "workspace", "space" or "page"."""
    if kind == WORKSPACE:
        return "workspace"
    return "space" if item.kind == choices.DocumentKindChoices.SPACE else "page"


def send_invitation_mail(email, invitation, kind, sender, language=None):
    """The email inviting someone, with the link to accept it."""
    item = item_of(kind, invitation)
    name = item.name if kind == WORKSPACE else (item.title or _("Untitled page"))
    sender_name = sender.full_name or sender.email
    language = language or get_language()
    with override(language):
        what = {
            "workspace": _("the workspace"),
            "space": _("the space"),
            "page": _("the page"),
        }[kind_label(kind, item)]
        context = {
            "brandname": settings.EMAIL_BRAND_NAME,
            "logo_img": settings.EMAIL_LOGO_IMG,
            "item_logo_img": invite_logo_url(kind, invitation),
            "title": _("{name} invited you to {what} {item}").format(
                name=sender_name, what=what, item=name
            ),
            "message": _(
                "{name} ({email}) invited you to join {what} “{item}” on "
                "{brand}. Sign up or sign in with Google, Microsoft or "
                "LinkedIn to accept the invitation."
            ).format(
                name=sender_name,
                email=sender.email,
                what=what,
                item=name,
                brand=settings.EMAIL_BRAND_NAME,
            ),
            "link": invite_link(kind, invitation),
            "link_label": name,
            "button_label": _("Accept the invitation"),
        }
        subject = str(context["title"])
        html = render_to_string("mail/html/template.html", context)
        plain = render_to_string("mail/text/template.txt", context)
    try:
        send_mail(
            subject,
            plain,
            settings.EMAIL_FROM,
            [email],
            html_message=html,
            fail_silently=False,
        )
    except smtplib.SMTPException as exception:
        logger.error("invitation to %s was not sent: %s", email, exception)


class InvitationView(APIView):
    """What an invitation is to, for the page accepting it."""

    permission_classes = [drf.permissions.AllowAny]

    def get(self, request, token):
        """Name, kind, who invites, and whether it is still valid."""
        try:
            kind, invitation = find_invitation(token)
        except drf.exceptions.NotFound:
            # Collaborators: used, by one who may open what it was to
            item = accepted_item(token, request.user)
            if item is None:
                raise
            is_workspace = isinstance(item, models.Workspace)
            return accepted_answer(
                item,
                name=item.name if is_workspace else item.title or "",
                description=item.description if is_workspace else "",
                issuer="",
                email=request.user.email,
                has_logo=False,
                is_expired=False,
                is_accepted=True,
            )
        item = item_of(kind, invitation)
        issuer = invitation.issuer
        return drf.response.Response(
            {
                "is_accepted": False,
                "kind": kind_label(kind, item),
                "name": item.name if kind == WORKSPACE else item.title or "",
                "description": item.description if kind == WORKSPACE else "",
                "issuer": (issuer.full_name or issuer.email) if issuer else "",
                "email": invitation.email,
                "has_logo": models.ItemLogo.objects.filter(
                    **{"workspace" if kind == WORKSPACE else "document": item}
                ).exists(),
                "is_expired": invitation.is_expired,
            }
        )


class InvitationLogoView(APIView):
    """The logo of what an invitation is to, for its page."""

    permission_classes = [drf.permissions.AllowAny]

    def get(self, request, token):
        """The image, or 404."""
        kind, invitation = find_invitation(token)
        item = item_of(kind, invitation)
        return logo_response(
            models.ItemLogo.objects.filter(
                **{"workspace" if kind == WORKSPACE else "document": item}
            ).first()
        )


class AcceptInvitationView(APIView):
    """
    Join what one is invited to. A newcomer waiting for approval of their
    registration is let in: the inviter vouches for them.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, token):
        """Become a member (workspace) or get the role (space, page)."""
        try:
            kind, invitation = find_invitation(token)
        except drf.exceptions.NotFound:
            # Collaborators: already in (accepted, or taken by the account
            # when it was made): it opens what it was to
            item = accepted_item(token, request.user)
            if item is None:
                raise
            return accepted_answer(item, id=str(item.id))
        if invitation.is_expired:
            raise drf.exceptions.ValidationError(
                {"token": _("This invitation has expired: ask for a new one.")}
            )
        user = request.user
        item = item_of(kind, invitation)
        with transaction.atomic():
            if kind == WORKSPACE:
                models.WorkspaceAccess.objects.get_or_create(
                    workspace=item, user=user, defaults={"role": invitation.role}
                )
            elif item.get_role(user) is None:
                models.DocumentAccess.objects.create(
                    document=item, user=user, role=invitation.role
                )
            invitation.delete()
            user.mark_invited()
            if user.registration_status != registrations.APPROVED:
                user.registration_status = registrations.APPROVED
                user.save(update_fields=["registration_status", "updated_at"])
        return drf.response.Response(
            {"kind": kind_label(kind, item), "id": str(item.id)}
        )


def validated_email(raw):
    """A lowercase email, or a validation error."""
    email = str(raw or "").strip().lower()
    try:
        validate_email(email)
    except DjangoValidationError as error:
        raise drf.exceptions.ValidationError(
            {"email": _("Enter a valid email address.")}
        ) from error
    return email


def workspace_for_admin(request, workspace_id):
    """The workspace, if the user administers it."""
    workspace = models.Workspace.objects.filter(id=workspace_id).first()
    if workspace is None or workspace.get_role(request.user) is None:
        raise drf.exceptions.NotFound()
    if workspace.get_role(request.user) not in choices.WORKSPACE_PRIVILEGED_ROLES:
        raise drf.exceptions.PermissionDenied()
    return workspace


def serialize_workspace_invitation(invitation):
    """An invitation as listed in the workspace's settings."""
    return {
        "id": str(invitation.id),
        "email": invitation.email,
        "role": invitation.role,
        "created_at": invitation.created_at,
        "is_expired": invitation.is_expired,
    }


class WorkspaceInvitationsView(APIView):
    """The invitations by email to a workspace, for its administrators."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, workspace_id):
        """Pending invitations, newest first."""
        workspace = workspace_for_admin(request, workspace_id)
        return drf.response.Response(
            [
                serialize_workspace_invitation(invitation)
                for invitation in workspace.invitations.order_by("-created_at")
            ]
        )

    def post(self, request, workspace_id):
        """Invite an email (sent again, renewed, when already invited)."""
        workspace = workspace_for_admin(request, workspace_id)
        if not platform_settings.get("email_invitations"):
            raise drf.exceptions.PermissionDenied(
                _("Invitations by email are turned off on this platform.")
            )
        email = validated_email(request.data.get("email"))
        role = request.data.get("role") or choices.WorkspaceRoleChoices.MEMBER
        if role not in choices.WorkspaceRoleChoices.values:
            raise drf.exceptions.ValidationError({"role": _("Unknown role.")})
        if (
            role == choices.WorkspaceRoleChoices.OWNER
            and workspace.get_role(request.user) != choices.WorkspaceRoleChoices.OWNER
        ):
            raise drf.exceptions.PermissionDenied(
                _("Only an owner can make someone an owner.")
            )
        if workspace.accesses.filter(user__email__iexact=email).exists():
            raise drf.exceptions.ValidationError(
                {"email": _("This person is already a member.")}
            )
        invitation, created = models.WorkspaceInvitation.objects.get_or_create(
            workspace=workspace,
            email=email,
            defaults={"role": role, "issuer": request.user},
        )
        if not created:
            invitation.role = role
            invitation.issuer = request.user
            invitation.created_at = timezone.now()
            invitation.save(update_fields=["role", "issuer", "created_at"])
        send_invitation_mail(
            email,
            invitation,
            WORKSPACE,
            request.user,
            request.user.language or settings.LANGUAGE_CODE,
        )
        return drf.response.Response(
            serialize_workspace_invitation(invitation),
            status=drf.status.HTTP_201_CREATED,
        )


class WorkspaceInvitationView(APIView):
    """One invitation to a workspace: taken back by an administrator."""

    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, workspace_id, invitation_id):
        """Cancel the invitation."""
        workspace = workspace_for_admin(request, workspace_id)
        deleted, _rows = workspace.invitations.filter(id=invitation_id).delete()
        if not deleted:
            raise drf.exceptions.NotFound()
        return drf.response.Response(status=drf.status.HTTP_204_NO_CONTENT)


# -- Logos


def logo_response(logo):
    """The image of a logo, cached briefly by browsers; 404 without one."""
    if logo is None:
        raise drf.exceptions.NotFound()
    response = HttpResponse(bytes(logo.data), content_type=logo.content_type)
    response["Cache-Control"] = "private, max-age=300"
    response["X-Content-Type-Options"] = "nosniff"
    return response


def decode_logo(raw):
    """(content type, bytes) of a data URL image, or a validation error."""
    invalid = drf.exceptions.ValidationError(
        {"data": _("Choose a PNG, JPEG, WebP or GIF image under 512 KB.")}
    )
    header, _sep, payload = str(raw or "").partition(",")
    if not header.startswith("data:") or not header.endswith(";base64"):
        raise invalid
    content_type = header[len("data:") : -len(";base64")]
    if content_type not in models.ItemLogo.CONTENT_TYPES:
        raise invalid
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as error:
        raise invalid from error
    if not data or len(data) > models.ItemLogo.MAX_BYTES:
        raise invalid
    signatures = {
        "image/png": (b"\x89PNG",),
        "image/jpeg": (b"\xff\xd8",),
        "image/gif": (b"GIF8",),
        "image/webp": (b"RIFF",),
    }
    if not data.startswith(signatures[content_type]):
        raise invalid
    return content_type, data


class LogoMixin:
    """Read, set and remove the logo of an item."""

    # Collaborators: the logo of what is public shows signed out too
    permission_classes = [permissions.IsAuthenticatedOrSafe]

    def get_item(self, request, pk, change):
        """The item, checking the user may see it (and change it)."""
        raise NotImplementedError

    def get(self, request, pk):
        """The image."""
        item = self.get_item(request, pk, change=False)
        return logo_response(
            models.ItemLogo.objects.filter(**{self.field: item}).first()
        )

    def put(self, request, pk):
        """Set the logo from a data URL."""
        item = self.get_item(request, pk, change=True)
        content_type, data = decode_logo(request.data.get("data"))
        models.ItemLogo.objects.update_or_create(
            **{self.field: item},
            defaults={"content_type": content_type, "data": data},
        )
        return drf.response.Response({"has_logo": True})

    def delete(self, request, pk):
        """Remove the logo."""
        item = self.get_item(request, pk, change=True)
        models.ItemLogo.objects.filter(**{self.field: item}).delete()
        return drf.response.Response(status=drf.status.HTTP_204_NO_CONTENT)


class WorkspaceLogoView(LogoMixin, APIView):
    """The logo of a workspace: its members see it, administrators set it."""

    field = "workspace"

    def get_item(self, request, pk, change):
        workspace = models.Workspace.objects.filter(id=pk).first()
        role = workspace and workspace.get_role(request.user)
        if workspace is None or not workspace.is_shown_to(request.user):
            raise drf.exceptions.NotFound()
        if change and role not in choices.WORKSPACE_PRIVILEGED_ROLES:
            raise drf.exceptions.PermissionDenied()
        return workspace


class DocumentLogoView(LogoMixin, APIView):
    """The logo of a space or a page: who reads it sees it, editors set it."""

    field = "document"

    def get_item(self, request, pk, change):
        document = models.Document.objects.filter(id=pk).first()
        if document is None:
            raise drf.exceptions.NotFound()
        abilities = document.get_abilities(request.user)
        if not abilities.get("retrieve"):
            raise drf.exceptions.NotFound()
        if change and not abilities.get("partial_update"):
            raise drf.exceptions.PermissionDenied()
        return document
