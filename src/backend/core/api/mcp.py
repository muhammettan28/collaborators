"""
Collaborators: the MCP server people connect their own AI assistant to
(Claude, ChatGPT, Gemini…), at `<app>/mcp` — MCP's "streamable HTTP"
transport, stateless: JSON-RPC requests POSTed, each answered in JSON.

    POST /mcp                                     initialize, ping, tools/list, tools/call
    GET  /.well-known/oauth-protected-resource[/mcp]   where to sign in

Every request carries an access token from the sign-in server (Keycloak):
the assistant registered there on its own and the person signed in and
approved it. The token names the person (by email, as signing in does);
without one, the answer says where to get it. What the assistant may do is
in core.assistants: find the pages the person can edit, and add their input
to one; and in core.presentations: publish an HTML presentation in a page
(with its PDF twin), or launch a new page with it at its top (of one's own,
or in a space), shared as asked; replace it later at the same address, and
read how to make presentations for Collaborators (its guide); every file
sent is checked against the guide, and the answer says what it misses.
"""

import base64
import binascii
import json
import logging
import uuid
from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

import jwt

from core import (
    assistants,
    merging,
    models,
    platform_settings,
    presentation_guide,
    presentations,
    registrations,
)
from core.api import invitations, publishing
from core.services import keycloak
from core.services.converter_services import ServiceUnavailableError
from core.services.yhub_services import YHubError
from core.utils.users import can_find

logger = logging.getLogger(__name__)

# Newest first; an older one asked for is answered in kind
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")

# Who may open a page launched with a presentation, with its link: its link
# reach (restricted: only those it is shared with, as a new page starts)
SHARES = {
    "restricted": None,
    "authenticated": models.LinkReachChoices.AUTHENTICATED,
    "public": models.LinkReachChoices.PUBLIC,
}
# The people one's assistant may add to a page it launches, and as what
MAX_MEMBERS = 50
MEMBER_ROLES = ("reader", "commenter", "editor", "administrator")

