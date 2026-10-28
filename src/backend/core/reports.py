"""
Collaborators: anyone who reads a page may report it to the platform
administrators (and owners), who either dismiss the report or take the page
down: it goes to the trash with the pages below it, and its owners can't
restore it; an administrator can put it back while it is in the trash.

The page's text is kept with the report, as it was, for the administrators
to judge even when they can't open the page. The administrators are told in
their inbox and by email; the reporters and the page's owners are told of
the decision by email. Every decision goes to the platform log.
"""

import logging

from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core import models, platform_roles, presentations, registrations
from core.choices import (
    PlatformLogActionChoices,
    ReportReasonChoices,
    ReportStatusChoices,
    RoleChoices,
)
from core.services.yhub_services import YHubService
from core.tasks.access import reset_service_connections_on_commit
from core.tasks.documents import sync_service_restorations_in_cascade
from core.utils.yjs import yjs_to_text

logger = logging.getLogger(__name__)

EXCERPT_LENGTH = 5000


class ReportError(Exception):
    """A report or a decision that can't be made, with why, to show."""


def page_text(document):
    """
    The page's text as the collaboration server holds it ("" if unread),
    then its presentations, which the text doesn't show: their titles and
    addresses, for administrators to open.
    """
    try:
        update = YHubService().get_ydoc(document)
        text = yjs_to_text(update) if update else ""
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        logger.warning("No text for the reported page %s", document.pk)
        text = ""
    shown = [
        _("Presentation “{title}”: {url}{link}").format(
            title=presentation.title or _("Untitled"),
            url=presentations.view_url(presentation),
            link=f" ({presentation.link_url})" if presentation.link_url else "",
        )
        for presentation in document.presentations.order_by("created_at")
    ]
    return "\n".join(part for part in [text, *shown] if part)


def owners(document):
    """The people owning the page, on it or on a page above it."""
    pages = [*document.get_ancestors(), document]
    return models.User.objects.filter(
        documentaccess__document__in=pages,
        documentaccess__role=RoleChoices.OWNER,
        is_active=True,
    ).distinct()


def _title(document):
    return (document.title or "")[:255] if document else ""


def report(document, reporter, reason, details=""):
    """Report a page one reads; the administrators are told."""
    if reason not in ReportReasonChoices.values:
        raise ReportError(_("Choose why you report this page."))
    if models.ContentReport.objects.filter(
        document=document, reporter=reporter, status=ReportStatusChoices.OPEN
    ).exists():
        raise ReportError(_("You already reported this page: it is being reviewed."))
    content_report = models.ContentReport.objects.create(
        document=document,
        document_title=_title(document),
        excerpt=page_text(document)[:EXCERPT_LENGTH],
        reporter=reporter,
        reporter_name=platform_roles.display_name(reporter),
        reason=reason,
        details=(details or "")[:2000],
    )
    for administrator in platform_roles.at_level(platform_roles.ADMINISTRATOR):
        models.Notification.objects.create(
            recipient=administrator,
            actor=reporter,
            kind=models.Notification.KIND_REPORT,
            document=document,
        )
        registrations.send_email(
            administrator,
            _("A page was reported"),
            _("{name} reported the page “{title}”: {reason}.").format(
                name=reporter.full_name or reporter.email,
                title=_title(document) or _("Untitled page"),
                reason=ReportReasonChoices(reason).label,
            ),
            "/?target=collaborators&tab=reports",
            _("See the reports"),
        )
    return content_report


def _resolve(reports, actor, status, note):
    """Close these open reports with a decision."""
    reports.update(
        status=status,
        resolved_by=actor,
        resolved_by_name=platform_roles.display_name(actor),
        resolved_at=timezone.now(),
        resolution_note=(note or "")[:500],
    )


def _clear_notifications(document):
    """No report of the page left open: it leaves the administrators' inbox."""
    if document is None:
        return
    if not models.ContentReport.objects.filter(
        document=document, status=ReportStatusChoices.OPEN
    ).exists():
        models.Notification.objects.filter(
            kind=models.Notification.KIND_REPORT, document=document
        ).delete()


def dismiss(content_report, actor, note=""):
    """Nothing to take down; the reporter is told."""
    if content_report.status != ReportStatusChoices.OPEN:
        raise ReportError(_("This report was already decided."))
    _resolve(
        models.ContentReport.objects.filter(pk=content_report.pk),
        actor,
        ReportStatusChoices.DISMISSED,
        note,
    )
    _clear_notifications(content_report.document)
    platform_roles.log(
        PlatformLogActionChoices.REPORT_DISMISSED,
        None,
        actor,
        target_name=content_report.document_title,
        report=str(content_report.pk),
        note=note,
    )
    if content_report.reporter:
        registrations.send_email(
            content_report.reporter,
            _("Your report was reviewed"),
            _(
                "A platform administrator reviewed your report about "
                "“{title}” and found nothing to take down."
            ).format(title=content_report.document_title or _("Untitled page")),
        )


def take_down(content_report, actor, note=""):
    """
    The page (with the pages below it) goes to the trash, for good unless an
    administrator puts it back; every open report of it is closed, and its
    owners and reporters are told.
    """
    document = content_report.document
    if content_report.status != ReportStatusChoices.OPEN:
        raise ReportError(_("This report was already decided."))
    if document is None:
        raise ReportError(_("This page no longer exists."))
    with transaction.atomic():
        if document.deleted_at is None and document.ancestors_deleted_at is None:
            document.soft_delete()
            reset_service_connections_on_commit(document.pk)
        models.Document.objects.filter(pk=document.pk).update(
            taken_down_at=timezone.now()
        )
        open_reports = models.ContentReport.objects.filter(
            document=document, status=ReportStatusChoices.OPEN
        )
        reporters = list(
            models.User.objects.filter(
                reports_made__in=open_reports, is_active=True
            ).distinct()
        )
        _resolve(open_reports, actor, ReportStatusChoices.TAKEN_DOWN, note)
        _clear_notifications(document)
        platform_roles.log(
            PlatformLogActionChoices.TAKEN_DOWN,
            None,
            actor,
            target_name=content_report.document_title,
            report=str(content_report.pk),
            document=str(document.pk),
            note=note,
        )
    title = content_report.document_title or _("Untitled page")
    for owner in owners(document):
        message = _(
            "A platform administrator took down your page “{title}” after a "
            "report: it is in the trash, with the pages below it."
        ).format(title=title)
        if note:
            message = f"{message} " + _("Reason: {reason}").format(reason=note)
        registrations.send_email(owner, _("Your page was taken down"), message)
    for reporter in reporters:
        registrations.send_email(
            reporter,
            _("Your report was reviewed"),
            _(
                "A platform administrator reviewed your report about "
                "“{title}” and took the page down. Thank you."
            ).format(title=title),
        )


def put_back(content_report, actor):
    """Undo a take-down while the page is still in the trash."""
    document = content_report.document
    if document is None or not document.taken_down_at:
        raise ReportError(_("This page is not taken down."))
    with transaction.atomic():
        models.Document.objects.filter(pk=document.pk).update(taken_down_at=None)
        document.taken_down_at = None
        if document.deleted_at is not None:
            try:
                document.restore()
            except RuntimeError as err:
                raise ReportError(str(err)) from err
            transaction.on_commit(
                lambda: sync_service_restorations_in_cascade.delay(str(document.id))
            )
        platform_roles.log(
            PlatformLogActionChoices.PUT_BACK,
            None,
            actor,
            target_name=content_report.document_title,
            report=str(content_report.pk),
            document=str(document.pk),
        )
