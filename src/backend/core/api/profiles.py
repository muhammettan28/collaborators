"""
Profiles: what collaborators tell about themselves, each piece shown to the
audience they chose (public, everyone on Collaborators, the people they work
with, or the members of chosen workspaces and spaces). A profile can't be
fully hidden: the name is always shown to the people one works with.

GET /api/v1.0/profiles/<user id>/  — what the viewer may see (anyone)
GET, PUT /api/v1.0/profiles/me/    — one's own profile and its settings
"""

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.db.models import Q
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

import rest_framework as drf
from rest_framework.views import APIView

from core import choices, models
from core.api import permissions
from core.services import keycloak
from core.utils.users import users_sharing_documents_with

# Collaborators: "chosen workspaces and spaces" is no longer offered
AUDIENCES = [
    models.ProfileAudience.COLLEAGUES,
    models.ProfileAudience.PLATFORM,
    models.ProfileAudience.PUBLIC,
]
REACHES = [
    models.ProfileAudience.COLLEAGUES,
    models.ProfileAudience.PLATFORM,
    models.ProfileAudience.PUBLIC,
]
TEXT_FIELDS = {
    "headline": 120,
    "organization": 120,
    "location": 120,
    "bio": 2000,
}
MAX_INTERESTS = 20


def profile_of(user):
    """The user's profile, made empty the first time."""
    profile, _created = models.UserProfile.objects.get_or_create(user=user)
    return profile


class Viewer:
    """How a viewer relates to a profile's owner, computed as needed."""

    def __init__(self, owner, viewer):
        self.owner = owner
        self.viewer = viewer
        self.is_self = viewer.is_authenticated and viewer.id == owner.id

    @cached_property
    def is_colleague(self):
        """Shares a workspace or a page with the owner."""
        if not self.viewer.is_authenticated:
            return False
        return self.is_self or self.owner.id in users_sharing_documents_with(
            self.viewer.id
        )

    def is_in(self, workspace_ids, space_ids):
        """A member of one of these workspaces, or has a role on these spaces."""
        if not self.viewer.is_authenticated:
            return False
        if (
            workspace_ids
            and models.WorkspaceAccess.objects.filter(
                user=self.viewer, workspace_id__in=workspace_ids
            ).exists()
        ):
            return True
        return any(
            space.get_role(self.viewer) is not None
            for space in models.Document.objects.filter(
                id__in=space_ids,
                kind=choices.DocumentKindChoices.SPACE,
                ancestors_deleted_at__isnull=True,
            )
        )

    def can_see(self, profile, field):
        """Whether the viewer may see this piece of the profile."""
        if self.is_self:
            return True
        audience = profile.audience(field)
        level = capped(audience["level"], profile.reach)
        if level == models.ProfileAudience.PUBLIC:
            return True
        if level == models.ProfileAudience.PLATFORM:
            return self.viewer.is_authenticated
        if level == models.ProfileAudience.COLLEAGUES:
            return self.is_colleague
        return self.is_in(audience["workspaces"], audience["spaces"]) or (
            # the name can't be hidden from the people one works with
            field == "name" and self.is_colleague
        )


# From the widest audience to the narrowest
WIDTH = [
    models.ProfileAudience.SELECTED,
    models.ProfileAudience.COLLEAGUES,
    models.ProfileAudience.PLATFORM,
    models.ProfileAudience.PUBLIC,
]


def capped(level, reach):
    """
    A piece's audience, no wider than who may find the person: with "people
    I work with", "everyone on Collaborators" means the people they work with.
    """
    if not settings.COLLABORATORS_PEOPLE_PRIVACY:
        return level
    reach = reach or models.ProfileAudience.COLLEAGUES
    if WIDTH.index(level) > WIDTH.index(reach):
        return reach
    return level


def visible_workspaces_of(owner, viewer):
    """The owner's workspaces that the viewer may know about."""
    workspaces = models.Workspace.objects.filter(accesses__user=owner)
    if viewer.is_authenticated:
        workspaces = workspaces.filter(
            Q(accesses__user=viewer)
            | Q(
                visibility__in=[
                    choices.WorkspaceVisibilityChoices.PUBLIC,
                    choices.WorkspaceVisibilityChoices.PLATFORM,
                ]
            )
        )
    else:
        workspaces = workspaces.filter(
            visibility=choices.WorkspaceVisibilityChoices.PUBLIC
        )
    return [
        {"id": str(workspace.id), "name": workspace.name}
        for workspace in workspaces.distinct().order_by("name")
    ]


