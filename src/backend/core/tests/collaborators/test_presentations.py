"""
Collaborators: HTML presentations shown in pages (core.presentations,
core.api.presentations), stored here within each person's limit or linked
from elsewhere, their PDFs, and the AI assistants' tools for them.
"""

import json
import socket
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile

import pytest
import requests
from rest_framework.test import APIClient

from core import (
    factories,
    models,
    platform_settings,
    presentation_guide,
    presentations,
    reports,
)
from core.services.converter_services import ServiceUnavailableError
from core.tests.collaborators.test_assistants import (  # pylint: disable=unused-import
    _rpc,
    _token,
    fixture_mcp_settings,
)

pytestmark = pytest.mark.django_db

API = "/api/v1.0/presentations/"
DECK = "<!doctype html><html><head><title>Q4 &amp; beyond</title></head><body>1</body></html>"


class FakeStorage:
    """The object storage's client, in memory."""

    def __init__(self):
        self.files = {}

    def put_object(self, Bucket, Key, Body, **kwargs):  # pylint: disable=invalid-name,unused-argument
        """Kept with its headers."""
        self.files[Key] = (Body, kwargs)

    def get_object(self, Bucket, Key):  # pylint: disable=invalid-name,unused-argument
        """Read back."""
        body = mock.Mock()
        body.read.return_value = self.files[Key][0]
        return {"Body": body}

    def delete_object(self, Bucket, Key):  # pylint: disable=invalid-name,unused-argument
        """Gone."""
        self.files.pop(Key, None)


@pytest.fixture(autouse=True, name="storage")
def fixture_storage(settings):
    """Files in memory; the app's address; a renderer to call."""
    settings.EMAIL_URL_APP = "https://app.example.org"
    settings.PRESENTATION_RENDERER_URL = "http://renderer:3010"
    settings.COLLABORATORS_PRESENTATION_STORAGE_MB = 25
    settings.COLLABORATORS_PRESENTATION_VERSIONS = 5
    fake = FakeStorage()
    with mock.patch.object(presentations, "_client", return_value=fake):
        yield fake


def _client(user=None):
    client = APIClient()
    if user:
        client.force_login(user)
    return client


def _upload(client, document, html=DECK, title=""):
    return client.post(
        API,
        {
            "document": str(document.pk),
            "title": title,
            "file": SimpleUploadedFile("deck.html", html.encode(), "text/html"),
        },
        format="multipart",
    )


def _public_address(*_args, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 443))]


def _response(status=200, body=b"", headers=None):
    response = mock.MagicMock()
    response.status_code = status
    response.is_redirect = status in (301, 302, 303, 307, 308)
    response.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
    response.iter_content.return_value = [body]
    response.__enter__.return_value = response
    return response


# ---------------------------------------------------------------------------
# Stored here


def test_an_editor_uploads_a_presentation_and_readers_see_it_as_text(storage):
    """Its title from the file; served as text in a sandbox, never as a page."""
    editor = factories.UserFactory()
    reader = factories.UserFactory()
    page = factories.DocumentFactory(
        link_reach="restricted", users=[(editor, "editor"), (reader, "reader")]
    )

    response = _upload(_client(editor), page)

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Q4 & beyond"
    assert body["source"] == "file"
    assert body["size"] == len(DECK.encode())
    assert body["view_url"] == f"https://app.example.org/presentation/{body['id']}/"
    assert body["pdf_url"] == (
        f"https://app.example.org/api/v1.0/presentations/{body['id']}/pdf/"
    )
    (key,) = storage.files
    assert key.startswith(f"presentations/{body['id']}/")
    assert storage.files[key][1]["ContentType"] == "text/plain; charset=utf-8"

    content = _client(reader).get(f"{API}{body['id']}/content/")
    assert content.status_code == 200
    assert content["Content-Type"] == "text/plain; charset=utf-8"
    assert "sandbox" in content["Content-Security-Policy"]
    assert content.content.decode() == DECK
    assert _client(reader).get(f"{API}{body['id']}/").json()["abilities"] == {
        "edit": False,
        "remove": False,
    }


