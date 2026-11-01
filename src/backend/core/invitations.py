"""
Collaborators: the tokens, links and emails of invitations by email to
workspaces, spaces and pages (core.api.invitations serves their page).

Apart from the API so that the Celery task sending invitations sent
together (core.tasks.mail) reaches them without importing the API back.
"""

import smtplib
from logging import getLogger

from django.conf import settings
from django.contrib.sites.models import Site
from django.core import signing
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.translation import get_language, ngettext, override
from django.utils.translation import gettext_lazy as _

from core import choices, models

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


def app_domain():
    """The app's address, for the links of emails."""
    return settings.EMAIL_URL_APP or Site.objects.get_current().domain


def invite_link(kind, invitation):
    """The page to accept the invitation."""
    return f"{app_domain()}/invite/?token={make_token(kind, invitation)}"


def bundle_link(bundle):
    """The page listing the invitations sent together, to accept them."""
    token = signing.dumps({"b": str(bundle.id)}, salt=SALT)
    return f"{app_domain()}/invite/?token={token}"


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
    return f"{app_domain()}/api/v1.0/invitations/{make_token(kind, invitation)}/logo/"


def item_of(kind, invitation):
    """The workspace or document an invitation is to."""
    return invitation.workspace if kind == WORKSPACE else invitation.document


def kind_label(kind, item):
    """ "workspace", "space" or "page"."""
    if kind == WORKSPACE:
        return "workspace"
    return "space" if item.kind == choices.DocumentKindChoices.SPACE else "page"


def item_name(kind, item):
    """The name of a workspace, the title of a space or page."""
    return item.name if kind == WORKSPACE else (item.title or _("Untitled page"))


def what_of(kind, item):
    """ "the workspace", "the space" or "the page"."""
    return {
        "workspace": _("the workspace"),
        "space": _("the space"),
        "page": _("the page"),
    }[kind_label(kind, item)]


def role_label(kind, invitation):
    """The role an invitation gives, as its email and page say it."""
    roles = choices.WorkspaceRoleChoices if kind == WORKSPACE else choices.RoleChoices
    return str(roles(invitation.role).label).lower()


def deliver(email, subject, context):
    """An email from the template, logged when it could not be sent."""
    html = render_to_string("mail/html/template.html", context)
    plain = render_to_string("mail/text/template.txt", context)
    try:
        send_mail(
            str(subject),
            plain,
            settings.EMAIL_FROM,
            [email],
            html_message=html,
            fail_silently=False,
        )
    except smtplib.SMTPException as exception:
        logger.error("invitation to %s was not sent: %s", email, exception)


def send_invitation_mail(email, invitation, kind, sender, language=None):
    """The email inviting someone, with the link to accept it."""
    item = item_of(kind, invitation)
    name = item_name(kind, item)
    sender_name = sender.full_name or sender.email
    language = language or get_language()
    with override(language):
        what = what_of(kind, item)
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
        deliver(email, context["title"], context)


def bundle_invitations(bundle):
    """(kind, invitation) of a bundle: workspaces, then spaces, then pages."""
    found = [
        (WORKSPACE, invitation)
        for invitation in bundle.workspace_invitations.select_related(
            "workspace"
        ).order_by("created_at")
    ] + [
        (DOCUMENT, invitation)
        for invitation in bundle.document_invitations.select_related(
            "document"
        ).order_by("created_at")
    ]
    order = {"workspace": 0, "space": 1, "page": 2}
    return sorted(found, key=lambda pair: order[kind_label(pair[0], item_of(*pair))])


def send_bundle(bundle_id, version):
    """
    The email of invitations sent together, unless sent already or another
    invitation joined them since this was queued (its own task sends it).
    """
    with transaction.atomic():
        bundle = (
            models.InvitationBundle.objects.select_for_update()
            .filter(id=bundle_id, version=version, sent_at__isnull=True)
            .first()
        )
        if bundle is None:
            return
        pending = bundle_invitations(bundle)
        bundle.sent_at = timezone.now()
        bundle.items = [
            [kind, str(item_of(kind, invitation).id)] for kind, invitation in pending
        ]
        bundle.save(update_fields=["sent_at", "items", "updated_at"])
    sender = bundle.issuer
    if sender is None or not pending:
        # its sender's account is gone, or its invitations were cancelled
        return
    language = bundle.language or settings.LANGUAGE_CODE
    if len(pending) > 1:
        send_bundle_mail(bundle, pending, sender, language)
        return
    # One invitation: its email as it always was
    kind, invitation = pending[0]
    if kind == WORKSPACE:
        send_invitation_mail(invitation.email, invitation, kind, sender, language)
    else:
        invitation.document.send_invitation_email(
            invitation.email,
            invitation.role,
            sender,
            language,
            link=invite_link(kind, invitation),
            logo_img=invite_logo_url(kind, invitation),
        )


def send_bundle_mail(bundle, pending, sender, language):
    """One email for several invitations, each with its logo and role."""
    sender_name = sender.full_name or sender.email
    with override(language):
        rows = []
        for kind, invitation in pending:
            item = item_of(kind, invitation)
            rows.append(
                {
                    "logo": invite_logo_url(kind, invitation),
                    "label": _("{what} “{item}”, as {role}").format(
                        what=what_of(kind, item),
                        item=item_name(kind, item),
                        role=role_label(kind, invitation),
                    ),
                }
            )
        first_kind, first = pending[0]
        others = len(pending) - 1
        title = ngettext(
            "{name} invited you to {item} and {count} more",
            "{name} invited you to {item} and {count} more",
            others,
        ).format(
            name=sender_name,
            item=item_name(first_kind, item_of(first_kind, first)),
            count=others,
        )
        context = {
            "brandname": settings.EMAIL_BRAND_NAME,
            "logo_img": settings.EMAIL_LOGO_IMG,
            "title": title,
            "message": _(
                "{name} ({email}) invited you to join these on {brand}. Sign "
                "up or sign in with Google, Microsoft or LinkedIn to accept "
                "the invitations."
            ).format(
                name=sender_name,
                email=sender.email,
                brand=settings.EMAIL_BRAND_NAME,
            ),
            "invitations": rows,
            "link": bundle_link(bundle),
            "link_label": _("See the invitations"),
            "button_label": _("Accept the invitations"),
        }
        deliver(bundle.email, title, context)
