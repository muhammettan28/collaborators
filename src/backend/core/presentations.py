"""
Collaborators: HTML presentations shown in pages, by the editor's
"presentation" block. Two ways in:

- **stored here**: an HTML file uploaded from the page, or sent by one's AI
  assistant through the MCP server (core.api.mcp). Each replacement is a new
  version, at the same address; the platform keeps the latest few (a
  platform setting) and limits what each person stores (another), counting
  every version they uploaded;
- **a link** to an HTML file hosted anywhere public (GitHub, Netlify,
  Dropbox, Google Drive shared with anyone…): nothing is stored, the file is
  fetched when the presentation is shown (kept a couple of minutes), so it is
  always the one at that address.

The page shows the HTML in a sealed frame (no access to the app, its cookies
or the network, but for script libraries, fonts and images): the file is
only ever served as text, never as a page of our own.

Whoever reads the page sees its presentations; whoever edits it adds,
replaces or removes them (and the person who uploaded a file may remove it).
A permanent address gives a PDF of the current version, made by the
presentation renderer (src/presentation-renderer), with a page after the
cover saying when it was made and where to get the current one.
"""

import hashlib
import html as html_lib
import ipaddress
import logging
import re
import socket
import uuid
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Sum
from django.utils import formats, timezone
from django.utils.translation import gettext as _

import requests

from core import models, platform_settings
from core.services.converter_services import YdocConverter
from core.services.jwt_services import Audiences, JWTService
from core.services.yhub_services import YHubService

logger = logging.getLogger(__name__)

MB = 1024 * 1024
FOLDER = "presentations"
# A linked file is kept this long once fetched (when small enough)
LINK_CACHE_SECONDS = 120
LINK_CACHE_MAX_BYTES = MB
MAX_REDIRECTS = 5
# What a linked file may be served as (hosts differ; anything else is refused)
LINK_CONTENT_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "application/octet-stream",
    "binary/octet-stream",
)


class PresentationError(Exception):
    """Something that can't be done, with why, for the person to read."""


# ---------------------------------------------------------------------------
# Rights and limits


def page_is_open(document):
    """The page is neither deleted nor below a deleted one."""
    return document.ancestors_deleted_at is None and document.deleted_at is None


def can_read(user, presentation):
    """Whoever reads the page sees its presentations."""
    document = presentation.document
    return page_is_open(document) and bool(document.get_abilities(user).get("retrieve"))


def can_edit(user, presentation):
    """Whoever edits the page changes its presentations."""
    document = presentation.document
    return page_is_open(document) and bool(document.get_abilities(user).get("update"))


def can_remove(user, presentation):
    """Editors of the page, and whoever uploaded a version of it."""
    return can_edit(user, presentation) or (
        user.is_authenticated
        and page_is_open(presentation.document)
        and presentation.versions.filter(uploaded_by=user).exists()
    )


def storage_limit():
    """What each person may store, in bytes."""
    return platform_settings.get("presentation_storage_mb") * MB


def versions_kept():
    """How many versions of each presentation are kept."""
    return max(1, platform_settings.get("presentation_versions"))


def used_storage(user):
    """What a person stores, in bytes: every version they uploaded."""
    return (
        models.PresentationVersion.objects.filter(uploaded_by=user).aggregate(
            total=Sum("size")
        )["total"]
        or 0
    )


def megabytes(size):
    """A size for people to read, e.g. "2.4 MB"."""
    return _("{size} MB").format(size=formats.number_format(size / MB, 1))


# ---------------------------------------------------------------------------
# The HTML itself