def test_only_editors_add_and_only_readers_see():
    """Readers can't add; strangers and anonymous visitors see nothing."""
    reader = factories.UserFactory()
    page = factories.DocumentFactory(
        link_reach="restricted", users=[(reader, "reader")]
    )
    assert _upload(_client(reader), page).status_code == 400
    editor = factories.UserFactory()
    models.DocumentAccess.objects.create(document=page, user=editor, role="editor")
    presentation = presentations.create(editor, page, html=DECK)

    assert (
        _client(factories.UserFactory()).get(f"{API}{presentation.pk}/").status_code
        == 404
    )
    assert _client().get(f"{API}{presentation.pk}/content/").status_code == 404


def test_a_public_page_shows_its_presentation_to_anyone():
    """Signed out too, and its PDF."""
    editor = factories.UserFactory()
    page = factories.DocumentFactory(
        link_reach="public", link_role="reader", users=[(editor, "editor")]
    )
    presentation = presentations.create(editor, page, html=DECK)

    assert _client().get(f"{API}{presentation.pk}/content/").status_code == 200
    assert _client().get(f"{API}?document={page.pk}").json()[0]["id"] == str(
        presentation.pk
    )


def test_replacing_keeps_the_address_and_old_versions_go(storage, settings):
    """Same id; the latest few kept (the shown one always), files removed."""
    settings.COLLABORATORS_PRESENTATION_VERSIONS = 2
    editor = factories.UserFactory()
    page = factories.DocumentFactory(users=[(editor, "editor")])
    created = _upload(_client(editor), page).json()

    for number in (2, 3):
        response = _client(editor).post(
            f"{API}{created['id']}/file/",
            {"file": SimpleUploadedFile("d.html", f"<p>{number}</p>".encode())},
            format="multipart",
        )
        assert response.status_code == 200
        assert response.json()["view_url"] == created["view_url"]

    presentation = models.Presentation.objects.get()
    assert presentation.versions.count() == 2
    assert len(storage.files) == 2
    assert presentations.html_of(presentation) == "<p>3</p>"
    assert presentation.title == "Q4 & beyond"  # files without a title keep it

    older = presentation.versions.order_by("created_at").first()
    restored = _client(editor).post(
        f"{API}{presentation.pk}/versions/{older.pk}/restore/"
    )
    assert restored.status_code == 200
    assert presentations.html_of(models.Presentation.objects.get()) == "<p>2</p>"
    versions = _client(editor).get(f"{API}{presentation.pk}/versions/").json()
    assert [version["current"] for version in versions] == [False, True]


def test_each_person_stores_up_to_their_limit(settings):
    """Every version one uploaded counts; a platform setting changes it."""
    settings.COLLABORATORS_PRESENTATION_STORAGE_MB = 1
    editor = factories.UserFactory()
    page = factories.DocumentFactory(users=[(editor, "editor")])
    big = "<p>" + "x" * (700 * 1024) + "</p>"

    assert _upload(_client(editor), page, big).status_code == 201
    refused = _upload(_client(editor), page, big)
    assert refused.status_code == 400
    assert "There isn't room" in refused.json()["detail"]
    assert models.Presentation.objects.count() == 1

    platform_settings.update(
        {"presentation_storage_mb": 2}, factories.UserFactory(is_superuser=True)
    )
    assert _upload(_client(editor), page, big).status_code == 201

    storage = _client(editor).get(f"{API}storage/").json()
    assert storage["limit"] == 2 * 1024 * 1024
    assert storage["used"] == 2 * len(big)
    assert len(storage["presentations"]) == 2


def test_too_big_or_empty_files_are_refused(settings):
    """Whatever the limit left."""
    settings.COLLABORATORS_PRESENTATION_MAX_BYTES = 1000
    editor = factories.UserFactory()
    page = factories.DocumentFactory(users=[(editor, "editor")])
    assert _upload(_client(editor), page, "<p>" + "x" * 2000).status_code == 400
    assert _upload(_client(editor), page, "   ").status_code == 400
    assert _upload(_client(editor), page, "no tags at all").status_code == 400


def test_removing_frees_the_storage(storage):
    """Editors of the page, or whoever uploaded it, even without edit rights."""
    uploader = factories.UserFactory()
    page = factories.DocumentFactory(
        link_reach="restricted", users=[(uploader, "editor")]
    )
    presentation = presentations.create(uploader, page, html=DECK)
    models.DocumentAccess.objects.filter(user=uploader).update(role="reader")
    reader = factories.UserFactory()
    models.DocumentAccess.objects.create(document=page, user=reader, role="reader")

    assert _client(reader).delete(f"{API}{presentation.pk}/").status_code == 403
    assert _client(uploader).delete(f"{API}{presentation.pk}/").status_code == 204
    assert not models.Presentation.objects.exists()
    assert storage.files == {}
    assert presentations.used_storage(uploader) == 0


