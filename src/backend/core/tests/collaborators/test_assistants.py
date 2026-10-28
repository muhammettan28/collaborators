"""
Collaborators: input from one's own AI assistant through the MCP server
(core.assistants, core.api.mcp), and the assistants one connected.
"""

import json
import time
from unittest import mock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from rest_framework.test import APIClient

from core import assistants, factories, models
from core.api import mcp
from core.services import keycloak
from core.services.converter_services import YdocConverter
from core.services.yhub_services import YHubService

pytestmark = pytest.mark.django_db

ISSUER = "https://auth.example.org/realms/collaborators"
APP = "https://app.example.org"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(autouse=True)
def fixture_mcp_settings(settings):
    """The app's and the sign-in server's addresses."""
    settings.EMAIL_URL_APP = APP
    settings.COLLABORATORS_MCP_RESOURCE = ""
    settings.OIDC_OP_AUTHORIZATION_ENDPOINT = f"{ISSUER}/protocol/openid-connect/auth"
    signing = mock.Mock(key=KEY.public_key())
    with mock.patch.object(
        mcp,
        "_jwks",
        return_value=mock.Mock(get_signing_key_from_jwt=lambda _t: signing),
    ):
        yield


def _token(email, audience=f"{APP}/mcp", issuer=ISSUER, **claims):
    return jwt.encode(
        {
            "sub": email,
            "email": email,
            "aud": audience,
            "iss": issuer,
            "exp": int(time.time()) + 300,
            "azp": "claude-client",
            **claims,
        },
        KEY,
        algorithm="RS256",
    )


def _rpc(token, method, params=None, request_id=1):
    client = APIClient()
    body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if request_id is not None:
        body["id"] = request_id
    return client.post(
        "/mcp",
        data=json.dumps(body),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}" if token else "",
    )


def test_editable_pages_are_those_one_can_edit():
    """Edit rights on the page or above it; found by title; not deleted."""
    user = factories.UserFactory()
    plan = factories.DocumentFactory(title="Q4 Plan", users=[(user, "editor")])
    below = factories.DocumentFactory(parent=plan, title="Q4 Notes")
    factories.DocumentFactory(
        title="Q4 Read only", link_reach="restricted", users=[(user, "reader")]
    )
    gone = factories.DocumentFactory(title="Q4 Gone", users=[(user, "owner")])
    gone.soft_delete()

    titles = {page["title"] for page in assistants.editable_pages(user, "q4")}

    assert titles == {plan.title, below.title}
    assert assistants.editable_pages(user, "notes")[0]["url"] == (
        f"{APP}/page/{below.pk}/"
    )


def test_the_title_names_the_person_and_the_assistant():
    """Name, email, assistant and date; an unnamed assistant has a default."""
    user = factories.UserFactory(full_name="Ada Lovelace", email="ada@example.org")
    title = assistants.toggle_title(user, "Claude")
    assert title.startswith("Input from Ada Lovelace (ada@example.org) · via Claude · ")
    assert "via an AI assistant" in assistants.toggle_title(user, "")


def test_input_is_added_at_the_end_as_the_person():
    """Read the page, build the toggle, append it credited to the person."""
    user = factories.UserFactory(full_name="Ada", email="ada@example.org")
    page = factories.DocumentFactory(title="Plan", users=[(user, "editor")])
    with (
        mock.patch.object(YHubService, "get_ydoc", return_value=b"state") as get,
        mock.patch.object(
            YdocConverter, "append_toggle", return_value=b"delta"
        ) as build,
        mock.patch.object(YHubService, "append_ydoc") as append,
    ):
        result = assistants.add_input(user, str(page.pk), "## Ideas\n\n- one", "Claude")

    assert result == {
        "id": str(page.pk),
        "title": "Plan",
        "url": f"{APP}/page/{page.pk}/",
    }
    get.assert_called_once()
    state, title, text = build.call_args.args
    assert state == b"state"
    assert title.startswith("Input from Ada (ada@example.org) · via Claude")
    assert text == "## Ideas\n\n- one"
    append.assert_called_once_with(page, b"delta")


