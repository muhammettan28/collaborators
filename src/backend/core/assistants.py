"""
Collaborators: input from one's own AI assistant (Claude, ChatGPT, Gemini…),
through the MCP server (core.api.mcp), always as the person who approved
the assistant at the sign-in server.

First version: the assistant finds the pages the person can edit, and adds
the person's input to one of them, at the end, as a closed toggle heading 3
titled "Input from <name> (<email>) · via <assistant> · <date>" (in the
person's language). It changes nothing else. The input is credited to the person in
the page's history, and everyone on the page sees it arrive live.

The assistant runs on the person's own plan with its provider: Collaborators
calls no AI model, and neither charges nor pays for its use.
"""

from django.conf import settings
from django.db.models import Exists, OuterRef, Q
from django.db.models.functions import Left, Length
from django.utils import formats, timezone
from django.utils.translation import gettext as _
from django.utils.translation import override

from core import models
from core.services.converter_services import YdocConverter
from core.services.yhub_services import YHubService

# What an assistant may add at once
MAX_INPUT_LENGTH = 100_000


class InputError(Exception):
    """Input that can't be added, with why, for the assistant to say."""


def page_url(document):
    """Where the page is read."""
    return f"{settings.EMAIL_URL_APP or ''}/page/{document.pk}/"


def editable_pages(user, query="", limit=20):
    """
    The pages (and spaces) the person can edit, which they have a role on
    or above, most recently changed first; found by title.
    """
    has_role = models.DocumentAccess.objects.filter(
        Q(user=user) | Q(team__in=user.teams),
        document__path=Left(OuterRef("path"), Length("document__path")),
    )
    documents = (
        models.Document.objects.filter(
            ancestors_deleted_at__isnull=True, deleted_at__isnull=True
        )
        .annotate(involved=Exists(has_role))
        .filter(involved=True)
        .order_by("-updated_at")
    )
    query = (query or "").strip()
    if query:
        documents = documents.filter(title__icontains=query)
    pages = []
    for document in documents[: limit * 3]:
        if document.get_abilities(user).get("update"):
            pages.append(
                {
                    "id": str(document.pk),
                    "title": document.title or _("Untitled page"),
                    "kind": document.kind,
                    "url": page_url(document),
                    "updated_at": document.updated_at.isoformat(),
                }
            )
        if len(pages) >= limit:
            break
    return pages


def workspaces_of(user, query="", limit=20):
    """
    The workspaces the person belongs to, found by name: where their
    assistant may launch a page (core.presentations.new_page).
    """
    workspaces = models.Workspace.objects.filter(accesses__user=user)
    query = (query or "").strip()
    if query:
        workspaces = workspaces.filter(name__icontains=query)
    return [
        {
            "id": str(workspace.pk),
            "title": workspace.name,
            "kind": "workspace",
            "url": f"{settings.EMAIL_URL_APP or ''}/workspace/{workspace.pk}/",
        }
        for workspace in workspaces.order_by("name")[:limit]
    ]


def toggle_title(user, assistant, when=None):
    """The toggle's title, in the person's language."""
    when = timezone.localtime(when or timezone.now())
    with override(user.language or settings.LANGUAGE_CODE):
        return _("Input from {name} ({email}) · via {assistant} · {date}").format(
            name=user.full_name or user.email,
            email=user.email,
            assistant=(assistant or "").strip()[:60] or _("an AI assistant"),
            date=formats.date_format(when, "DATE_FORMAT"),
        )


def find_page(user, page_id):
    """A page the person can edit, or why not."""
    document = models.Document.objects.filter(
        pk=page_id, ancestors_deleted_at__isnull=True
    ).first()
    if document is None or not document.get_abilities(user).get("retrieve"):
        raise InputError(_("This page doesn't exist, or you can't see it."))
    if not document.get_abilities(user).get("update"):
        raise InputError(_("You can't edit this page, so nothing can be added."))
    return document


def add_input(user, page_id, text, assistant=""):
    """
    Add the person's input at the end of a page they can edit, as a closed
    toggle heading 3 with their name and email in its title. Returns the page.
    """
    text = (text or "").strip()
    if not text:
        raise InputError(_("There is nothing to add."))
    if len(text) > MAX_INPUT_LENGTH:
        raise InputError(_("That is too long to add at once."))
    document = find_page(user, page_id)
    current = YHubService().get_ydoc(document)
    update = YdocConverter().append_toggle(current, toggle_title(user, assistant), text)
    YHubService(user=user).append_ydoc(document, update)
    return {
        "id": str(document.pk),
        "title": document.title or _("Untitled page"),
        "url": page_url(document),
    }