# ---------------------------------------------------------------------------
# Linked from elsewhere


@pytest.mark.parametrize(
    "link, address",
    [
        (
            "https://github.com/ada/decks/blob/main/q4/deck.html",
            "https://raw.githubusercontent.com/ada/decks/main/q4/deck.html",
        ),
        (
            "https://www.dropbox.com/scl/fi/abc/deck.html?rlkey=k&dl=0",
            "https://www.dropbox.com/scl/fi/abc/deck.html?rlkey=k&dl=1",
        ),
        (
            "https://drive.google.com/file/d/1AbC-d_9/view?usp=sharing",
            "https://drive.google.com/uc?export=download&id=1AbC-d_9",
        ),
        (
            "https://1drv.ms/u/c/abc/XYZ?e=Q",
            "https://1drv.ms/u/c/abc/XYZ?e=Q&download=1",
        ),
        ("https://ada.example.org/deck.html#2", "https://ada.example.org/deck.html"),
    ],
)
def test_links_people_copy_lead_to_the_file_itself(link, address):
    """GitHub, Dropbox, Google Drive and OneDrive share links."""
    assert presentations.normalize_link(link) == address


def test_only_https_links():
    """Plain http, other schemes and bare words are refused."""
    for link in ("http://example.org/d.html", "file:///etc/passwd", "deck.html"):
        with pytest.raises(presentations.PresentationError):
            presentations.normalize_link(link)


@mock.patch.object(socket, "getaddrinfo", _public_address)
def test_a_linked_presentation_is_fetched_and_kept_briefly():
    """Its title from the file; fetched once for a while."""
    editor = factories.UserFactory()
    page = factories.DocumentFactory(users=[(editor, "editor")])
    with mock.patch.object(
        requests, "get", return_value=_response(body=DECK.encode())
    ) as get:
        response = _client(editor).post(
            API,
            {"document": str(page.pk), "link": "https://ada.example.org/deck.html"},
            format="json",
        )
        assert response.status_code == 201
        assert response.json()["source"] == "link"
        assert response.json()["title"] == "Q4 & beyond"
        content = _client(editor).get(f"{API}{response.json()['id']}/content/")
        assert content.content.decode() == DECK
        assert get.call_count == 1
    assert presentations.used_storage(editor) == 0


@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1"])
def test_links_into_the_servers_network_are_refused(address):
    """Loopback, private, link-local: never fetched."""
    found = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
    with (
        mock.patch.object(socket, "getaddrinfo", return_value=found),
        mock.patch.object(requests, "get") as get,
        pytest.raises(presentations.PresentationError),
    ):
        presentations.fetch_link("https://inside.example.org/deck.html", fresh=True)
    get.assert_not_called()


@mock.patch.object(socket, "getaddrinfo")
def test_a_redirect_into_the_servers_network_is_refused(getaddrinfo):
    """Each address on the way is checked."""
    getaddrinfo.side_effect = lambda host, _port: (
        _public_address()
        if host == "ada.example.org"
        else [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))]
    )
    redirect = _response(302, headers={"Location": "https://minio.internal/x"})
    with (
        mock.patch.object(requests, "get", return_value=redirect) as get,
        pytest.raises(presentations.PresentationError),
    ):
        presentations.fetch_link("https://ada.example.org/deck.html", fresh=True)
    assert get.call_count == 1


@mock.patch.object(socket, "getaddrinfo", _public_address)
def test_linked_files_that_arent_html_or_are_too_big_are_refused(settings):
    """An image, a PDF; more than the limit."""
    image = _response(body=b"\x89PNG", headers={"Content-Type": "image/png"})
    with mock.patch.object(requests, "get", return_value=image):
        with pytest.raises(presentations.PresentationError):
            presentations.fetch_link("https://ada.example.org/a.png", fresh=True)
    settings.COLLABORATORS_PRESENTATION_MAX_BYTES = 10
    with mock.patch.object(requests, "get", return_value=_response(body=DECK.encode())):
        with pytest.raises(presentations.PresentationError):
            presentations.fetch_link("https://ada.example.org/d.html", fresh=True)