TOOLS = [
    {
        "name": "find_pages",
        "title": "Find pages",
        "description": (
            "Find the Collaborators pages the user can add input to (pages "
            "they can edit), most recently changed first. Optionally filter "
            "by words of the title; with the workspaces they belong to "
            '(`kind` "workspace") and spaces ("space"), where '
            "create_presentation_page can launch a page."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Words of the page's title (optional)",
                }
            },
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "add_input_to_page",
        "title": "Add input to a page",
        "description": (
            "Add the user's input at the end of an existing Collaborators page "
            "they can edit. It goes in as a closed toggle heading titled with "
            "the user's name and email; nothing else on the page changes. "
            "Write the input in Markdown (headings, lists, tables, links)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "The page's id, as find_pages gives it",
                },
                "text": {
                    "type": "string",
                    "description": "The input, in Markdown",
                },
                "assistant_name": {
                    "type": "string",
                    "description": "Your name as an assistant, e.g. Claude",
                },
            },
            "required": ["page_id", "text"],
        },
        "annotations": {"destructiveHint": False, "idempotentHint": False},
    },
    {
        "name": "publish_presentation",
        "title": "Publish a presentation in a page",
        "description": (
            "Publish an HTML presentation (a standalone HTML file: slides "
            "made in a chat or exported from Claude Design) in a "
            "Collaborators page the user can edit. It is added at the end "
            "of the page, where readers click through it, and gets a "
            "permanent address and an 'Export to PDF' address. Give the "
            "HTML itself in `html`; or `link`, the https address of an HTML "
            "file hosted elsewhere (shown from there, always its current "
            "state); or, for a file too big to write out (over about "
            "200 KB), set `upload_later` and upload it within 15 minutes "
            "with the command returned (curl -F file=@deck.html "
            "-F pdf=@deck.pdf <address>). Before making one, read "
            "presentation_guide: make its PDF at the same time (one slide "
            "per page) and send both (`pdf_base64` or `pdf_link`), give it "
            "print rules and a presentation card, and a time handle to a "
            "script-driven animation. The answer lists what the file misses "
            "of the guide: fix it with replace_presentation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "The page's id, as find_pages gives it",
                },
                "title": {
                    "type": "string",
                    "description": "Its title (else the HTML's own <title>)",
                },
                "html": {"type": "string", "description": "The HTML file"},
                "link": {
                    "type": "string",
                    "description": "Or: the https address of an HTML file",
                },
                "upload_later": {
                    "type": "boolean",
                    "description": (
                        "Or: get an address to upload the file (and its PDF) to"
                    ),
                },
                "pdf_base64": {
                    "type": "string",
                    "description": (
                        "Its PDF twin (one slide per page), base64-encoded"
                    ),
                },
                "pdf_link": {
                    "type": "string",
                    "description": "Or: the https address of its PDF",
                },
            },
            "required": ["page_id"],
        },
        "annotations": {"destructiveHint": False, "idempotentHint": False},
    },
    {
        "name": "create_presentation_page",
        "title": "Launch a page with a presentation",
        "description": (
            "Create a new Collaborators page with an HTML presentation at its "
            "top (an animation or slides made in a chat, with its PDF twin), "
            "ready to share. The page is the user's own, or goes straight in "
            "a workspace they belong to, in a space, or under a page they can "
            "edit (`place_id`, as find_pages gives it). `share` says who may "
            'open it with its link: "restricted" (default: those it is '
            "shared with, the members of its workspace or the people of its "
            'space), "authenticated" (anyone signed in to '
            'Collaborators) or "public" (anyone, as the workspace\'s '
            "publishing rules allow). `members` adds people by email, each "
            "told by email (ask the user for their addresses): those the user "
            "can find get their role at once, the others are invited by "
            "email. Give the file and its PDF as for "
            "publish_presentation, after reading presentation_guide. The "
            "answer gives the page's address to share, the presentation's "
            "addresses, and what the file misses of the guide."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": ("The page's title (else the HTML's own <title>)"),
                },
                "place_id": {
                    "type": "string",
                    "description": (
                        "A workspace, space or page to create it in, as "
                        "find_pages gives it (optional: else a page of the "
                        "user's own)"
                    ),
                },
                "share": {
                    "type": "string",
                    "enum": list(SHARES),
                    "description": "Who may open it with its link",
                },
                "members": {
                    "type": "array",
                    "description": "People to add to it (optional)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "email": {"type": "string"},
                            "role": {
                                "type": "string",
                                "enum": list(MEMBER_ROLES),
                                "description": "Default: reader",
                            },
                        },
                        "required": ["email"],
                    },
                },
                "html": {"type": "string", "description": "The HTML file"},
                "link": {
                    "type": "string",
                    "description": "Or: the https address of an HTML file",
                },
                "upload_later": {
                    "type": "boolean",
                    "description": (
                        "Or: get an address to upload the file (and its PDF) to"
                    ),
                },
                "pdf_base64": {
                    "type": "string",
                    "description": (
                        "Its PDF twin (one slide per page), base64-encoded"
                    ),
                },
                "pdf_link": {
                    "type": "string",
                    "description": "Or: the https address of its PDF",
                },
            },
        },
        "annotations": {"destructiveHint": False, "idempotentHint": False},
    },
    {
        "name": "replace_presentation",
        "title": "Replace a presentation",
        "description": (
            "Replace a presentation published in a Collaborators page with "
            "a new version, at the same address: the page shows the new one "
            "at once and its PDF address gives it from then on (earlier "
            "versions stay in its history). Give `html`, `link` or "
            "`upload_later` as for publish_presentation, with its new PDF "
            "(`pdf_base64` or `pdf_link`): replace both together. A PDF "
            "alone goes with what it shows now; `title` alone renames it. "
            "The answer lists what the file misses of presentation_guide."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "presentation_id": {
                    "type": "string",
                    "description": "Its id, as list_presentations gives it",
                },
                "title": {"type": "string", "description": "A new title"},
                "html": {"type": "string", "description": "The new HTML file"},
                "link": {
                    "type": "string",
                    "description": "Or: the https address of an HTML file",
                },
                "upload_later": {
                    "type": "boolean",
                    "description": (
                        "Or: get an address to upload the file (and its PDF) to"
                    ),
                },
                "pdf_base64": {
                    "type": "string",
                    "description": (
                        "Its PDF twin (one slide per page), base64-encoded"
                    ),
                },
                "pdf_link": {
                    "type": "string",
                    "description": "Or: the https address of its PDF",
                },
            },
            "required": ["presentation_id"],
        },
        "annotations": {"destructiveHint": False, "idempotentHint": False},
    },
    {
        "name": "list_presentations",
        "title": "List presentations",
        "description": (
            "List the presentations in the Collaborators pages the user can "
            "edit (or in one page), with their ids, addresses and PDF "
            "addresses."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "Only this page's (optional)",
                }
            },
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "presentation_guide",
        "title": "How to make presentations for Collaborators",
        "description": (
            "Read this before making a presentation to publish: how to make "
            "its HTML and PDF so that its PDF matches its slides, readers "
            "can page through it, and an animation's time bar works."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True},
    },
]


