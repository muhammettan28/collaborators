"""
Collaborators: platform owners put people straight into workspaces, spaces
and pages, any on the platform, apart from invitations (nothing to accept,
and the owner needs no role there). Each person added gets one email listing
where they were added (core.tasks.mail), unless the owner chose not to tell
them.

A role is only ever raised: someone already there with that role or a
higher one keeps theirs. Every addition is written to the platform log.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext, override

from core import choices, invitations, models, platform_roles

WORKSPACE = "workspace"
SPACE = "space"
PAGE = "page"
KINDS = [WORKSPACE, SPACE, PAGE]

ADDED = "added"
RAISED = "raised"
ALREADY = "already"

# Places found a search, of each kind
FOUND_PER_KIND = 20


class PlacementError(Exception):
    """What the owner asked can't be done; the message says why."""


def roles_of(kind):
    """The roles a kind of place gives."""
    if kind == WORKSPACE:
        return choices.WorkspaceRoleChoices
    return choices.RoleChoices


def kind_of(item):
    """ "workspace", "space" or "page"."""
    if isinstance(item, models.Workspace):
        return WORKSPACE
    return SPACE if item.kind == choices.DocumentKindChoices.SPACE else PAGE


def name_of(item):
    """The name of a workspace, the title of a space or page."""
    if isinstance(item, models.Workspace):
        return item.name
    return item.title or str(_("Untitled page"))


def link_of(item):
    """The address of a place in the app."""
    return f"{invitations.app_domain()}/{kind_of(item)}/{item.id}/"


def live_documents():
    """Spaces and pages neither deleted nor in a deleted one."""
    return models.Document.objects.filter(
        deleted_at__isnull=True, ancestors_deleted_at__isnull=True
    )


def describe(item):
    """A place as the owner's tool lists it, with the space a page is in."""
    place = {"kind": kind_of(item), "id": str(item.id), "name": name_of(item)}
    if isinstance(item, models.Document) and item.depth > 1:
        root = live_documents().filter(path=item.path[: item.steplen]).first()
        place["inside"] = name_of(root) if root else ""
    return place


def find_places(query):
    """Workspaces, spaces and pages whose name has the query, newest first."""
    query = (query or "").strip()
    workspaces = models.Workspace.objects.order_by("-created_at")
    documents = live_documents().order_by("-updated_at")
    if query:
        workspaces = workspaces.filter(name__unaccent__icontains=query)
        documents = documents.filter(title__unaccent__icontains=query)
    spaces = documents.filter(kind=choices.DocumentKindChoices.SPACE)
    pages = documents.exclude(kind=choices.DocumentKindChoices.SPACE)
    return [
        describe(item)
        for found in (workspaces, spaces, pages)
        for item in found[:FOUND_PER_KIND]
    ]


def resolve_places(raw_places):
    """The places asked for, each with its role, or a PlacementError."""
    places = []
    for raw in raw_places or []:
        kind = raw.get("kind") if isinstance(raw, dict) else None
        if kind not in KINDS:
            raise PlacementError(str(_("Unknown kind of place.")))
        role = raw.get("role")
        if role not in roles_of(kind).values:
            raise PlacementError(str(_("Unknown role.")))
        try:
            if kind == WORKSPACE:
                item = models.Workspace.objects.filter(id=raw.get("id")).first()
            else:
                item = live_documents().filter(id=raw.get("id")).first()
        except ValueError, TypeError, ValidationError:
            item = None
        if item is None or kind_of(item) != kind:
            raise PlacementError(str(_("This place doesn't exist anymore.")))
        places.append((item, role))
    if not places:
        raise PlacementError(str(_("Choose at least one place.")))
    return places


def resolve_people(raw_ids):
    """The active accounts asked for, or a PlacementError."""
    try:
        people = list(
            models.User.objects.filter(
                id__in=raw_ids or [], is_active=True, is_device=False
            )
        )
    except (ValueError, TypeError, ValidationError) as err:
        raise PlacementError(str(_("Unknown person."))) from err
    if not people:
        raise PlacementError(str(_("Choose at least one person.")))
    if len(people) != len(set(raw_ids)):
        raise PlacementError(str(_("Some of these people can't be added.")))
    return people