# ---------------------------------------------------------------------------
# The PDF


def test_the_pdf_is_made_by_the_renderer_with_the_dated_page():
    """The reader's zone; the permanent address again; a dated file name."""
    editor = factories.UserFactory()
    page = factories.DocumentFactory(
        title="Q4 Launch",
        link_reach="public",
        link_role="reader",
        users=[(editor, "editor")],
    )
    presentation = presentations.create(editor, page, html=DECK)
    made = mock.Mock(status_code=200, ok=True, content=b"%PDF-1.7 ...")

    with mock.patch.object(requests, "post", return_value=made) as post:
        response = _client().get(f"{API}{presentation.pk}/pdf/?tz=Europe/Istanbul")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert "Q4%20beyond%20" in response["Content-Disposition"]
    assert response.content == b"%PDF-1.7 ..."
    (url,) = post.call_args.args
    assert url == "http://renderer:3010/render"
    sent = post.call_args.kwargs["json"]
    assert sent["html"] == DECK
    assert sent["baseUrl"] is None
    notice = sent["notice"]
    assert notice["url"] == presentations.pdf_url(presentation)
    assert notice["lines"][0] == {"text": "Q4 & beyond", "bold": True}
    assert "(Europe/Istanbul)" in notice["lines"][1]["text"]
    assert "Q4 Launch" in notice["footer"]
    assert post.call_args.kwargs["headers"]["Authorization"].startswith("Bearer ")


def test_without_a_renderer_the_pdf_says_so(settings):
    """A clear message, not an error page."""
    settings.PRESENTATION_RENDERER_URL = ""
    editor = factories.UserFactory()
    page = factories.DocumentFactory(users=[(editor, "editor")])
    presentation = presentations.create(editor, page, html=DECK)
    response = _client(editor).get(f"{API}{presentation.pk}/pdf/")
    assert response.status_code == 503
    assert "aren't available" in response.content.decode()


def test_an_unknown_zone_falls_back_to_utc():
    """Whatever ?tz= says."""
    editor = factories.UserFactory()
    page = factories.DocumentFactory(users=[(editor, "editor")])
    presentation = presentations.create(editor, page, html=DECK)
    lines = presentations.notice(presentation, zone_name="Mars/Base")["lines"]
    assert "(UTC)" in lines[1]["text"]


# ---------------------------------------------------------------------------
# One-time upload addresses


def test_an_upload_address_takes_one_file_once(storage):
    """Credited to whoever got it; then used up."""
    editor = factories.UserFactory()
    page = factories.DocumentFactory(users=[(editor, "editor")])
    presentation = presentations.create(editor, page)
    address = presentations.upload_address(editor, presentation)
    path = address.removeprefix("https://app.example.org")

    def send():
        return APIClient().post(
            path,
            {"file": SimpleUploadedFile("deck.html", DECK.encode())},
            format="multipart",
        )

    assert APIClient().post(path, {}, format="multipart").status_code == 400
    assert send().status_code == 200
    presentation.refresh_from_db()
    assert presentation.current.uploaded_by == editor
    assert presentation.title == "Q4 & beyond"
    assert send().status_code == 400
    assert APIClient().post(f"{API}upload/forged/", {}).status_code == 400
    assert len(storage.files) == 1


# ---------------------------------------------------------------------------
# AI assistants (MCP)


def _call(user, name, arguments):
    response = _rpc(
        _token(user.email),
        "tools/call",
        {"name": name, "arguments": arguments},
    )
    return response.json()["result"]


@pytest.fixture(name="page_update")
def fixture_page_update():
    """The page's state and its update, without the collaboration server."""
    with (
        mock.patch("core.presentations.YHubService.get_ydoc", return_value=b"state"),
        mock.patch("core.presentations.YHubService.append_ydoc") as append,
        mock.patch(
            "core.presentations.YdocConverter.append_blocks", return_value=b"upd"
        ) as build,
    ):
        yield build, append