def resource_url():
    """The MCP server's address, which tokens must be meant for."""
    return settings.COLLABORATORS_MCP_RESOURCE or (
        f"{(settings.EMAIL_URL_APP or '').rstrip('/')}/mcp"
    )


def issuer():
    """The sign-in server's realm, which issues the tokens."""
    endpoint = settings.OIDC_OP_AUTHORIZATION_ENDPOINT or ""
    return endpoint.rsplit("/protocol/", 1)[0]


def _metadata_url():
    base = resource_url().rsplit("/mcp", 1)[0]
    return f"{base}/.well-known/oauth-protected-resource"


@require_http_methods(["GET"])
def protected_resource_metadata(_request):
    """Where an assistant signs in to use this server (RFC 9728)."""
    return JsonResponse(
        {
            "resource": resource_url(),
            "authorization_servers": [issuer()],
            "bearer_methods_supported": ["header"],
            "scopes_supported": ["openid", "email", "profile"],
            "resource_name": "Collaborators",
        }
    )


@lru_cache(maxsize=1)
def _jwks():
    return jwt.PyJWKClient(settings.OIDC_OP_JWKS_ENDPOINT, cache_keys=True)


def _unauthorized(error=None):
    challenge = f'Bearer resource_metadata="{_metadata_url()}"'
    if error:
        challenge += f', error="{error}"'
    response = JsonResponse({"error": error or "unauthorized"}, status=401)
    response["WWW-Authenticate"] = challenge
    return response


def person_of(token):
    """The person a valid token names, and the token's claims; else None."""
    try:
        key = _jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=resource_url(),
            issuer=issuer(),
        )
    except (jwt.PyJWTError, ValueError) as err:
        logger.info("MCP token refused: %s", err)
        return None, None
    user = merging.account_of(claims.get("sub"), claims.get("email"))
    if (
        user is None
        or not user.is_active
        or user.registration_status != registrations.APPROVED
    ):
        return None, claims
    return user, claims


@lru_cache(maxsize=256)
def _known_client_name(client_id):
    # Only names found are kept: a failed lookup is tried again next time
    name = keycloak.client_name(client_id)
    if not name:
        raise LookupError(client_id)
    return name


def client_name(client_id):
    """The name an assistant registered under at the sign-in server, or ""."""
    if not client_id:
        return ""
    try:
        return _known_client_name(client_id)
    except LookupError, keycloak.KeycloakError:
        return ""


def _result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code, message):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _text(text, is_error=False, structured=None):
    result = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if structured is not None:
        result["structuredContent"] = structured
    return result


def _call_tool(user, claims, name, arguments):
    """Run one tool as the person; errors become a result the model reads."""
    if name in PRESENTATION_TOOLS:
        return _call_presentation_tool(user, name, arguments)
    return _call_input_tool(user, claims, name, arguments)


