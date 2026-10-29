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
(with its PDF twin), replace it later at the same address, and read how to
make presentations for Collaborators (its guide); every file sent is
checked against the guide, and the answer says what it misses.
"""

import base64
import binascii
import json
import logging
import uuid
from functools import lru_cache

from django.conf import settings
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
    presentation_guide,
    presentations,
    registrations,
)
from core.services import keycloak
from core.services.converter_services import ServiceUnavailableError
from core.services.yhub_services import YHubError

logger = logging.getLogger(__name__)

# Newest first; an older one asked for is answered in kind
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")

TOOLS = [
    {
        "name": "find_pages",
        "title": "Find pages",
        "description": (
            "Find the Collaborators pages the user can add input to (pages "
            "they can edit), most recently changed first. Optionally filter "
            "by words of the title."
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
        pages = assistants.editable_pages(user, arguments.get("query") or "")
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
            "presentation in a page and replace it later at the same "
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