def test_an_assistant_publishes_a_presentation_at_the_end_of_a_page(page_update):
    """Its block added; its addresses told."""
    build, append = page_update
    user = factories.UserFactory(email="ada@example.org")
    page = factories.DocumentFactory(title="Q4 Launch", users=[(user, "editor")])

    tools = _rpc(_token(user.email), "tools/list").json()["result"]["tools"]
    assert {"publish_presentation", "replace_presentation", "list_presentations"} <= {
        tool["name"] for tool in tools
    }

    result = _call(
        user, "publish_presentation", {"page_id": str(page.pk), "html": DECK}
    )

    assert not result.get("isError")
    presentation = models.Presentation.objects.get()
    assert presentation.document == page
    assert presentation.current.uploaded_by == user
    blocks = build.call_args.args[1]
    assert blocks == [
        {
            "type": "presentation",
            "props": {"presentationId": str(presentation.pk), "title": "Q4 & beyond"},
        }
    ]
    append.assert_called_once()
    shown = result["structuredContent"]["presentation"]
    assert shown["pdf_url"] == presentations.pdf_url(presentation)
    assert "upload_url" not in shown


@pytest.mark.usefixtures("page_update")
def test_an_assistant_uploads_a_big_file_later_and_replaces_it():
    """An upload address to curl to; then a replacement at the same address."""
    user = factories.UserFactory(email="ada@example.org")
    page = factories.DocumentFactory(users=[(user, "editor")])

    result = _call(
        user, "publish_presentation", {"page_id": str(page.pk), "upload_later": True}
    )
    shown = result["structuredContent"]["presentation"]
    assert "/api/v1.0/presentations/upload/" in shown["upload_url"]
    assert "curl -F file=@" in result["content"][0]["text"]

    replaced = _call(
        user,
        "replace_presentation",
        {"presentation_id": shown["id"], "html": "<p>v2</p>", "title": "Q4"},
    )
    assert not replaced.get("isError")
    presentation = models.Presentation.objects.get()
    assert presentation.title == "Q4"
    assert presentations.html_of(presentation) == "<p>v2</p>"

    listed = _call(user, "list_presentations", {})
    assert [found["id"] for found in listed["structuredContent"]["presentations"]] == [
        shown["id"]
    ]


@pytest.mark.usefixtures("page_update")
def test_an_assistant_cant_publish_where_one_only_reads():
    """The page's rights apply; one way in at a time."""
    user = factories.UserFactory(email="ada@example.org")
    read_only = factories.DocumentFactory(
        link_reach="restricted", users=[(user, "reader")]
    )
    editable = factories.DocumentFactory(users=[(user, "editor")])

    refused = _call(
        user, "publish_presentation", {"page_id": str(read_only.pk), "html": DECK}
    )
    assert refused["isError"]
    both = _call(
        user,
        "publish_presentation",
        {"page_id": str(editable.pk), "html": DECK, "link": "https://a.example/d"},
    )
    assert both["isError"]
    assert not models.Presentation.objects.exists()


def test_a_presentation_that_cant_be_placed_is_not_kept(page_update):
    """The converter down: the tool says so and keeps nothing half done."""
    build, _append = page_update
    build.side_effect = ServiceUnavailableError("down")
    user = factories.UserFactory(email="ada@example.org")
    page = factories.DocumentFactory(users=[(user, "editor")])
    result = _call(
        user, "publish_presentation", {"page_id": str(page.pk), "html": DECK}
    )
    assert result["isError"]
    assert not models.Presentation.objects.exists()


# ---------------------------------------------------------------------------
# Platform settings and reports


def test_the_two_presentation_settings_are_numbers():
    """Whole numbers within bounds, or null."""
    owner = factories.UserFactory(is_superuser=True)
    client = _client(owner)
    url = "/api/v1.0/platform/settings/"
    assert client.get(url).json()["presentation_storage_mb"] == {
        "value": 25,
        "server_default": 25,
        "set_here": False,
    }
    assert (
        client.patch(url, {"presentation_versions": 3}, format="json").status_code
        == 200
    )
    for wrong in (True, "3", 0, 101):
        response = client.patch(url, {"presentation_versions": wrong}, format="json")
        assert response.status_code == 400
    assert presentations.versions_kept() == 3


def test_a_report_lists_the_pages_presentations():
    """Their titles and addresses, which the page's text doesn't show."""
    editor = factories.UserFactory()
    page = factories.DocumentFactory(users=[(editor, "editor")])
    presentation = presentations.create(editor, page, html=DECK)
    with mock.patch.object(reports.YHubService, "get_ydoc", return_value=b""):
        text = reports.page_text(page)
    assert text == f"Presentation “Q4 & beyond”: {presentations.view_url(presentation)}"
    assert json.dumps(text)