def _call_input_tool(user, claims, name, arguments):
    """Finding pages and adding one's input to one (core.assistants)."""
    if name == "find_pages":
        query = arguments.get("query") or ""
        pages = assistants.workspaces_of(user, query) + assistants.editable_pages(
            user, query
        )
        if not pages:
            return _text(_("No page you can edit matches."), structured={"pages": []})
        return _text(json.dumps(pages, ensure_ascii=False), structured={"pages": pages})
    if name == "add_input_to_page":
        assistant = (arguments.get("assistant_name") or "").strip() or client_name(
            claims.get("azp") or ""
        )
        try:
            page = assistants.add_input(
                user, arguments.get("page_id"), arguments.get("text"), assistant
            )
        except assistants.InputError as err:
            return _text(str(err), is_error=True)
        except ServiceUnavailableError, YHubError:
            logger.exception("MCP input not added")
            return _text(_("The input could not be added right now."), is_error=True)
        return _text(
            _("Added to “{title}”: {url}").format(title=page["title"], url=page["url"]),
            structured={"page": page},
        )
    return None


def _call_presentation_tool(user, name, arguments):
    """Publishing, replacing and listing presentations (core.presentations)."""
    try:
        return PRESENTATION_TOOLS[name](user, arguments)
    except (assistants.InputError, presentations.PresentationError) as err:
        return _text(str(err), is_error=True)
    except ServiceUnavailableError, YHubError:
        logger.exception("MCP presentation not published")
        return _text(
            _("The presentation could not be published right now."),
            is_error=True,
        )


def _presentation_summary(presentation, user, upload_url=None):
    described = presentations.describe(presentation, user)
    summary = {
        key: described[key]
        for key in (
            "id",
            "title",
            "source",
            "link",
            "page",
            "view_url",
            "pdf_url",
            "pdf",
        )
    }
    lines = [
        _("“{title}” in the page “{page}”.").format(
            title=presentation.title or _("Presentation"),
            page=presentation.document.title or _("Untitled page"),
        ),
        _("Shown at: {url}").format(url=described["view_url"]),
        _("PDF, always current: {url}").format(url=described["pdf_url"]),
    ]
    if upload_url:
        summary["upload_url"] = upload_url
        lines.append(
            _(
                "Upload the HTML file and its PDF within 15 minutes, once: "
                "curl -F file=@<file.html> -F pdf=@<file.pdf> {url} (the "
                "answer lists what they miss of the guide)"
            ).format(url=upload_url)
        )
    elif described["has_content"]:
        found = presentations.checks_of(presentation)
        summary["checks"] = found
        if found:
            lines.append(
                _("What it misses of presentation_guide (fix it and replace it):")
            )
            lines.extend(f"- {check}" for check in found)
        else:
            lines.append(_("It follows presentation_guide."))
    return _text("\n".join(lines), structured={"presentation": summary})


def _pdf_of(arguments):
    """Its PDF twin, given as base64 or a link; checked; or None."""
    encoded = (arguments.get("pdf_base64") or "").strip()
    link = (arguments.get("pdf_link") or "").strip() or None
    if not encoded and not link:
        return None
    data = None
    if encoded:
        try:
            data = base64.b64decode(encoded, validate=False)
        except (binascii.Error, ValueError) as err:
            raise assistants.InputError(_("pdf_base64 isn't valid base64.")) from err
    return presentations.prepare_pdf(data=data, link=link)


def _content_of(arguments):
    """The HTML, the link, or an upload to come; one of them."""
    html = arguments.get("html")
    link = (arguments.get("link") or "").strip() or None
    later = bool(arguments.get("upload_later"))
    if sum((html is not None and html != "", bool(link), later)) > 1:
        raise assistants.InputError(_("Give html, link or upload_later: one of them."))
    return (html or None), link, later