TITLE = re.compile(r"<title[^>]*>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)


def title_of(text):
    """The title an HTML file gives itself, or ""."""
    match = TITLE.search(text or "")
    if not match:
        return ""
    return " ".join(html_lib.unescape(match.group(1)).split())[:255]


def read_html(data):
    """The text of an HTML file, refused when empty or too big."""
    if isinstance(data, str):
        data = data.encode()
    if not data or not data.strip():
        raise PresentationError(_("The file is empty."))
    if len(data) > settings.COLLABORATORS_PRESENTATION_MAX_BYTES:
        raise PresentationError(
            _("A presentation can be up to {size}.").format(
                size=megabytes(settings.COLLABORATORS_PRESENTATION_MAX_BYTES)
            )
        )
    text = data.decode("utf-8", errors="replace").lstrip("﻿")
    if "<" not in text:
        raise PresentationError(_("This doesn't look like an HTML file."))
    return text


# ---------------------------------------------------------------------------
# Links to files hosted elsewhere


def normalize_link(url):
    """
    The address of the file itself, from the link people copy: a GitHub
    page of the file gives its raw file, Dropbox and OneDrive their download,
    Google Drive its download. Only https.
    """
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise PresentationError(_("The link must be a full address starting https://"))
    host = parts.hostname.lower()
    query = parse_qs(parts.query, keep_blank_values=True)

    if host in ("github.com", "www.github.com"):
        # github.com/<owner>/<repo>/blob/<branch>/<path>
        segments = parts.path.split("/")
        if len(segments) > 5 and segments[3] == "blob":
            path = "/".join(segments[1:3] + segments[4:])
            return f"https://raw.githubusercontent.com/{path}"
    if host in ("dropbox.com", "www.dropbox.com"):
        query.pop("raw", None)
        query["dl"] = ["1"]
        return urlunsplit(("https", host, parts.path, urlencode(query, doseq=True), ""))
    if host in ("drive.google.com", "docs.google.com"):
        found = re.search(r"/file/d/([\w-]+)", parts.path)
        file_id = found.group(1) if found else (query.get("id") or [""])[0]
        if file_id:
            return f"https://drive.google.com/uc?export=download&id={file_id}"
    if host in ("1drv.ms", "onedrive.live.com") and "download" not in query:
        query["download"] = ["1"]
        return urlunsplit(("https", host, parts.path, urlencode(query, doseq=True), ""))
    return urlunsplit(("https", parts.netloc, parts.path, parts.query, ""))


def _check_public(url):
    """
    Refuse an address that isn't on the public internet (the server's own
    network, its services, the cloud's metadata). The name is looked up
    here and again by the request: a host answering differently the second
    time could still reach inside, which the short timeouts limit.
    """
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise PresentationError(_("The link must be a full address starting https://"))
    try:
        found = socket.getaddrinfo(parts.hostname, parts.port or 443)
    except (socket.gaierror, UnicodeError) as err:
        raise PresentationError(_("This address can't be reached.")) from err
    for address in {info[4][0] for info in found}:
        if not ipaddress.ip_address(address.split("%")[0]).is_global:
            raise PresentationError(_("This address can't be reached."))


def _download(url):
    """The file at a public address, following its redirects."""
    limit = settings.COLLABORATORS_PRESENTATION_MAX_BYTES
    for _hop in range(MAX_REDIRECTS + 1):
        _check_public(url)
        try:
            response = requests.get(
                url,
                stream=True,
                allow_redirects=False,
                timeout=(5, 15),
                headers={"User-Agent": "Collaborators presentations"},
            )
        except requests.RequestException as err:
            raise PresentationError(_("This address can't be reached.")) from err
        with response:
            if response.is_redirect:
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            if response.status_code != 200:
                raise PresentationError(
                    _("The file can't be read there (error {status}).").format(
                        status=response.status_code
                    )
                )
            kind = response.headers.get("Content-Type", "").split(";")[0].strip()
            if kind and kind.lower() not in LINK_CONTENT_TYPES:
                raise PresentationError(_("This address doesn't give an HTML file."))
            data = b""
            for chunk in response.iter_content(64 * 1024):
                data += chunk
                if len(data) > limit:
                    raise PresentationError(
                        _("A presentation can be up to {size}.").format(
                            size=megabytes(limit)
                        )
                    )
            return data
    raise PresentationError(_("This address redirects too many times."))


def fetch_link(url, fresh=False):
    """
    The HTML of a linked presentation, kept a couple of minutes (when small)
    so a page opened by many doesn't fetch it each time.
    """
    key = f"presentation-link:{hashlib.sha256(url.encode()).hexdigest()}"
    if not fresh:
        kept = cache.get(key)
        if kept is not None:
            return kept
    text = read_html(_download(url))
    if len(text) <= LINK_CACHE_MAX_BYTES:
        cache.set(key, text, LINK_CACHE_SECONDS)
    return text


# ---------------------------------------------------------------------------
# Stored files


def _client():
    return default_storage.connection.meta.client


def _put(key, text):
    _client().put_object(
        Bucket=default_storage.bucket_name,
        Key=key,
        Body=text.encode(),
        # never served as a page: only the app reads it, as text
        ContentType="text/plain; charset=utf-8",
        ContentDisposition="attachment",
    )


def _get(key):
    response = _client().get_object(Bucket=default_storage.bucket_name, Key=key)
    return response["Body"].read().decode("utf-8", errors="replace")


def _remove(key):
    try:
        _client().delete_object(Bucket=default_storage.bucket_name, Key=key)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Presentation file %s not removed", key)


def _prune(presentation):
    """The oldest versions beyond what is kept go, with their file (never
    the one shown)."""
    kept = versions_kept()
    extra = [
        version
        for version in presentation.versions.order_by("-created_at")[kept:]
        if version.pk != presentation.current_id
    ]
    for version in extra:
        _remove(version.file_key)
        version.delete()


def store(user, presentation, text):
    """A new version of a stored presentation, shown at once."""
    size = len(text.encode())
    used = used_storage(user)
    limit = storage_limit()
    if used + size > limit:
        raise PresentationError(
            _(
                "There isn't room: this file is {size}, and you use {used} of "
                "your {limit} for presentations. Remove one you no longer need."
            ).format(size=megabytes(size), used=megabytes(used), limit=megabytes(limit))
        )
    key = f"{FOLDER}/{presentation.pk}/{uuid.uuid4()}.html"
    _put(key, text)
    with transaction.atomic():
        version = models.PresentationVersion.objects.create(
            presentation=presentation, file_key=key, size=size, uploaded_by=user
        )
        presentation.current = version
        presentation.link_url = ""
        presentation.save(update_fields=["current", "link_url", "updated_at"])
    _prune(presentation)
    return version


# ---------------------------------------------------------------------------
# What people and assistants do


def create(user, document, *, title="", html=None, link=None):
    """
    A presentation in a page the person edits: an HTML file stored here,
    a link to one hosted elsewhere, or neither yet (its file comes next,
    with a one-time upload address).
    """
    if not page_is_open(document) or not document.get_abilities(user).get("update"):
        raise PresentationError(_("You can't edit this page."))
    if html is not None and link:
        raise PresentationError(_("Give a file or a link, not both."))
    text = read_html(html) if html is not None else None
    url = normalize_link(link) if link else ""
    if url:
        text = fetch_link(url, fresh=True)
    presentation = models.Presentation.objects.create(
        document=document,
        title=((title or "").strip() or title_of(text or ""))[:255],
        link_url=url,
        created_by=user,
    )
    if url == "" and text is not None:
        try:
            store(user, presentation, text)
        except PresentationError:
            presentation.delete()
            raise
    return presentation


def replace(user, presentation, *, html=None, link=None, title=None):
    """
    A new version at the same address: another file (stored), or another
    link; a new title, or the new file's own.
    """
    if html is not None and link:
        raise PresentationError(_("Give a file or a link, not both."))
    text = None
    if html is not None:
        text = read_html(html)
        store(user, presentation, text)
    elif link:
        url = normalize_link(link)
        text = fetch_link(url, fresh=True)
        presentation.link_url = url
        presentation.current = None
    if title is not None or text is not None:
        presentation.title = (
            (title or "").strip() or title_of(text or "") or presentation.title
        )[:255]
    presentation.save()
    return presentation


def restore(presentation, version_id):
    """Show an earlier stored version again (it becomes the current one)."""
    version = presentation.versions.filter(pk=version_id).first()
    if version is None:
        raise PresentationError(_("This version no longer exists."))
    presentation.current = version
    presentation.link_url = ""
    presentation.save(update_fields=["current", "link_url", "updated_at"])
    return presentation


def remove(presentation):
    """The presentation goes, with every stored file of it."""
    for version in presentation.versions.all():
        _remove(version.file_key)
    presentation.delete()


def html_of(presentation):
    """The HTML shown now: the current stored version, or the linked file."""
    if presentation.link_url:
        return fetch_link(presentation.link_url)
    if presentation.current is None:
        raise PresentationError(_("This presentation has no file yet."))
    return _get(presentation.current.file_key)


def add_to_page(user, presentation):
    """
    Its block at the end of its page (before the editor's empty last line),
    credited to the person in the page's history, live for everyone there.
    """
    document = presentation.document
    current = YHubService().get_ydoc(document)
    update = YdocConverter().append_blocks(
        current,
        [
            {
                "type": "presentation",
                "props": {
                    "presentationId": str(presentation.pk),
                    "title": presentation.title,
                },
            }
        ],
    )
    YHubService(user=user).append_ydoc(document, update)


# One-time upload addresses: an assistant sending a big file (a Claude Design
# export with its pictures inside) uploads it there instead of writing it
# into its message, e.g. `curl -F file=@deck.html <address>`
UPLOAD_SALT = "collaborators.presentation-upload"
UPLOAD_SECONDS = 15 * 60


def upload_address(user, presentation):
    """An address taking one file for this presentation, for 15 minutes."""
    nonce = uuid.uuid4().hex
    cache.set(f"presentation-upload:{nonce}", 1, UPLOAD_SECONDS)
    token = signing.dumps(
        {"p": str(presentation.pk), "u": str(user.pk), "n": nonce},
        salt=UPLOAD_SALT,
        compress=True,
    )
    return f"{app_url()}/api/v1.0/presentations/upload/{token}/"


def use_upload_address(token):
    """The presentation and person an upload address is for; once only."""
    try:
        data = signing.loads(token, salt=UPLOAD_SALT, max_age=UPLOAD_SECONDS)
    except signing.BadSignature as err:
        raise PresentationError(
            _("This upload address is wrong or has expired.")
        ) from err
    key = f"presentation-upload:{data.get('n')}"
    if not cache.get(key):
        raise PresentationError(_("This upload address was already used."))
    cache.delete(key)
    presentation = models.Presentation.objects.filter(pk=data.get("p")).first()
    user = models.User.objects.filter(pk=data.get("u"), is_active=True).first()
    if presentation is None or user is None or not can_edit(user, presentation):
        raise PresentationError(_("This presentation can't be changed."))
    return presentation, user


# ---------------------------------------------------------------------------
# Addresses


def app_url():
    """The app's address, without a final slash."""
    return (settings.EMAIL_URL_APP or "").rstrip("/")


def view_url(presentation):
    """Where the presentation is shown on its own, full screen."""
    return f"{app_url()}/presentation/{presentation.pk}/"


def pdf_url(presentation):
    """The permanent address of its PDF, always of the current version."""
    return f"{app_url()}/api/v1.0/presentations/{presentation.pk}/pdf/"


def page_url(document):
    """Where a page is read."""
    return f"{app_url()}/page/{document.pk}/"


def describe(presentation, user):
    """What the block and the assistants are told of a presentation."""
    current = presentation.current
    return {
        "id": str(presentation.pk),
        "title": presentation.title,
        "source": "link" if presentation.link_url else "file",
        "link": presentation.link_url,
        "page": {
            "id": str(presentation.document_id),
            "title": presentation.document.title,
        },
        "size": current.size if current and not presentation.link_url else None,
        "has_content": bool(presentation.link_url or current),
        "updated_at": presentation.updated_at.isoformat(),
        "view_url": view_url(presentation),
        "pdf_url": pdf_url(presentation),
        "abilities": {
            "edit": can_edit(user, presentation),
            "remove": can_remove(user, presentation),
        },
    }


# ---------------------------------------------------------------------------
# The PDF


def _zone(name):
    try:
        return ZoneInfo(name) if name else None
    except ZoneInfoNotFoundError, ValueError:
        return None


def notice(presentation, when=None, zone_name=""):
    """
    The page after the cover, in the reader's language (active): when the
    file was made, that the presentation is live, and where to get it again.
    """
    zone = _zone(zone_name)
    moment = timezone.localtime(when or timezone.now(), zone)
    date = formats.date_format(moment, "DATETIME_FORMAT")
    zone_label = zone_name if zone else "UTC"
    document = presentation.document
    return {
        "lines": [
            {"text": presentation.title or _("Presentation"), "bold": True},
            {
                "text": _("Downloaded on {date} ({zone}).").format(
                    date=date, zone=zone_label
                )
            },
            {
                "text": _(
                    "This presentation is live: its authors may have changed "
                    "it since this file was made."
                )
            },
            {
                "text": _(
                    "To read its current version, download it again from the "
                    "address below. The new file will carry the date of that day."
                )
            },
        ],
        "url": pdf_url(presentation),
        "footer": _("Shown in the page “{title}” on Collaborators: {url}").format(
            title=document.title or _("Untitled page"), url=page_url(document)
        ),
    }


def file_name(presentation, when=None):
    """ "<title> <date>.pdf", safe for any system."""
    day = timezone.localdate(when or timezone.now())
    title = " ".join(
        re.sub(r"[^\w\s.-]", "", presentation.title or "presentation").split()
    )
    return f"{title[:80] or 'presentation'} {day.isoformat()}.pdf"


def render_pdf(presentation, zone_name=""):
    """The PDF of the current version, with the dated page after the cover."""
    if not settings.PRESENTATION_RENDERER_URL:
        raise PresentationError(_("PDFs of presentations aren't available here."))
    text = html_of(presentation)
    token = JWTService().get_admin_token(audience=Audiences.PRESENTATION_RENDERER)
    try:
        response = requests.post(
            f"{settings.PRESENTATION_RENDERER_URL.rstrip('/')}/render",
            json={
                "html": text,
                "baseUrl": presentation.link_url or None,
                "notice": notice(presentation, zone_name=zone_name),
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.PRESENTATION_RENDERER_TIMEOUT,
        )
    except requests.RequestException as err:
        logger.exception("Presentation renderer unreachable")
        raise PresentationError(_("The PDF can't be made right now.")) from err
    if response.status_code == 503:
        raise PresentationError(_("Many PDFs are being made; try again in a minute."))
    if not response.ok:
        logger.error(
            "Presentation renderer error %s: %s",
            response.status_code,
            response.text[:200],
        )
        raise PresentationError(_("The PDF can't be made right now."))
    return response.content