# ---------------------------------------------------------------------------
# PDF twins: made with the HTML, sent and replaced with it

PDF = b"%PDF-1.7\n% twin\n"
GOOD_DECK = (
    "<!doctype html><html><head><title>Q4</title>"
    "<style>@page { size: 1280px 720px; margin: 0 }</style>"
    '<script type="application/json" id="collaborators-presentation">'
    '{"kind": "slides", "slides": 3}</script></head><body>1</body></html>'
)


@pytest.fixture(name="pages")
def fixture_pages():
    """The renderer counting a PDF's pages."""
    with mock.patch.object(presentations, "pdf_pages", return_value=3) as pages:
        yield pages


def _pair(client, document, html=GOOD_DECK, pdf=PDF):
    return client.post(
        API,
        {
            "document": str(document.pk),
            "file": SimpleUploadedFile("deck.html", html.encode(), "text/html"),
            "pdf": SimpleUploadedFile("deck.pdf", pdf, "application/pdf"),
        },
        format="multipart",
    )


@pytest.mark.usefixtures("pages")
def test_a_presentation_and_its_pdf_go_together(storage):
    """Stored side by side, counted, shown page by page, given as its PDF."""
    editor = factories.UserFactory()
    page = factories.DocumentFactory(
        link_reach="public", link_role="reader", users=[(editor, "editor")]
    )

    response = _pair(_client(editor), page)

    assert response.status_code == 201
    body = response.json()
    assert body["pdf"] == {
        "state": "current",
        "source": "file",
        "link": "",
        "pages": 3,
        "size": len(PDF),
        "slides_url": (
            f"https://app.example.org/api/v1.0/presentations/{body['id']}/slides/"
        ),
    }
    pdf_key = next(key for key in storage.files if key.endswith(".pdf"))
    assert storage.files[pdf_key][1]["ContentType"] == "application/pdf"
    assert presentations.used_storage(editor) == len(GOOD_DECK) + len(PDF)

    slides = _client().get(f"{API}{body['id']}/slides/")
    assert slides.status_code == 200
    assert slides["Content-Type"] == "application/pdf"
    assert "sandbox" in slides["Content-Security-Policy"]
    assert slides.content == PDF

    # Export to PDF: the twin with the dated page, no photographing
    made = mock.Mock(status_code=200, ok=True, content=b"%PDF-1.7 noticed")
    with mock.patch.object(requests, "post", return_value=made) as post:
        exported = _client().get(f"{API}{body['id']}/pdf/?tz=Europe/Istanbul")
    assert exported.content == b"%PDF-1.7 noticed"
    (url,) = post.call_args.args
    assert url == "http://renderer:3010/notice"
    sent = post.call_args.kwargs["json"]
    assert sent["pdf"] == "JVBERi0xLjcKJSB0d2luCg=="
    assert "(Europe/Istanbul)" in sent["notice"]["lines"][1]["text"]


@pytest.mark.usefixtures("pages")
def test_a_new_file_without_its_pdf_leaves_it_out_of_date(storage):
    """Then photographed again; the earlier pair comes back together."""
    editor = factories.UserFactory()
    page = factories.DocumentFactory(users=[(editor, "editor")])
    first = _pair(_client(editor), page).json()
    first_version = models.Presentation.objects.get().current_id

    replaced = _client(editor).post(
        f"{API}{first['id']}/file/",
        {"file": SimpleUploadedFile("deck.html", b"<p>v2</p>")},
        format="multipart",
    )

    assert replaced.json()["pdf"]["state"] == "outdated"
    assert _client(editor).get(f"{API}{first['id']}/slides/").status_code == 404
    made = mock.Mock(status_code=200, ok=True, content=b"%PDF-1.7 photographed")
    with mock.patch.object(requests, "post", return_value=made) as post:
        _client(editor).get(f"{API}{first['id']}/pdf/")
    assert post.call_args.args == ("http://renderer:3010/render",)

    versions = _client(editor).get(f"{API}{first['id']}/versions/").json()
    assert [version["has_pdf"] for version in versions] == [False, True]
    restored = (
        _client(editor)
        .post(f"{API}{first['id']}/versions/{first_version}/restore/")
        .json()
    )
    assert restored["pdf"]["state"] == "current"

    # removing it removes every file of it
    _client(editor).delete(f"{API}{first['id']}/")
    assert not storage.files