def _publish_presentation(user, arguments):
    document = assistants.find_page(user, arguments.get("page_id"))
    html, link, later = _content_of(arguments)
    if not (html or link or later):
        raise assistants.InputError(_("Give html, link or upload_later."))
    presentation = presentations.create(
        user,
        document,
        title=arguments.get("title") or "",
        html=html,
        link=link,
        pdf=_pdf_of(arguments),
    )
    try:
        presentations.add_to_page(user, presentation)
    except Exception:
        presentations.remove(presentation)
        raise
    upload_url = presentations.upload_address(user, presentation) if later else None
    return _presentation_summary(presentation, user, upload_url)


def _place_of(user, place_id):
    """
    Where a new page goes: (a space or page, a workspace), (None, None) for a
    page of one's own; or why not.
    """
    if not place_id:
        return None, None
    found = _uuid_or_none(place_id)
    workspace = models.Workspace.objects.filter(pk=found).first()
    if workspace is not None and workspace.get_role(user) is not None:
        return None, workspace
    parent = models.Document.objects.filter(
        pk=found, ancestors_deleted_at__isnull=True
    ).first()
    if parent is None or not parent.get_abilities(user).get("retrieve"):
        raise assistants.InputError(_("This place doesn't exist, or you can't see it."))
    if not parent.get_abilities(user).get("children_create"):
        raise assistants.InputError(_("You can't create pages there."))
    return parent, None


def _reach_of(user, share, document, abilities):
    """
    The link reach the new page gets, None to leave it restricted; or why it
    can't: one manages the link of a page of one's own or in a workspace, of
    a page in a space one administers; publishing follows the workspace's
    rules.
    """
    reach = SHARES[share]
    if reach is None:
        return None
    if not abilities["link_configuration"]:
        raise assistants.InputError(
            _(
                "You can't change who opens pages there: leave share out, "
                "or make it a page of your own."
            )
        )
    if reach == models.LinkReachChoices.PUBLIC and not publishing.can_publish(
        user, document, abilities
    ):
        raise assistants.InputError(
            _("Your workspace only lets its administrators publish.")
        )
    return reach


def _who_opens(reach, parent, workspace):
    if reach == models.LinkReachChoices.PUBLIC:
        return _("anyone with its link (public)")
    if reach == models.LinkReachChoices.AUTHENTICATED:
        return _("anyone signed in to Collaborators, with its link")
    if workspace is not None:
        return _("the members of “{place}”").format(place=workspace.name)
    if parent is not None:
        return _("the people of “{place}”").format(
            place=parent.title or _("Untitled page")
        )
    return _("only you, until you share it")


def _members_of(arguments):
    """The people to add to a new page, checked: [(email, role)]."""
    members = arguments.get("members") or []
    if not isinstance(members, list) or len(members) > MAX_MEMBERS:
        raise assistants.InputError(
            _("members is a list of up to {count} people.").format(count=MAX_MEMBERS)
        )
    found = []
    for given in members:
        member = given if isinstance(given, dict) else {"email": given}
        email = str(member.get("email") or "").strip().lower()
        role = member.get("role") or models.RoleChoices.READER
        try:
            validate_email(email)
        except ValidationError as err:
            raise assistants.InputError(
                _("“{email}” isn't an email address.").format(email=email)
            ) from err
        if role not in MEMBER_ROLES:
            raise assistants.InputError(
                _("A member's role is one of: {roles}.").format(
                    roles=", ".join(MEMBER_ROLES)
                )
            )
        found.append((email, role))
    return found


def _add_members(user, document, members):
    """
    The people added to the new page, each told by email, as the share
    dialog does: those one may find get their role at once; the others (and
    those without an account) are invited by email, when the platform allows
    it. What became of each.
    """
    language = user.language or settings.LANGUAGE_CODE
    outcome = []
    for email, role in members:
        if email == user.email.lower():
            continue
        member = models.User.objects.filter(email__iexact=email).first()
        if member is not None and (
            not settings.COLLABORATORS_PEOPLE_PRIVACY or can_find(user.id, member.id)
        ):
            models.DocumentAccess.objects.update_or_create(
                document=document, user=member, defaults={"role": role}
            )
            document.send_invitation_email(
                member.email, role, user, member.language or language
            )
            outcome.append({"email": email, "role": role, "status": "added"})
        elif platform_settings.get("email_invitations"):
            invitation, _created = models.Invitation.objects.update_or_create(
                document=document,
                email=email,
                defaults={"role": role, "issuer": user},
            )
            invitations.queue_invitation_mail(invitation, user, language)
            outcome.append({"email": email, "role": role, "status": "invited"})
        else:
            outcome.append({"email": email, "role": role, "status": "not_added"})
    return outcome