@pytest.mark.parametrize(
    ("role", "text", "message"),
    [
        ("reader", "Hello", "can't edit"),
        ("editor", "   ", "nothing to add"),
        ("editor", "x" * (assistants.MAX_INPUT_LENGTH + 1), "too long"),
    ],
)
def test_input_is_refused_with_why(role, text, message):
    """No edit rights, nothing to add, or too much at once."""
    user = factories.UserFactory()
    page = factories.DocumentFactory(link_reach="restricted", users=[(user, role)])
    with pytest.raises(assistants.InputError, match=message):
        assistants.add_input(user, str(page.pk), text)


def test_a_page_one_cannot_see_is_not_found():
    """Its existence isn't told."""
    user = factories.UserFactory()
    page = factories.DocumentFactory(link_reach="restricted")
    with pytest.raises(assistants.InputError, match="doesn't exist"):
        assistants.add_input(user, str(page.pk), "Hello")


def test_the_server_says_where_to_sign_in():
    """Without a token: 401 pointing to the resource's metadata; which names Keycloak."""
    response = _rpc(None, "initialize")
    assert response.status_code == 401
    assert response["WWW-Authenticate"] == (
        f'Bearer resource_metadata="{APP}/.well-known/oauth-protected-resource"'
    )
    metadata = APIClient().get("/.well-known/oauth-protected-resource").json()
    assert metadata["resource"] == f"{APP}/mcp"
    assert metadata["authorization_servers"] == [ISSUER]
    assert (
        APIClient().get("/.well-known/oauth-protected-resource/mcp").status_code == 200
    )


@pytest.mark.parametrize(
    "token_args",
    [
        {"audience": "https://elsewhere.example.org/mcp"},
        {"issuer": "https://evil.example.org/realms/x"},
        {"exp": int(time.time()) - 10},
    ],
)
def test_tokens_for_others_or_expired_are_refused(token_args):
    """Another audience, another issuer, expired: invalid_token."""
    user = factories.UserFactory()
    response = _rpc(_token(user.email, **token_args), "ping")
    assert response.status_code == 401
    assert 'error="invalid_token"' in response["WWW-Authenticate"]


def test_people_not_let_in_get_no_access():
    """Unknown, waiting for approval, or suspended."""
    waiting = factories.UserFactory(registration_status="pending")
    for email in ("nobody@example.org", waiting.email):
        assert _rpc(_token(email), "ping").status_code == 401