# How many spaces and pages a profile lists at most
PROFILE_DOCUMENTS_LIMIT = 30


def visible_documents_of(owner, viewer):
    """
    {"spaces", "pages"}: those the owner has a role on that the viewer may
    open (public, open to everyone signed in, or shared with them).
    """
    documents = (
        models.Document.objects.filter(
            accesses__user=owner,
            deleted_at__isnull=True,
            ancestors_deleted_at__isnull=True,
        )
        .distinct()
        .order_by("-updated_at")[: PROFILE_DOCUMENTS_LIMIT * 4]
    )
    result = {"spaces": [], "pages": []}
    for document in documents:
        kind = (
            "spaces" if document.kind == choices.DocumentKindChoices.SPACE else "pages"
        )
        if len(result[kind]) >= PROFILE_DOCUMENTS_LIMIT:
            continue
        if document.get_abilities(viewer).get("retrieve"):
            result[kind].append({"id": str(document.id), "title": document.title or ""})
    return result


def email_choices(user):
    """
    The person's own addresses: the account's, those its sign-in providers
    are linked with, and those of the accounts merged into it.
    """
    found = [user.email or ""]
    if keycloak.is_configured():
        try:
            keycloak_id = keycloak.find_user_id(user.email or "")
            if keycloak_id:
                links, _password = keycloak.sign_in_methods(keycloak_id)
                found.extend(links.values())
        except keycloak.KeycloakError:
            pass
    found.extend(user.sign_in_identities.values_list("account", flat=True))
    addresses = []
    for raw in found:
        email = (raw or "").strip()
        if "@" in email and email.lower() not in {a.lower() for a in addresses}:
            addresses.append(email)
    return addresses


def shown_email(owner, profile):
    """The address the profile shows: the one chosen, else the account's."""
    return profile.shown_email or owner.email or ""


def emails_seen_by(viewer, people, colleague_ids):
    """
    The address each person's profile shows the viewer, by id ("" when kept
    from them), for the lists and cards naming people. `colleague_ids`: the
    people the viewer shares something with, known already.
    """
    profiles = {
        profile.user_id: profile
        for profile in models.UserProfile.objects.filter(
            user_id__in=[person.id for person in people]
        )
    }
    seen = {}
    for person in people:
        profile = profiles.get(person.id) or models.UserProfile(user=person)
        relation = Viewer(person, viewer)
        # known already: not looked up again for each person
        relation.is_colleague = relation.is_self or person.id in colleague_ids
        seen[person.id] = (
            shown_email(person, profile) if relation.can_see(profile, "email") else ""
        )
    return seen


def forget_lost_address(user, address):
    """
    A sign-in account was removed: a profile showing its address, no longer
    one of the person's own, shows the account's again.
    """
    address = (address or "").lower()
    profile = models.UserProfile.objects.filter(
        user=user, shown_email__iexact=address
    ).first()
    if (
        not address
        or profile is None
        or address in {email.lower() for email in email_choices(user)}
    ):
        return
    profile.shown_email = ""
    profile.save(update_fields=["shown_email", "updated_at"])


def describe(owner, viewer):
    """The profile as the viewer may see it; None if hidden from them."""
    profile = profile_of(owner)
    relation = Viewer(owner, viewer)
    if not relation.can_see(profile, "name"):
        return None
    shown = {field: relation.can_see(profile, field) for field in models.PROFILE_FIELDS}
    return {
        "id": str(owner.id),
        "full_name": owner.full_name or "",
        "is_me": relation.is_self,
        "headline": profile.headline if shown["headline"] else "",
        "organization": profile.organization if shown["organization"] else "",
        "location": profile.location if shown["location"] else "",
        "bio": profile.bio if shown["bio"] else "",
        "website": profile.website if shown["website"] else "",
        "email": shown_email(owner, profile) if shown["email"] else "",
        "interests": [label.name for label in profile.interests.order_by("key")]
        if shown["interests"]
        else [],
        # the pieces kept from the viewer: their titles show, not their content
        "hidden": [field for field in models.PROFILE_FIELDS if not shown[field]],
        # each shown as its own visibility allows the viewer
        "workspaces": visible_workspaces_of(owner, viewer),
        **visible_documents_of(owner, viewer),
    }