def _member_line(member):
    if member["status"] == "added":
        line = _("{email} added as {role}, and told by email")
    elif member["status"] == "invited":
        line = _("{email} invited by email as {role}, to accept")
    else:
        line = _(
            "{email} not added: invitations by email are turned off, so they "
            "sign in first, then the page is shared with them"
        )
    return "- " + line.format(email=member["email"], role=member["role"])


def _create_presentation_page(user, arguments):
    parent, workspace = _place_of(user, arguments.get("place_id"))
    share = arguments.get("share") or "restricted"
    if share not in SHARES:
        raise assistants.InputError(
            _("share is one of: {shares}.").format(shares=", ".join(SHARES))
        )
    members = _members_of(arguments)
    html, link, later = _content_of(arguments)
    if not (html or link or later):
        raise assistants.InputError(_("Give html, link or upload_later."))
    pdf = _pdf_of(arguments)
    title = (arguments.get("title") or "").strip()
    with transaction.atomic():
        document = presentations.new_page(user, title, parent, workspace)
        abilities = document.get_abilities(user)
        reach = _reach_of(user, share, document, abilities)
        if members and not abilities["accesses_manage"]:
            raise assistants.InputError(
                _(
                    "You can't add people to pages there: leave members out, "
                    "or make it a page of your own or of a workspace."
                )
            )
        presentation = presentations.create(
            user, document, title=title, html=html, link=link, pdf=pdf
        )
        try:
            document.title = (title or presentation.title or _("Presentation"))[:255]
            if reach is not None:
                document.link_reach = reach
                document.link_role = models.LinkRoleChoices.READER
            document.save()
            if reach == models.LinkReachChoices.PUBLIC:
                publishing.log_publication(
                    document, user, models.PublicationActionChoices.PAGE_PUBLISHED
                )
            presentations.start_page(user, presentation)
        except Exception:
            # its files go; the page goes with the transaction
            presentations.remove(presentation)
            raise
    added = _add_members(user, document, members)
    upload_url = presentations.upload_address(user, presentation) if later else None
    summary = _presentation_summary(presentation, user, upload_url)
    page = {
        "id": str(document.pk),
        "title": document.title,
        "url": presentations.page_url(document),
        "share": share,
        "members": added,
    }
    summary["structuredContent"]["page"] = page
    summary["content"][0]["text"] = "\n".join(
        [
            _("Created the page “{title}”, the presentation at its top: {url}").format(
                title=page["title"], url=page["url"]
            ),
            _("Who opens it with its link: {who}.").format(
                who=_who_opens(reach, parent, workspace)
            ),
            *(_member_line(member) for member in added),
            summary["content"][0]["text"],
        ]
    )
    return summary


def _replace_presentation(user, arguments):
    presentation = (
        models.Presentation.objects.select_related("document")
        .filter(pk=_uuid_or_none(arguments.get("presentation_id")))
        .first()
    )
    if presentation is None or not presentations.can_read(user, presentation):
        raise assistants.InputError(
            _("This presentation doesn't exist, or you can't see it.")
        )
    if not presentations.can_edit(user, presentation):
        raise assistants.InputError(_("You can't edit the page of this presentation."))
    html, link, later = _content_of(arguments)
    title = arguments.get("title")
    pdf = _pdf_of(arguments)
    if not (html or link or later or title or pdf):
        raise assistants.InputError(
            _("Give html, link, upload_later, a PDF or a title.")
        )
    presentations.replace(
        user, presentation, html=html, link=link, title=title, pdf=pdf
    )
    upload_url = presentations.upload_address(user, presentation) if later else None
    return _presentation_summary(presentation, user, upload_url)