def place_one(user, item, role):
    """Give the user this role on the place; what it did."""
    roles = roles_of(kind_of(item))
    if isinstance(item, models.Workspace):
        access, created = models.WorkspaceAccess.objects.get_or_create(
            workspace=item, user=user, defaults={"role": role}
        )
    else:
        access, created = models.DocumentAccess.objects.get_or_create(
            document=item, user=user, defaults={"role": role}
        )
    if created:
        return ADDED
    if roles.get_priority(role) <= roles.get_priority(access.role):
        return ALREADY
    access.role = role
    access.save(update_fields=["role", "updated_at"])
    return RAISED


def add_to_places(actor, raw_people, raw_places, notify=True):
    """
    Add each person to each place and log it; the outcome for each person
    and place (the caller sends the emails, see `to_tell`).
    """
    if not platform_roles.has_level(actor, platform_roles.OWNER):
        raise PlacementError(str(_("Only platform owners add people this way.")))
    people = resolve_people(raw_people)
    places = resolve_places(raw_places)
    outcomes = []
    with transaction.atomic():
        for user in people:
            done = []
            for item, role in places:
                result = place_one(user, item, role)
                done.append({**describe(item), "role": role, "result": result})
            platform_roles.log(
                choices.PlatformLogActionChoices.ADDED_TO_PLACES,
                user,
                actor=actor,
                places=done,
                notified=notify,
            )
            outcomes.append({"id": str(user.id), "places": done})
    return outcomes


def to_tell(outcome):
    """The places someone was added to or raised in, for their email."""
    return [
        [place["kind"], place["id"], place["role"]]
        for place in outcome["places"]
        if place["result"] != ALREADY
    ]


def what_of(kind):
    """ "the workspace", "the space" or "the page"."""
    return {
        WORKSPACE: _("the workspace"),
        SPACE: _("the space"),
        PAGE: _("the page"),
    }[kind]


def role_label(kind, role):
    """A role as the email says it."""
    return str(roles_of(kind)(role).label).lower()


def send_added_mail(user_id, actor_id, changed):
    """The email telling someone where a platform owner added them."""
    user = models.User.objects.filter(id=user_id, is_active=True).first()
    actor = models.User.objects.filter(id=actor_id).first()
    if user is None or not user.email:
        return
    places = []
    for kind, item_id, role in changed:
        if kind == WORKSPACE:
            item = models.Workspace.objects.filter(id=item_id).first()
        else:
            item = live_documents().filter(id=item_id).first()
        if item is not None:
            places.append((kind, item, role))
    if not places:
        return
    actor_name = (actor.full_name or actor.email) if actor else ""
    actor_email = actor.email if actor else ""
    brand = settings.EMAIL_BRAND_NAME
    with override(user.language or settings.LANGUAGE_CODE):
        context = {"brandname": brand, "logo_img": settings.EMAIL_LOGO_IMG}
        first_kind, first, first_role = places[0]
        others = len(places) - 1
        if others:
            title = ngettext(
                "{name} added you to {item} and {count} more",
                "{name} added you to {item} and {count} more",
                others,
            ).format(name=actor_name, item=name_of(first), count=others)
            context.update(
                {
                    "message": _(
                        "{name} ({email}), an owner of {brand}, added you to "
                        "these. There is nothing to accept: you are in them "
                        "already."
                    ).format(name=actor_name, email=actor_email, brand=brand),
                    "invitations": [
                        {
                            "label": _("{what} “{item}”, as {role}").format(
                                what=what_of(kind),
                                item=name_of(item),
                                role=role_label(kind, role),
                            )
                        }
                        for kind, item, role in places
                    ],
                    "link": invitations.app_domain() + "/",
                    "button_label": _("Open {brand}").format(brand=brand),
                }
            )
        else:
            title = _("{name} added you to {what} {item}").format(
                name=actor_name, what=what_of(first_kind), item=name_of(first)
            )
            context.update(
                {
                    "message": _(
                        "{name} ({email}), an owner of {brand}, added you as "
                        "{role} to {what}"
                    ).format(
                        name=actor_name,
                        email=actor_email,
                        brand=brand,
                        role=role_label(first_kind, first_role),
                        what=what_of(first_kind),
                    ),
                    "link": link_of(first),
                    "link_label": name_of(first),
                    "button_label": _("Open {what}").format(what=what_of(first_kind)),
                }
            )
        context["title"] = title
        invitations.deliver(user.email, title, context)
