"""Declare and configure choices for Docs' core application."""

from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _


class PriorityTextChoices(TextChoices):
    """
    This class inherits from Django's TextChoices and provides a method to get the priority
    of a given value based on its position in the class.
    """

    @classmethod
    def get_priority(cls, role):
        """Returns the priority of the given role based on its order in the class."""

        members = list(cls.__members__.values())
        return members.index(role) + 1 if role in members else 0

    @classmethod
    def max(cls, *roles):
        """
        Return the highest-priority role among the given roles, using get_priority().
        If no valid roles are provided, returns None.
        """
        valid_roles = [role for role in roles if cls.get_priority(role) is not None]
        if not valid_roles:
            return None
        return max(valid_roles, key=cls.get_priority)


class LinkRoleChoices(PriorityTextChoices):
    """Defines the possible roles a link can offer on a document."""

    READER = "reader", _("Reader")  # Can read
    COMMENTER = "commenter", _("Commenter")  # Can read and comment
    EDITOR = "editor", _("Editor")  # Can read and edit


class RoleChoices(PriorityTextChoices):
    """Defines the possible roles a user can have in a resource."""

    READER = "reader", _("Reader")  # Can read
    COMMENTER = "commenter", _("Commenter")  # Can read and comment
    EDITOR = "editor", _("Editor")  # Can read and edit
    ADMIN = "administrator", _("Administrator")  # Can read, edit, delete and share
    OWNER = "owner", _("Owner")


PRIVILEGED_ROLES = [RoleChoices.ADMIN, RoleChoices.OWNER]
COMMENTING_ROLES = [RoleChoices.COMMENTER, RoleChoices.EDITOR, *PRIVILEGED_ROLES]


class LinkReachChoices(PriorityTextChoices):
    """Defines types of access for links"""

    RESTRICTED = (
        "restricted",
        _("Restricted"),
    )  # Only users with a specific access can read/edit the document
    AUTHENTICATED = (
        "authenticated",
        _("Authenticated"),
    )  # Any authenticated user can access the document
    PUBLIC = "public", _("Public")  # Even anonymous users can access the document

    @classmethod
    def get_select_options(cls, link_reach, link_role):
        """
        Determines the valid select options for link reach and link role depending on the
        ancestors' link reach/role given as arguments.
        Returns:
            Dictionary mapping possible reach levels to their corresponding possible roles.
        """
        return {
            reach: [
                role
                for role in LinkRoleChoices.values
                if LinkRoleChoices.get_priority(role)
                >= LinkRoleChoices.get_priority(link_role)
            ]
            if reach != cls.RESTRICTED
            else None
            for reach in cls.values
            if LinkReachChoices.get_priority(reach)
            >= LinkReachChoices.get_priority(link_reach)
        }


def get_equivalent_link_definition(ancestors_links):
    """
    Return the (reach, role) pair with:
    1. Highest reach
    2. Highest role among links having that reach
    """
    if not ancestors_links:
        return {"link_reach": None, "link_role": None}

    # 1) Find the highest reach
    max_reach = max(
        ancestors_links,
        key=lambda link: LinkReachChoices.get_priority(link["link_reach"]),
    )["link_reach"]

    # 2) Among those, find the highest role (ignore role if RESTRICTED)
    if max_reach == LinkReachChoices.RESTRICTED:
        max_role = None
    else:
        max_role = max(
            (
                link["link_role"]
                for link in ancestors_links
                if link["link_reach"] == max_reach
            ),
            key=LinkRoleChoices.get_priority,
        )

    return {"link_reach": max_reach, "link_role": max_role}


class DocumentKindChoices(TextChoices):
    """A document is a page, or the root of a space holding pages."""

    PAGE = "page", _("Page")
    SPACE = "space", _("Space")


class WorkspaceRoleChoices(PriorityTextChoices):
    """Defines the roles a user can have in a workspace."""

    MEMBER = "member", _("Member")
    ADMIN = "administrator", _("Administrator")
    OWNER = "owner", _("Owner")


WORKSPACE_PRIVILEGED_ROLES = [WorkspaceRoleChoices.ADMIN, WorkspaceRoleChoices.OWNER]