def _list_presentations(user, arguments):
    page_id = arguments.get("page_id")
    if page_id:
        pages = [str(assistants.find_page(user, page_id).pk)]
    else:
        pages = [page["id"] for page in assistants.editable_pages(user, limit=100)]
    found = [
        {
            key: described[key]
            for key in ("id", "title", "source", "page", "view_url", "pdf_url")
        }
        for described in (
            presentations.describe(presentation, user)
            for presentation in models.Presentation.objects.filter(
                document_id__in=pages
            )
            .select_related("document", "current")
            .order_by("-updated_at")
        )
    ]
    if not found:
        return _text(_("No presentation found."), structured={"presentations": []})
    return _text(
        json.dumps(found, ensure_ascii=False), structured={"presentations": found}
    )


def _uuid_or_none(value):
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _presentation_guide(_user, _arguments):
    return _text(
        presentation_guide.GUIDE, structured={"guide": presentation_guide.GUIDE}
    )


PRESENTATION_TOOLS = {
    "publish_presentation": _publish_presentation,
    "create_presentation_page": _create_presentation_page,
    "replace_presentation": _replace_presentation,
    "list_presentations": _list_presentations,
    "presentation_guide": _presentation_guide,
}


def _initialize(_user, _claims, params):
    asked = params.get("protocolVersion")
    return {
        "protocolVersion": asked
        if asked in PROTOCOL_VERSIONS
        else PROTOCOL_VERSIONS[0],
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {
            "name": "collaborators",
            "title": "Collaborators",
            "version": "1.0",
        },
        "instructions": (
            "Collaborators is where the user's teams write pages together. "
            "You can find the pages the user can edit, and add the user's "
            "input to one of them; it appears at the end of the page, in a "
            "toggle heading with their name. You can also publish an HTML "
            "presentation in a page, or launch a new page with it at its "
            "top, ready to share, and replace it later at the same "
            "address: read presentation_guide first, and send its PDF with "
            "it. Ask which page when unsure."
        ),
    }


def _tools_call(user, claims, params):
    return _call_tool(user, claims, params.get("name"), params.get("arguments") or {})


METHODS = {
    "initialize": _initialize,
    "ping": lambda _user, _claims, _params: {},
    "tools/list": lambda _user, _claims, _params: {"tools": TOOLS},
    "tools/call": _tools_call,
}


def _handle(user, claims, message):
    """Answer one JSON-RPC message; None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, -32600, "Invalid request")
    request_id = message.get("id")
    if request_id is None:
        # notifications (initialized, cancelled…): nothing to answer
        return None
    method = METHODS.get(message.get("method"))
    if method is None:
        return _error(request_id, -32601, "Method not found")
    result = method(user, claims, message.get("params") or {})
    if result is None:
        return _error(request_id, -32602, "Unknown tool")
    return _result(request_id, result)


@csrf_exempt
@require_http_methods(["POST", "GET", "DELETE"])
def mcp_endpoint(request):
    """The MCP server: one JSON-RPC message per request, answered in JSON."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return _unauthorized()
    user, claims = person_of(header.removeprefix("Bearer ").strip())
    if user is None:
        return _unauthorized("invalid_token")
    if request.method != "POST":
        # stateless: no stream to open, no session to end
        return HttpResponse(status=405, headers={"Allow": "POST"})
    try:
        message = json.loads(request.body or b"")
    except ValueError:
        return JsonResponse(_error(None, -32700, "Parse error"), status=400)
    # When this assistant last did something for the person
    if (
        isinstance(message, dict)
        and message.get("method") == "tools/call"
        and claims.get("azp")
    ):
        models.AssistantUse.objects.update_or_create(
            user=user,
            client_id=claims["azp"],
            defaults={"last_used_at": timezone.now()},
        )
    answer = _handle(user, claims, message)
    if answer is None:
        return HttpResponse(status=202)
    return JsonResponse(answer)