@pytest.mark.usefixtures("pages")
def test_editors_add_replace_and_remove_the_pdf_of_what_it_shows(storage):
    """Readers can't; a new one takes the place of the old one."""
    editor = factories.UserFactory()
    reader = factories.UserFactory()
    page = factories.DocumentFactory(
        link_reach="restricted", users=[(editor, "editor"), (reader, "reader")]
    )
    presentation = presentations.create(editor, page, html=GOOD_DECK)
    address = f"{API}{presentation.pk}/pdf-file/"

    def send(user):
        return _client(user).post(
            address,
            {"file": SimpleUploadedFile("deck.pdf", PDF, "application/pdf")},
            format="multipart",
        )

    assert describe_state(editor, presentation) == "none"
    assert send(reader).status_code == 403
    assert send(editor).json()["pdf"]["state"] == "current"
    assert send(editor).status_code == 200
    assert models.PresentationPdf.objects.count() == 1
    assert len([key for key in storage.files if key.endswith(".pdf")]) == 1

    assert _client(editor).post(address, {}, format="multipart").status_code == 400
    assert _client(editor).delete(address).json()["pdf"]["state"] == "none"
    assert not [key for key in storage.files if key.endswith(".pdf")]


def describe_state(user, presentation):
    """How its PDF twin stands, as the block is told."""
    presentation.refresh_from_db()
    return presentations.describe(presentation, user)["pdf"]["state"]


def test_pdfs_that_arent_or_cant_be_opened_are_refused(settings):
    """Not a PDF, too big, or one the renderer can't open."""
    settings.COLLABORATORS_PRESENTATION_PDF_MAX_BYTES = 30
    with pytest.raises(presentations.PresentationError, match="look like a PDF"):
        presentations.prepare_pdf(data=b"<html>")
    with pytest.raises(presentations.PresentationError, match="up to"):
        presentations.prepare_pdf(data=PDF + b"x" * 40)
    locked = mock.Mock(status_code=422, ok=False)
    with mock.patch.object(requests, "post", return_value=locked):
        with pytest.raises(presentations.PresentationError, match="can't be opened"):
            presentations.prepare_pdf(data=PDF)
    counted = mock.Mock(status_code=200, ok=True, content=b'{"pages": 7}')
    with mock.patch.object(requests, "post", return_value=counted) as post:
        assert presentations.prepare_pdf(data=PDF).pages == 7
    assert post.call_args.args == ("http://renderer:3010/inspect",)


def test_a_pdf_that_doesnt_fit_leaves_nothing_stored(storage, settings, pages):
    """The pair is checked before anything is kept."""
    settings.COLLABORATORS_PRESENTATION_STORAGE_MB = 0
    editor = factories.UserFactory()
    page = factories.DocumentFactory(users=[(editor, "editor")])
    response = _pair(_client(editor), page)
    assert response.status_code == 400
    assert "There isn't room" in response.json()["detail"]
    assert not storage.files
    assert not models.Presentation.objects.exists()
    pages.assert_called_once()


@mock.patch.object(socket, "getaddrinfo", _public_address)
@pytest.mark.usefixtures("pages")
def test_a_linked_presentations_pdf_is_out_of_date_once_its_file_changes():
    """The fingerprint of the file it was made for, against the one seen."""
    editor = factories.UserFactory()
    page = factories.DocumentFactory(users=[(editor, "editor")])

    def answer(url, **_kwargs):
        if url.endswith(".pdf"):
            return _response(body=PDF, headers={"Content-Type": "application/pdf"})
        return _response(body=deck.encode())

    deck = GOOD_DECK
    with mock.patch.object(requests, "get", side_effect=answer):
        presentation = presentations.create(
            editor,
            page,
            link="https://example.org/deck.html",
            pdf=presentations.prepare_pdf(link="https://example.org/deck.pdf"),
        )
        assert describe_state(editor, presentation) == "current"
        assert presentations.pdf_data(presentation.pdfs.get()) == PDF
        # nothing stored: nothing counted
        assert presentations.used_storage(editor) == 0

        deck = GOOD_DECK.replace("<body>1", "<body>2")
        presentations.cache.clear()
        presentations.html_of(presentation)
        assert describe_state(editor, presentation) == "outdated"

        # another link: the PDF made for the old one goes
        presentations.replace(editor, presentation, link="https://example.org/b.html")
        assert describe_state(editor, presentation) == "none"
        assert not presentation.pdfs.exists()


