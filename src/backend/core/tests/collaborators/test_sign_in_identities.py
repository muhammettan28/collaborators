"""
Tests for more than one Google or Microsoft account opening a collaborator's
account (see core.identities).
"""

from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.test import RequestFactory

import pytest
from rest_framework.test import APIClient

from core import factories, identities, joining, merging, models
from core.authentication.backends import OIDCAuthenticationBackend
from core.services import keycloak

pytestmark = pytest.mark.django_db

ORG = {"id": "google:acme.org", "name": "acme.org"}


@pytest.fixture(name="configured")
def fixture_configured(settings):
    """Keycloak is set up, with its sign-out endpoint."""
    settings.COLLABORATORS_KEYCLOAK_URL = "http://keycloak.test"
    settings.COLLABORATORS_KEYCLOAK_REALM = "collaborators"
    settings.COLLABORATORS_KEYCLOAK_CLIENT_ID = "collaborators-backend"
    settings.COLLABORATORS_KEYCLOAK_CLIENT_SECRET = "secret"
    settings.COLLABORATORS_SIGNIN_PROVIDERS = ["google", "microsoft", "linkedin"]
    settings.OIDC_OP_LOGOUT_ENDPOINT = "http://keycloak.test/logout"


def client_for(user, id_token="id-token"):
    """An API client logged in as the user, with an ID token in its session."""
    client = APIClient()
    client.force_login(user)
    session = client.session
    session["oidc_id_token"] = id_token
    session.save()
    return client


def sign_in(client, sub, email):
    """Sign in through Keycloak as this account, in the client's session."""
    request = RequestFactory().get("/api/v1.0/callback/")
    request.session = client.session
    backend = OIDCAuthenticationBackend()
    backend.request = request
    backend.collaborators_access_token = "token"
    backend.collaborators_user_info = {"sub": sub, "email": email}
    with mock.patch("core.joining.read_organizations"):
        user = backend.get_or_create_user("token", "id", {})
    request.session.save()
    return user, request.session