def test_initialize_and_tools():
    """The handshake, in the version asked; the two tools."""
    user = factories.UserFactory()
    token = _token(user.email)

    init = _rpc(token, "initialize", {"protocolVersion": "2025-06-18"}).json()
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["capabilities"] == {"tools": {"listChanged": False}}
    assert (
        _rpc(token, "initialize", {"protocolVersion": "1999"}).json()["result"][
            "protocolVersion"
        ]
        == mcp.PROTOCOL_VERSIONS[0]
    )
    assert _rpc(token, "notifications/initialized", request_id=None).status_code == 202
    tools = _rpc(token, "tools/list").json()["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
        "find_pages",
        "add_input_to_page",
        "publish_presentation",
        "replace_presentation",
        "list_presentations",
    ]
    assert _rpc(token, "nope").json()["error"]["code"] == -32601
    assert (
        APIClient().get("/mcp", HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 405
    )


def test_find_pages_through_mcp():
    """The pages one can edit, as text and structured."""
    user = factories.UserFactory()
    page = factories.DocumentFactory(title="Roadmap", users=[(user, "editor")])
    result = _rpc(
        _token(user.email), "tools/call", {"name": "find_pages", "arguments": {}}
    ).json()["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["pages"][0]["id"] == str(page.pk)


def test_add_input_through_mcp_names_the_assistant():
    """Its own name, or the one it registered under at the sign-in server."""
    user = factories.UserFactory()
    page = factories.DocumentFactory(title="Roadmap", users=[(user, "editor")])
    mcp._known_client_name.cache_clear()  # pylint: disable=protected-access
    with (
        mock.patch.object(
            assistants,
            "add_input",
            return_value={"id": str(page.pk), "title": "Roadmap", "url": "u"},
        ) as add,
        mock.patch.object(keycloak, "client_name", return_value="ChatGPT"),
    ):
        result = _rpc(
            _token(user.email),
            "tools/call",
            {
                "name": "add_input_to_page",
                "arguments": {"page_id": str(page.pk), "text": "Hello"},
            },
        ).json()["result"]

    assert result["isError"] is False
    assert "Roadmap" in result["content"][0]["text"]
    assert add.call_args.args == (user, str(page.pk), "Hello", "ChatGPT")


def test_add_input_errors_reach_the_model():
    """A refusal is a result the assistant reads, not a failure."""
    user = factories.UserFactory()
    page = factories.DocumentFactory(link_reach="restricted", users=[(user, "reader")])
    result = _rpc(
        _token(user.email),
        "tools/call",
        {
            "name": "add_input_to_page",
            "arguments": {
                "page_id": str(page.pk),
                "text": "Hi",
                "assistant_name": "Claude",
            },
        },
    ).json()["result"]
    assert result["isError"] is True
    assert "can't edit" in result["content"][0]["text"]


def test_assistants_are_sorted_into_the_three_with_their_state(settings):
    """Claude, ChatGPT, Gemini, each with its approvals; others apart."""
    settings.OIDC_RP_CLIENT_ID = "collaborators"
    user = factories.UserFactory()
    models.AssistantUse.objects.create(
        user=user, client_id="c-claude", last_used_at="2026-10-26T10:00:00Z"
    )
    infos = {
        "c-claude": {"id": "u1", "name": "Claude", "redirect_uris": []},
        "c-cli": {
            "id": "u2",
            "name": "Some CLI",
            "redirect_uris": ["http://localhost:7777/oauth/callback"],
        },
        "c-odd": {
            "id": "u3",
            "name": "Odd tool",
            "redirect_uris": ["https://x.example"],
        },
    }
    client = APIClient()
    client.force_login(user)
    with (
        mock.patch.object(keycloak, "is_configured", return_value=True),
        mock.patch.object(keycloak, "find_user_id", return_value="kc-1"),
        mock.patch.object(
            keycloak,
            "consents",
            return_value=[
                {"clientId": "collaborators", "createdDate": 1},
                {"clientId": "c-claude", "createdDate": 2},
                {"clientId": "c-cli", "createdDate": 3},
                {"clientId": "c-odd", "createdDate": 4},
            ],
        ),
        mock.patch.object(keycloak, "client_info", side_effect=infos.get),
        mock.patch.object(
            keycloak, "has_session", side_effect=lambda _u, uuid: uuid == "u1"
        ),
    ):
        body = client.get("/api/v1.0/users/me/assistants/").json()

    assert body["mcp_url"] == f"{APP}/mcp"
    tools = {tool["id"]: tool for tool in body["tools"]}
    assert [tool["id"] for tool in body["tools"]] == ["claude", "chatgpt", "gemini"]
    claude = tools["claude"]["approvals"][0]
    assert claude["name"] == "Claude"
    assert claude["connected"] is True
    assert claude["last_used_at"].startswith("2026-10-26")
    assert tools["chatgpt"]["approvals"] == []
    # recognised by where its sign-in returns; no live session: not in use
    gemini = tools["gemini"]["approvals"][0]
    assert gemini["client_id"] == "c-cli" and gemini["connected"] is False
    assert [item["client_id"] for item in body["others"]] == ["c-odd"]


def test_disconnecting_withdraws_the_approval_and_forgets_its_use(settings):
    """The approval goes at the sign-in server; never the app's own client."""
    settings.OIDC_RP_CLIENT_ID = "collaborators"
    user = factories.UserFactory()
    models.AssistantUse.objects.create(
        user=user, client_id="abc-123", last_used_at="2026-10-26T10:00:00Z"
    )
    client = APIClient()
    client.force_login(user)
    with (
        mock.patch.object(keycloak, "is_configured", return_value=True),
        mock.patch.object(keycloak, "find_user_id", return_value="kc-1"),
        mock.patch.object(keycloak, "revoke_consent") as revoke,
    ):
        assert (
            client.delete("/api/v1.0/users/me/assistants/abc-123/").status_code == 204
        )
        revoke.assert_called_once_with("kc-1", "abc-123")
        assert (
            client.delete("/api/v1.0/users/me/assistants/collaborators/").status_code
            == 404
        )
    assert not models.AssistantUse.objects.exists()


def test_using_a_tool_records_when():
    """A tool called through MCP records the assistant's last use."""
    user = factories.UserFactory()
    factories.DocumentFactory(users=[(user, "editor")])
    _rpc(_token(user.email), "tools/call", {"name": "find_pages", "arguments": {}})
    _rpc(_token(user.email), "tools/list")
    use = models.AssistantUse.objects.get()
    assert (use.user, use.client_id) == (user, "claude-client")


def test_a_session_is_live_offline_or_online(settings):
    """The assistant's refresh tokens, or a session naming it."""
    settings.COLLABORATORS_KEYCLOAK_URL = "http://keycloak.test"
    settings.COLLABORATORS_KEYCLOAK_REALM = "collaborators"
    settings.COLLABORATORS_KEYCLOAK_CLIENT_ID = "collaborators-backend"
    settings.COLLABORATORS_KEYCLOAK_CLIENT_SECRET = "secret"
    with mock.patch.object(keycloak, "_request") as request:
        request.side_effect = [[{"id": "s"}]]
        assert keycloak.has_session("kc-1", "u1") is True
        request.side_effect = [None, [{"clients": {"u1": "c-claude"}}]]
        assert keycloak.has_session("kc-1", "u1") is True
        request.side_effect = [[], [{"clients": {"u9": "x"}}]]
        assert keycloak.has_session("kc-1", "u1") is False


def test_the_converter_builds_the_toggle_update(settings):
    """The page's state base64 encoded, the title and the Markdown."""
    settings.Y_PROVIDER_API_BASE_URL = "http://converter/api/"
    response = mock.Mock(content=b"delta", status_code=200)
    with (
        mock.patch.object(YdocConverter, "auth_header", "Bearer t"),
        mock.patch(
            "core.services.converter_services.requests.post", return_value=response
        ) as post,
    ):
        assert YdocConverter().append_toggle(b"state", "Title", "Text") == b"delta"

    assert post.call_args.args[0] == "http://converter/api/append-toggle/"
    assert post.call_args.kwargs["json"] == {
        "doc": "c3RhdGU=",
        "title": "Title",
        "markdown": "Text",
    }


def test_the_collaboration_server_gets_the_update_as_the_person():
    """append-ydoc, the raw update, credited to the user the service is for."""
    user = factories.UserFactory()
    page = factories.DocumentFactory()
    with mock.patch.object(YHubService, "request") as request:
        YHubService(user=user).append_ydoc(page, b"delta")
    method, url = request.call_args.args
    assert method == "post"
    assert "/append-ydoc/v1/" in url and str(page.pk) in url
    assert request.call_args.kwargs["data"] == b"delta"
    assert request.call_args.kwargs["headers"]["X-User-Id"] == str(user.pk)


def test_a_failed_name_lookup_is_tried_again():
    """Keycloak refusing once doesn't leave the assistant nameless for good."""
    mcp._known_client_name.cache_clear()  # pylint: disable=protected-access
    with mock.patch.object(
        keycloak, "client_name", side_effect=[keycloak.KeycloakError("403"), "Claude"]
    ):
        assert mcp.client_name("abc") == ""
        assert mcp.client_name("abc") == "Claude"
        # found once, kept
        assert mcp.client_name("abc") == "Claude"