def test_checks_say_what_a_file_misses_of_the_guide():
    """For the AI to fix: card, print rules, time handle, PDF."""
    assert not presentation_guide.checks(GOOD_DECK, pdf_pages_count=3, has_pdf=True)
    found = presentation_guide.checks(DECK)
    assert any("no presentation card" in check for check in found)
    assert any("no print rules" in check for check in found)
    assert any("No PDF came with it" in check for check in found)
    assert any(
        "says 3 slides but its PDF has 5 pages" in check
        for check in presentation_guide.checks(
            GOOD_DECK, pdf_pages_count=5, has_pdf=True
        )
    )
    animated = GOOD_DECK.replace(
        '{"kind": "slides", "slides": 3}', '{"kind": "animation"}'
    ).replace("<body>", "<body><script>requestAnimationFrame(go)</script>")
    found = presentation_guide.checks(animated, has_pdf=True)
    assert any("how long it lasts" in check for check in found)
    assert any("collaboratorsTimeline" in check for check in found)
    broken = GOOD_DECK.replace('"slides": 3}', '"slides": 3')
    assert presentation_guide.checks(broken, has_pdf=True) == [
        "Its presentation card isn't valid JSON."
    ]


@pytest.mark.usefixtures("page_update", "pages")
def test_an_assistant_reads_the_guide_and_sends_the_pdf_with_its_html():
    """The guide as a tool; the pair in one call; what it misses told."""
    user = factories.UserFactory(email="ada@example.org")
    page = factories.DocumentFactory(users=[(user, "editor")])

    tools = _rpc(_token(user.email), "tools/list").json()["result"]["tools"]
    publish = next(tool for tool in tools if tool["name"] == "publish_presentation")
    assert "pdf_base64" in publish["inputSchema"]["properties"]
    assert "presentation_guide" in publish["description"]
    guide = _call(user, "presentation_guide", {})
    assert "window.collaboratorsTimeline" in guide["content"][0]["text"]
    assert APIClient().get(f"{API}guide/").json()["guide"] == presentation_guide.GUIDE

    result = _call(
        user,
        "publish_presentation",
        {
            "page_id": str(page.pk),
            "html": DECK,
            "pdf_base64": "JVBERi0xLjcKJSB0d2luCg==",
        },
    )
    shown = result["structuredContent"]["presentation"]
    assert shown["pdf"]["state"] == "current"
    assert any("no presentation card" in check for check in shown["checks"])
    assert "What it misses of presentation_guide" in result["content"][0]["text"]

    fixed = _call(
        user,
        "replace_presentation",
        {
            "presentation_id": shown["id"],
            "html": GOOD_DECK,
            "pdf_base64": "JVBERi0xLjcKJSB0d2luCg==",
        },
    )
    assert fixed["structuredContent"]["presentation"]["checks"] == []
    assert "It follows presentation_guide." in fixed["content"][0]["text"]

    refused = _call(
        user,
        "replace_presentation",
        {"presentation_id": shown["id"], "pdf_base64": "PGh0bWw+"},
    )
    assert refused["isError"]


@pytest.mark.usefixtures("pages")
def test_an_upload_address_takes_the_html_and_its_pdf(storage):
    """Both in one go; the answer lists what they miss."""
    editor = factories.UserFactory()
    page = factories.DocumentFactory(users=[(editor, "editor")])
    presentation = presentations.create(editor, page)
    path = presentations.upload_address(editor, presentation).removeprefix(
        "https://app.example.org"
    )

    response = APIClient().post(
        path,
        {
            "file": SimpleUploadedFile("deck.html", GOOD_DECK.encode()),
            "pdf": SimpleUploadedFile("deck.pdf", PDF),
        },
        format="multipart",
    )

    assert response.status_code == 200
    assert response.json()["pdf"]["state"] == "current"
    assert response.json()["checks"] == []
    assert len(storage.files) == 2