def test_adding_an_account_goes_through_keycloak_sign_out(configured):  # pylint: disable=unused-argument
    """The URL ends the Keycloak session, then signs in with the provider."""
    user = factories.UserFactory()
    client = client_for(user)

    response = client.post(
        "/api/v1.0/users/me/sign-in-methods/google/add/",
        {"next": "http://localhost:3000/account/sign-in-methods/"},
        format="json",
    )

    assert response.status_code == 200
    url = urlparse(response.json()["url"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == "http://keycloak.test/logout"
    query = parse_qs(url.query)
    assert query["id_token_hint"] == ["id-token"]
    then = urlparse(query["post_logout_redirect_uri"][0])
    assert then.path == "/api/v1.0/authenticate/"
    assert parse_qs(then.query) == {
        "kc_idp_hint": ["google"],
        "next": ["http://localhost:3000/account/sign-in-methods/"],
    }
    assert client.session[identities.ADDING_SESSION_KEY]["provider"] == "google"

    # LinkedIn: one account only
    assert (
        client.post("/api/v1.0/users/me/sign-in-methods/linkedin/add/").status_code
        == 404
    )


def test_the_added_account_opens_the_collaborators_account(configured):  # pylint: disable=unused-argument
    """Signed in with the other account, it's recorded, then opens this one."""
    user = factories.UserFactory(sub="kc-ada", email="ada@gmail.com")
    client = client_for(user)
    client.post("/api/v1.0/users/me/sign-in-methods/google/add/", format="json")

    signed_in, session = sign_in(client, "kc-ada-work", "ada@acme.org")

    assert signed_in == user
    identity = models.SignInIdentity.objects.get()
    assert (identity.user, identity.provider, identity.account) == (
        user,
        "google",
        "ada@acme.org",
    )
    assert session[identities.NOTICE_SESSION_KEY]["outcome"] == "added"
    assert identities.ADDING_SESSION_KEY not in session
    # the user's own details aren't the other account's
    user.refresh_from_db()
    assert user.email == "ada@gmail.com"

    # later, signing in with it opens the same account
    signed_in, _session = sign_in(APIClient(), "kc-ada-work", "ada@acme.org")
    assert signed_in == user
    assert models.User.objects.count() == 1


def test_an_account_with_its_own_collaborators_account_is_offered_to_merge(configured):  # pylint: disable=unused-argument
    """
    Collaborators: an account that already opens a separate Collaborators
    account isn't added; merging it into this one is offered instead.
    """
    user = factories.UserFactory(sub="kc-ada")
    other = factories.UserFactory(sub="kc-other", email="other@contoso.com")
    client = client_for(user)
    client.post("/api/v1.0/users/me/sign-in-methods/microsoft/add/", format="json")

    signed_in, session = sign_in(client, "kc-other", "other@contoso.com")

    assert signed_in == user
    assert not models.SignInIdentity.objects.exists()
    assert session[identities.NOTICE_SESSION_KEY]["outcome"] == "merge"
    proposal = session[merging.PROPOSAL_SESSION_KEY]
    assert proposal["keep"] == str(user.pk)
    assert proposal["gone"] == str(other.pk)
    assert proposal["provider"] == "microsoft"
    # Nothing of the other account was taken before confirming
    user.refresh_from_db()
    assert user.collaborator_organizations == []


def test_an_account_that_cant_be_merged_stays_separate(configured):  # pylint: disable=unused-argument
    """At a higher level: separate, with why (merge the other way)."""
    user = factories.UserFactory(sub="kc-ada")
    factories.UserFactory(sub="kc-other", platform_role="administrator")
    client = client_for(user)
    client.post("/api/v1.0/users/me/sign-in-methods/microsoft/add/", format="json")

    _signed_in, session = sign_in(client, "kc-other", "other@contoso.com")

    notice = session[identities.NOTICE_SESSION_KEY]
    assert notice["outcome"] == "separate"
    assert "higher level" in notice["reason"]
    assert merging.PROPOSAL_SESSION_KEY not in session


def test_sign_in_methods_list_and_remove_more_accounts(configured):  # pylint: disable=unused-argument
    """More accounts show under their provider, and can be removed."""
    user = factories.UserFactory(email="ada@gmail.com")
    identity = models.SignInIdentity.objects.create(
        user=user,
        provider="google",
        sub="kc-ada-work",
        account="ada@acme.org",
        organizations=[ORG],
    )
    user.collaborator_organizations = [ORG]
    user.save()
    client = client_for(user)
    with (
        mock.patch.object(keycloak, "find_user_id", return_value="kc-1"),
        mock.patch.object(
            keycloak,
            "sign_in_methods",
            return_value=({"google": "ada@gmail.com"}, False),
        ),
    ):
        data = client.get("/api/v1.0/users/me/sign-in-methods/").json()
        google = data["methods"][0]
        assert google["more_accounts"] == [
            {"id": str(identity.id), "account": "ada@acme.org"}
        ]
        assert google["can_add_accounts"] is True
        assert data["methods"][1]["can_add_accounts"] is False  # not connected
        assert data["methods"][2]["can_add_accounts"] is False  # LinkedIn
        assert data["notice"] is None

        # with another account, Google isn't the only way in any more
        with mock.patch.object(keycloak, "unlink") as unlink:
            response = client.delete("/api/v1.0/users/me/sign-in-methods/google/")
        assert response.status_code == 204
        unlink.assert_called_once()

    response = client.delete(
        f"/api/v1.0/users/me/sign-in-methods/google/accounts/{identity.id}/"
    )
    assert response.status_code == 204
    assert not models.SignInIdentity.objects.exists()
    user.refresh_from_db()
    assert user.collaborator_organizations == []


def test_organizations_of_every_account_count(configured):  # pylint: disable=unused-argument
    """Signed in with another account, its organisation adds to the user's own."""
    own = {"id": "microsoft:t-1", "name": "contoso.com"}
    user = factories.UserFactory(
        collaborator_own_organizations=[own], collaborator_organizations=[own]
    )
    identity = models.SignInIdentity.objects.create(
        user=user, provider="google", sub="kc-work"
    )
    with mock.patch.object(
        keycloak,
        "provider_id_token_claims",
        side_effect=lambda token, provider: (
            {"hd": "acme.org"} if provider == "google" else None
        ),
    ):
        joining.read_organizations(user, "token", identity)

    identity.refresh_from_db()
    user.refresh_from_db()
    assert identity.organizations == [ORG]
    assert user.collaborator_own_organizations == [own]
    assert user.collaborator_organizations == [own, ORG]


def test_removing_an_account_forgets_its_address_on_the_profile():
    """The profile shows the account's own address again."""
    user = factories.UserFactory()
    identity = models.SignInIdentity.objects.create(
        user=user, provider="google", sub="g-2", account="ada@work.example"
    )
    models.UserProfile.objects.create(user=user, shown_email="ada@work.example")
    client = APIClient()
    client.force_login(user)

    response = client.delete(
        f"/api/v1.0/users/me/sign-in-methods/google/accounts/{identity.id}/"
    )

    assert response.status_code == 204
    assert models.UserProfile.objects.get(user=user).shown_email == ""