class PublishingPolicyChoices(TextChoices):
    """Who may publish the pages and spaces of a workspace to the web."""

    SPACE_ADMINS = "space_admins", _("Space owners and administrators")
    WORKSPACE_ADMINS = "workspace_admins", _("Workspace administrators only")


class PublicationActionChoices(TextChoices):
    """What happened, in the publishing log."""

    PAGE_PUBLISHED = "page_published", _("Page published")
    PAGE_UNPUBLISHED = "page_unpublished", _("Page unpublished")
    WIKI_PUBLISHED = "wiki_published", _("Wiki published")
    WIKI_UPDATED = "wiki_updated", _("Wiki updated")
    WIKI_UNPUBLISHED = "wiki_unpublished", _("Wiki unpublished")
    WIKI_RELEASED = "wiki_released", _("Fixed version of a wiki published")
    WIKI_LIVE = "wiki_live", _("Wiki shown live again")


class GroupKindChoices(TextChoices):
    """A group gathers people working on a task, or belonging to an organization."""

    TEAM = "team", _("Team")
    ORGANIZATION = "organization", _("Organization")


class JoinViaChoices(TextChoices):
    """How someone came to ask to join a workspace."""

    LINK = "link", _("Join link")
    DOMAIN = "domain", _("Email domain")
    ORGANIZATION = "organization", _("Organisation")
    DIRECTORY = "directory", _("Discover workspaces")


class WorkspaceVisibilityChoices(TextChoices):
    """Who can find a workspace (its name, description, public spaces)."""

    PUBLIC = "public", _("Public on the internet")
    PLATFORM = "platform", _("Everyone on Collaborators")
    HIDDEN = "hidden", _("Only its members")


class JoinRequestStatusChoices(TextChoices):
    """Whether the admins answered a request to join."""

    PENDING = "pending", _("Pending")
    DECLINED = "declined", _("Declined")


class RegistrationStatusChoices(TextChoices):
    """Whether a platform manager let a new collaborator in."""

    APPROVED = "approved", _("Approved")
    PENDING = "pending", _("Pending")
    DECLINED = "declined", _("Declined")


class PlatformRoleChoices(TextChoices):
    """
    Collaborators: the levels of the platform, lowest first; each has the
    rights of the levels below it (see core.platform_roles). Each is named
    with one word in the interface.
    """

    COLLABORATOR = "collaborator", _("Collaborator")
    MANAGER = "manager", _("Manager")
    ADMINISTRATOR = "administrator", _("Administrator")
    OWNER = "owner", _("Owner")


class PlatformLogActionChoices(TextChoices):
    """What the platform log records."""

    ROLE_CHANGED = "role_changed", _("Level changed")
    SUSPENDED = "suspended", _("Account suspended")
    REINSTATED = "reinstated", _("Account reinstated")
    REMOVED = "removed", _("Account removed")
    BLOCKED = "blocked", _("Email blocked")
    UNBLOCKED = "unblocked", _("Email unblocked")
    REPORT_DISMISSED = "report_dismissed", _("Report dismissed")
    TAKEN_DOWN = "taken_down", _("Page taken down")
    PUT_BACK = "put_back", _("Page put back")
    SETTINGS_CHANGED = "settings_changed", _("Platform settings changed")
    MERGED = "merged", _("Accounts merged")
    ADDED_TO_PLACES = "added_to_places", _("Added to places")


class ReportReasonChoices(TextChoices):
    """Collaborators: why someone reports a page (core.reports)."""

    SPAM = "spam", _("Spam or advertising")
    ABUSE = "abuse", _("Abuse or harassment")
    ILLEGAL = "illegal", _("Illegal content")
    PERSONAL_DATA = "personal_data", _("Someone's personal data")
    COPYRIGHT = "copyright", _("Copyright infringement")
    OTHER = "other", _("Something else")


class ReportStatusChoices(TextChoices):
    """Where a report stands, and what was decided."""

    OPEN = "open", _("Open")
    DISMISSED = "dismissed", _("Dismissed")
    TAKEN_DOWN = "taken_down", _("Page taken down")


class SpaceVisibilityChoices(TextChoices):
    """Who can read a space when it is created."""

    PUBLIC = "public", _("Public")
    WORKSPACE = "workspace", _("All workspace members")
    INVITED = "invited", _("Only invited people")