class ProfileView(APIView):
    """Someone's profile, as much as the viewer may see."""

    permission_classes = [drf.permissions.AllowAny]

    def get(self, request, user_id):
        """The visible pieces; 404 when the profile is hidden from the viewer."""
        owner = models.User.objects.filter(id=user_id, is_active=True).first()
        if owner is None:
            raise drf.exceptions.NotFound()
        data = describe(owner, request.user)
        if data is None:
            raise drf.exceptions.NotFound()
        return drf.response.Response(data)


class MyProfileView(APIView):
    """One's own profile: every piece, who sees it, and what one can choose."""

    permission_classes = [permissions.IsAuthenticated]

    def _state(self, user):
        profile = profile_of(user)
        return {
            **describe(user, user),
            # who may find them, see their profile and invite them by name
            "reach": profile.reach,
            # the addresses one may show as the profile's email
            "email_choices": email_choices(user),
            "visibility": {
                field: profile.audience(field) for field in models.PROFILE_FIELDS
            },
            # what "Chosen workspaces and spaces" can name
            "workspace_choices": [
                {"id": str(workspace.id), "name": workspace.name}
                for workspace in models.Workspace.objects.filter(
                    accesses__user=user
                ).order_by("name")
            ],
            "space_choices": [
                {"id": str(space.id), "title": space.title}
                for space in models.Document.objects.filter(
                    Q(accesses__user=user) | Q(accesses__team__in=user.teams),
                    kind=choices.DocumentKindChoices.SPACE,
                    ancestors_deleted_at__isnull=True,
                )
                .distinct()
                .order_by("title")
            ],
        }

    def get(self, request):
        """One's whole profile and its settings."""
        return drf.response.Response(self._state(request.user))

    def put(self, request):
        """Change the pieces given, their audiences, and the interests."""
        user = request.user
        profile = profile_of(user)
        data = request.data
        errors = {}
        _apply_texts(profile, data, errors)
        if "shown_email" in data:
            wanted = str(data["shown_email"] or "").strip()
            own = {email.lower(): email for email in email_choices(user)}
            if wanted.lower() not in own:
                errors["shown_email"] = _("Choose one of your own addresses.")
            else:
                # the account's own: nothing to keep
                profile.shown_email = (
                    ""
                    if wanted.lower() == (user.email or "").lower()
                    else own[wanted.lower()]
                )
        if "reach" in data:
            if data["reach"] not in REACHES:
                errors["reach"] = _("Unknown audience.")
            else:
                profile.reach = data["reach"]
        if "visibility" in data:
            _apply_visibility(profile, data["visibility"], user, errors)
        if errors:
            raise drf.exceptions.ValidationError(errors)

        with transaction.atomic():
            profile.save()
            if "interests" in data:
                _set_interests(profile, data["interests"])
        return drf.response.Response(self._state(user))


def _apply_texts(profile, data, errors):
    """The text pieces given, and the website as a web address."""
    for field, max_length in TEXT_FIELDS.items():
        if field in data:
            value = str(data[field] or "").strip()
            if len(value) > max_length:
                errors[field] = _("Too long.")
            setattr(profile, field, value)
    if "website" not in data:
        return
    website = str(data["website"] or "").strip()
    if website and not website.startswith(("https://", "http://")):
        website = f"https://{website}"
    if website:
        try:
            URLValidator(schemes=["http", "https"])(website)
        except DjangoValidationError:
            errors["website"] = _("Enter a web address.")
    profile.website = website


def _apply_visibility(profile, wanted, user, errors):
    """Who sees each piece given; chosen workspaces must be one's own."""
    mine = {
        str(pk)
        for pk in models.Workspace.objects.filter(accesses__user=user).values_list(
            "id", flat=True
        )
    }
    visibility = {}
    for field, setting in (wanted or {}).items():
        if field not in models.PROFILE_FIELDS or not isinstance(setting, dict):
            continue
        if setting.get("level") not in AUDIENCES:
            errors["visibility"] = _("Unknown audience.")
            continue
        visibility[field] = {
            "level": setting["level"],
            "workspaces": [
                str(pk) for pk in setting.get("workspaces") or [] if str(pk) in mine
            ],
            "spaces": [str(pk) for pk in setting.get("spaces") or []],
        }
    profile.visibility = {**(profile.visibility or {}), **visibility}


def _set_interests(profile, raw_names):
    """
    The interests, among the labels already used on the platform (none is
    made from a profile): unknown names are left out.
    """
    labels = []
    for raw in raw_names or []:
        name = models.Label.normalize(raw)
        label = models.Label.objects.filter(key=name.lower()).first() if name else None
        if label and label not in labels:
            labels.append(label)
    profile.interests.set(labels[:MAX_INTERESTS])
