"""
Declare and configure the models for the impress core application
"""

# pylint: disable=too-many-lines

import operator
import smtplib
import uuid
from datetime import timedelta
from functools import partial, reduce
from logging import getLogger

from django.conf import settings
from django.contrib.auth import models as auth_models
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import models, transaction
from django.db.models import Count
from django.db.models.functions import Left, Length
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.text import slugify
from django.utils.translation import get_language, override
from django.utils.translation import gettext_lazy as _

from rest_framework.exceptions import ValidationError
from timezone_field import TimeZoneField
from treebeard.mp_tree import MP_Node, MP_NodeManager, MP_NodeQuerySet

from core.choices import (
    PRIVILEGED_ROLES,
    WORKSPACE_PRIVILEGED_ROLES,
    DocumentKindChoices,
    GroupKindChoices,
    JoinRequestStatusChoices,
    JoinViaChoices,
    LinkReachChoices,
    LinkRoleChoices,
    PlatformLogActionChoices,
    PlatformRoleChoices,
    PublicationActionChoices,
    PublishingPolicyChoices,
    RegistrationStatusChoices,
    ReportReasonChoices,
    ReportStatusChoices,
    RoleChoices,
    WorkspaceRoleChoices,
    WorkspaceVisibilityChoices,
    get_equivalent_link_definition,
)
from core.services.yhub_services import YHubError, YHubService
from core.utils.treebeard import create_tree_node_with_retry
from core.validators import sub_validator

logger = getLogger(__name__)


# Teams are the strings that document accesses grant a role to, besides users
# (see `BaseAccess.team`). Collaborators derives them from the workspaces and
# groups a user belongs to, so that granting a group or a whole workspace on a
# space reuses the access inheritance of the document tree unchanged.
TEAM_GROUP = "group"
TEAM_WORKSPACE = "workspace"
TEAM_WORKSPACE_ADMINS = "workspace-admins"


def make_team(kind, obj_id):
    """Return the team string granting a role to a group or to a workspace."""
    return f"{kind}:{obj_id}"


def parse_team(team):
    """Split a team string into its kind and object id, or (None, None)."""
    kind, _sep, obj_id = (team or "").partition(":")
    if kind not in (TEAM_GROUP, TEAM_WORKSPACE, TEAM_WORKSPACE_ADMINS):
        return None, None
    try:
        return kind, uuid.UUID(obj_id)
    except ValueError:
        return None, None


def get_trashbin_cutoff():
    """
    Calculate the cutoff datetime for soft-deleted items based on the retention policy.

    The function returns the current datetime minus the number of days specified in
    the TRASHBIN_CUTOFF_DAYS setting, indicating the oldest date for items that can
    remain in the trash bin.

    Returns:
        datetime: The cutoff datetime for soft-deleted items.
    """
    return timezone.now() - timedelta(days=settings.TRASHBIN_CUTOFF_DAYS)


class DuplicateEmailError(Exception):
    """Raised when an email is already associated with a pre-existing user."""

    def __init__(self, message=None, email=None):
        """Set message and email to describe the exception."""
        self.message = message
        self.email = email
        super().__init__(self.message)


class BaseModel(models.Model):
    """
    Serves as an abstract base model for other models, ensuring that records are validated
    before saving as Django doesn't do it by default.

    Includes fields common to all models: a UUID primary key and creation/update timestamps.
    """

    id = models.UUIDField(
        verbose_name=_("id"),
        help_text=_("primary key for the record as UUID"),
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    created_at = models.DateTimeField(
        verbose_name=_("created on"),
        help_text=_("date and time at which a record was created"),
        auto_now_add=True,
        editable=False,
    )
    updated_at = models.DateTimeField(
        verbose_name=_("updated on"),
        help_text=_("date and time at which a record was last updated"),
        auto_now=True,
        editable=False,
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        """Call `full_clean` before saving."""
        self.full_clean()
        super().save(*args, **kwargs)


class UserManager(auth_models.UserManager):
    """Custom manager for User model with additional methods."""

    def get_user_by_sub_or_email(self, sub, email):
        """Fetch existing user by sub or email."""
        try:
            return self.get(sub=sub)
        except self.model.DoesNotExist:
            return self.get_user_by_email(email)

    def get_user_by_email(self, email):
        """When no user has the sub: the user with this email, if allowed."""
        if not email:
            return None

        if settings.OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION:
            try:
                return self.get(email__iexact=email)
            except self.model.DoesNotExist:
                pass
        elif (
            self.filter(email__iexact=email).exists()
            and not settings.OIDC_ALLOW_DUPLICATE_EMAILS
        ):
            raise DuplicateEmailError(
                _(
                    "We couldn't find a user with this sub but the email is already "
                    "associated with a registered user."
                )
            )
        return None


class User(AbstractBaseUser, BaseModel, auth_models.PermissionsMixin):
    """User model to work with OIDC only authentication."""

    sub = models.CharField(
        _("sub"),
        help_text=_("Required. 255 characters or fewer. ASCII characters only."),
        max_length=255,
        validators=[sub_validator],
        unique=True,
        blank=True,
        null=True,
    )

    full_name = models.CharField(_("full name"), max_length=100, null=True, blank=True)
    # Whether mentions and assignments are also sent by email (they always
    # reach the in-app notification inbox): off until one asks for it
    collaborator_email_notifications = models.BooleanField(default=False)
    # The identity provider vouched for the email at the last sign-in: it
    # can join workspaces by domain
    collaborator_email_verified = models.BooleanField(default=False)
    # The organisations the identity providers vouch for, read at sign-in:
    # [{"id": "google:<Workspace domain>" | "microsoft:<tenant id>", "name"}]
    collaborator_organizations = models.JSONField(default=list, blank=True)
    # Those of the account it signs in with first; collaborator_organizations
    # adds those of its other sign-in identities
    collaborator_own_organizations = models.JSONField(default=list, blank=True)
    # The dashboard hints closed for good: "welcome" (to a new account),
    # "connect-accounts" (connect another sign-in method)
    collaborator_dismissed_hints = ArrayField(
        models.CharField(max_length=40), default=list, blank=True
    )
    # The dashboard as this collaborator arranged it: [{id, hidden, collapsed}]
    collaborator_dashboard = models.JSONField(default=list, blank=True)
    # The order of the lists of "My collaborations" in the left panel
    collaborator_sidebar = models.JSONField(default=list, blank=True)
    # Which side of the screen the panel stands on: "left" or "right"
    collaborator_sidebar_side = models.CharField(
        max_length=5,
        choices=[("left", "left"), ("right", "right")],
        default="left",
    )
    # Derived from workspace and group memberships, see `teams`
    collaborator_teams = ArrayField(
        models.CharField(max_length=100), default=list, blank=True, editable=False
    )
    short_name = models.CharField(
        _("short name"), max_length=100, null=True, blank=True
    )

    email = models.EmailField(_("identity email address"), blank=True, null=True)

    # Unlike the "email" field which stores the email coming from the OIDC token, this field
    # stores the email used by staff users to login to the admin site
    admin_email = models.EmailField(
        _("admin email address"), unique=True, blank=True, null=True
    )

    language = models.CharField(
        max_length=10,
        choices=settings.LANGUAGES,
        default=None,
        verbose_name=_("language"),
        help_text=_("The language in which the user wants to see the interface."),
        null=True,
        blank=True,
    )
    timezone = TimeZoneField(
        choices_display="WITH_GMT_OFFSET",
        use_pytz=False,
        default=settings.TIME_ZONE,
        help_text=_("The timezone in which the user wants to see times."),
    )
    is_device = models.BooleanField(
        _("device"),
        default=False,
        help_text=_("Whether the user is a device or a real user."),
    )
    is_staff = models.BooleanField(
        _("staff status"),
        default=False,
        help_text=_("Whether the user can log into this admin site."),
    )
    is_active = models.BooleanField(
        _("active"),
        default=True,
        help_text=_(
            "Whether this user should be treated as active. "
            "Unselect this instead of deleting accounts."
        ),
    )
    is_first_connection = models.BooleanField(
        _("first connection status"),
        default=True,
        help_text=_("Whether the user has completed the first connection process."),
    )
    # Collaborators: a newcomer waits for a platform manager to let them
    # in, when COLLABORATORS_SIGNUP_APPROVAL is set
    registration_status = models.CharField(
        _("registration status"),
        max_length=10,
        choices=RegistrationStatusChoices.choices,
        default=RegistrationStatusChoices.APPROVED,
    )
    # Collaborators: came in through an invitation by email (someone vouches
    # for them: no approval of the registration needed)
    collaborator_invited = models.BooleanField(default=False)
    # Collaborators: the level on the platform, changed through
    # core.platform_roles (which logs it); see `platform_level`
    platform_role = models.CharField(
        _("level"),
        max_length=20,
        choices=PlatformRoleChoices.choices,
        default=PlatformRoleChoices.COLLABORATOR,
    )
    # Collaborators: a protected owner: nobody changes their level in the
    # app, and they alone change other owners' (set by set_platform_role
    # --protected on the server, see core.accounts)
    platform_protected = models.BooleanField(default=False)
    # Collaborators: suspended by a platform administrator (core.accounts):
    # inactive, and disabled at the sign-in server, until reinstated
    suspended_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "admin_email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "impress_user"
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self):
        return self.email or self.admin_email or str(self.id)

    def save(self, *args, **kwargs):
        """
        If it's a new user, give its user access to the documents they were invited to.
        """
        is_adding = self._state.adding
        super().save(*args, **kwargs)

        if is_adding:
            self._handle_onboarding_documents_access()
            self._duplicate_onboarding_sandbox_document()
            self._convert_valid_invitations()

    def delete(self, using=None, keep_parents=False):
        """Completely delete a user and its relations."""
        with transaction.atomic():
            self._delete_user_shared_documents_accesses()
            self._delete_documents_single_owner()
            self._clear_user_created_documents()

            return super().delete(using=using, keep_parents=keep_parents)

    @property
    def platform_level(self):
        """
        Collaborators: the level on the platform; a superuser (made with
        createsuperuser) is an owner.
        """
        if self.is_superuser:
            return PlatformRoleChoices.OWNER
        return self.platform_role

    def _delete_user_shared_documents_accesses(self):
        """
        accesses to delete where there are more than one owner.

        Create first a subquery to filter all the the accesses having more than one
        owner. Then use this subquery to filter the accesses belonging to this list of
        documents and to the user to delete
        """
        docs_ids = (
            DocumentAccess.objects.filter(role=RoleChoices.OWNER)
            .values("document_id")
            .annotate(owner_count=Count("id"))
            .filter(owner_count__gte=2)
            .values("document_id")
        )
        DocumentAccess.objects.filter(user=self, document_id__in=docs_ids).delete()

        logger.info(
            "user_delete: shared documents accesses for user %s have been deleted",
            self.id,
        )

    def _delete_documents_single_owner(self):
        """
        Delete the documents where the user is the single owner.

        Deleted for good, so the collaboration server, which holds their
        content and serves them to whoever is editing them, is told by id
        once the deletion is committed.
        """
        from core.tasks.documents import (  # noqa: PLC0415 # pylint: disable=import-outside-toplevel
            delete_service_documents,
        )

        documents = Document.objects.filter(
            accesses__user=self, accesses__role=RoleChoices.OWNER
        )
        # the descendants go with their ancestor, whoever they are shared with
        paths = list(documents.values_list("path", flat=True))
        document_ids = []
        if paths:
            subtrees = reduce(
                operator.or_, (models.Q(path__startswith=path) for path in paths)
            )
            document_ids = [
                str(document_id)
                for document_id in Document.objects.filter(subtrees).values_list(
                    "id", flat=True
                )
            ]
        documents.delete()
        logger.info(
            "user_delete: documents where the user %s is the sole owner deleted",
            self.id,
        )

        if document_ids:
            transaction.on_commit(partial(delete_service_documents.delay, document_ids))

    def _clear_user_created_documents(self):
        """Set creator to Null for documents where the user is the creator."""
        Document.objects.filter(creator=self).update(creator=None)
        logger.info(
            "user_delete: documents created by user %s have been cleared",
            self.id,
        )

    def _handle_onboarding_documents_access(self):
        """
        If the user is new and there are documents configured to be given to new users,
        create link traces to these documents and pin them as favorites for the user.
        """
        if settings.USER_ONBOARDING_DOCUMENTS:
            onboarding_document_ids = set(settings.USER_ONBOARDING_DOCUMENTS)
            onboarding_link_traces = []
            favorite_documents = []
            for document_id in onboarding_document_ids:
                try:
                    document = Document.objects.get(id=document_id)
                except Document.DoesNotExist:
                    logger.warning(
                        "Onboarding document with id %s does not exist. Skipping.",
                        document_id,
                    )
                    continue

                if document.computed_link_reach == LinkReachChoices.RESTRICTED:
                    logger.warning(
                        "Onboarding on a restricted document is not allowed. Must be public or "
                        "connected. Restricted document: %s",
                        document_id,
                    )
                    continue

                onboarding_link_traces.append(LinkTrace(user=self, document=document))
                favorite_documents.append(
                    DocumentFavorite(user=self, document_id=document_id)
                )

            LinkTrace.objects.bulk_create(onboarding_link_traces)
            DocumentFavorite.objects.bulk_create(favorite_documents)

    def _duplicate_onboarding_sandbox_document(self):
        """
        If the user is new and there is a sandbox document configured,
        duplicate the sandbox document for the user

        The content of the template is read from the collaboration server, which
        owns it, and seeded into the copy under the identity of the user: the
        sandbox is theirs from its very first revision.
        """
        if settings.USER_ONBOARDING_SANDBOX_DOCUMENT:
            sandbox_id = settings.USER_ONBOARDING_SANDBOX_DOCUMENT
            try:
                template_document = Document.objects.get(id=sandbox_id)
            except Document.DoesNotExist:
                logger.warning(
                    "Onboarding sandbox document with id %s does not exist. Skipping.",
                    sandbox_id,
                )
                return

            service = YHubService(user=self)
            try:
                # a template the collaboration server holds nothing for is an
                # empty template: the sandbox is created, empty as well
                ydoc_update = service.get_ydoc(template_document)

                with transaction.atomic():
                    sandbox_document = create_tree_node_with_retry(
                        lambda: Document.add_root(
                            title=template_document.title,
                            attachments=template_document.attachments,
                            duplicated_from=template_document,
                            creator=self,
                        )
                    )

                    DocumentAccess.objects.create(
                        user=self, document=sandbox_document, role=RoleChoices.OWNER
                    )

                    if ydoc_update:
                        service.create_ydoc(sandbox_document, ydoc_update)
            except YHubError:
                # Onboarding is not worth failing a signup for, and a sandbox
                # the content of which could not be copied is not one we want
                # to leave behind: the transaction takes it back.
                logger.exception(
                    "Onboarding sandbox document with id %s could not be copied. Skipping.",
                    sandbox_id,
                )

    def mark_invited(self):
        """Came in through an invitation by email (see collaborator_invited)."""
        User.objects.filter(pk=self.pk).update(collaborator_invited=True)
        self.collaborator_invited = True

    def _convert_valid_invitations(self):
        """
        Convert valid invitations to document accesses.
        Expired invitations are ignored.

        Collaborators: invitations to workspaces too.
        """
        WorkspaceInvitation.convert_for(self)
        valid_invitations = Invitation.objects.filter(
            email__iexact=self.email,
            created_at__gte=(
                timezone.now()
                - timedelta(seconds=settings.INVITATION_VALIDITY_DURATION)
            ),
        ).select_related("document")

        if not valid_invitations.exists():
            return

        DocumentAccess.objects.bulk_create(
            [
                DocumentAccess(
                    user=self, document=invitation.document, role=invitation.role
                )
                for invitation in valid_invitations
            ]
        )
        self.mark_invited()

        # Set creator of documents if not yet set (e.g. documents created via server-to-server API)
        document_ids = [invitation.document_id for invitation in valid_invitations]

        Document.objects.filter(id__in=document_ids, creator__isnull=True).update(
            creator=self
        )

        valid_invitations.delete()

    def send_email(self, subject, context=None, language=None):
        """Generate and send email to the user from a template."""
        emails = [self.email]
        context = context or {}
        domain = settings.EMAIL_URL_APP or Site.objects.get_current().domain

        language = language or get_language()
        context.update(
            {
                "brandname": settings.EMAIL_BRAND_NAME,
                "domain": domain,
                "logo_img": settings.EMAIL_LOGO_IMG,
            }
        )

        with override(language):
            msg_html = render_to_string("mail/html/template.html", context)
            msg_plain = render_to_string("mail/text/template.txt", context)
            subject = str(subject)  # Force translation

            try:
                send_mail(
                    subject.capitalize(),
                    msg_plain,
                    settings.EMAIL_FROM,
                    emails,
                    html_message=msg_html,
                    fail_silently=False,
                )
            except smtplib.SMTPException as exception:
                logger.error("invitation to %s was not sent: %s", emails, exception)

    @cached_property
    def teams(self):
        """
        Get list of teams in which the user is, as a list of strings: one per
        group, one per workspace, and one per workspace the user administers.

        Read from `collaborator_teams`, kept up to date by `refresh_teams`
        whenever a membership changes, so that permission checks cost no query.
        """
        return list(self.collaborator_teams or [])

    @staticmethod
    def refresh_teams(user_id):
        """Recompute and store the teams of a user from their memberships."""
        teams = [
            make_team(TEAM_GROUP, group_id)
            for group_id in GroupMembership.objects.filter(user_id=user_id).values_list(
                "group_id", flat=True
            )
        ]
        for workspace_id, role in WorkspaceAccess.objects.filter(
            user_id=user_id
        ).values_list("workspace_id", "role"):
            teams.append(make_team(TEAM_WORKSPACE, workspace_id))
            if role in WORKSPACE_PRIVILEGED_ROLES:
                teams.append(make_team(TEAM_WORKSPACE_ADMINS, workspace_id))
        User.objects.filter(pk=user_id).update(collaborator_teams=sorted(teams))


class UserReconciliation(BaseModel):
    """Model to run batch jobs to replace an active user by another one"""

    active_email = models.EmailField(_("Active email address"))
    inactive_email = models.EmailField(_("Email address to deactivate"))
    active_email_checked = models.BooleanField(default=False)
    inactive_email_checked = models.BooleanField(default=False)
    active_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="active_user",
    )
    inactive_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="inactive_user",
    )
    active_email_confirmation_id = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False, null=True
    )
    inactive_email_confirmation_id = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False, null=True
    )
    source_unique_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("Unique ID in the source file"),
    )

    status = models.CharField(
        max_length=20,
        choices=[
            ("pending", _("Pending")),
            ("ready", _("Ready")),
            ("done", _("Done")),
            ("error", _("Error")),
        ],
        default="pending",
    )
    logs = models.TextField(blank=True)

    class Meta:
        db_table = "impress_user_reconciliation"
        verbose_name = _("user reconciliation")
        verbose_name_plural = _("user reconciliations")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Reconciliation from {self.inactive_email} to {self.active_email}"

    def save(self, *args, **kwargs):
        """
        For pending queries, identify the actual users and send validation emails
        """
        if self.status == "pending":
            self.active_user = User.objects.filter(email=self.active_email).first()
            self.inactive_user = User.objects.filter(email=self.inactive_email).first()

            if self.active_user and self.inactive_user:
                if not self.active_email_checked:
                    self.send_reconciliation_confirm_email(
                        self.active_user, "active", self.active_email_confirmation_id
                    )
                if not self.inactive_email_checked:
                    self.send_reconciliation_confirm_email(
                        self.inactive_user,
                        "inactive",
                        self.inactive_email_confirmation_id,
                    )
                self.status = "ready"
            else:
                self.status = "error"
                self.logs = "Error: Both active and inactive users need to exist."

        super().save(*args, **kwargs)

    @transaction.atomic
    def process_reconciliation_request(self):
        """
        Process the reconciliation request as a transaction.

        - Transfer document accesses from inactive to active user, updating roles as needed.
        - Transfer document favorites from inactive to active user.
        - Transfer link traces from inactive to active user.
        - Transfer comment-related content from inactive to active user
          (threads, comments and reactions)
        - Activate the active user and deactivate the inactive user.
        - Update the reconciliation entry itself.
        """

        # Prepare the data to perform the reconciliation on
        updated_accesses, removed_accesses = (
            self.prepare_documentaccess_reconciliation()
        )
        updated_linktraces, removed_linktraces = self.prepare_linktrace_reconciliation()
        update_favorites, removed_favorites = (
            self.prepare_document_favorite_reconciliation()
        )
        updated_threads = self.prepare_thread_reconciliation()
        updated_comments = self.prepare_comment_reconciliation()
        updated_reactions, removed_reactions = self.prepare_reaction_reconciliation()

        self.active_user.is_active = True
        self.inactive_user.is_active = False

        # Actually perform the bulk operations
        DocumentAccess.objects.bulk_update(updated_accesses, ["user", "role"])

        if removed_accesses:
            ids_to_delete = [entry.id for entry in removed_accesses]
            DocumentAccess.objects.filter(id__in=ids_to_delete).delete()

        # Updated in bulk, so without the signal that reports a changed access to
        # the collaboration server. Both users are concerned, the one gaining
        # the accesses and the one being deactivated: every connection of the
        # document is re-checked.
        from core.tasks.access import (  # noqa: PLC0415 # pylint: disable=import-outside-toplevel
            reset_service_connections_on_commit,
        )

        for document_id in {access.document_id for access in updated_accesses}:
            reset_service_connections_on_commit(document_id)

        DocumentFavorite.objects.bulk_update(update_favorites, ["user"])
        if removed_favorites:
            ids_to_delete = [entry.id for entry in removed_favorites]
            DocumentFavorite.objects.filter(id__in=ids_to_delete).delete()

        LinkTrace.objects.bulk_update(updated_linktraces, ["user"])
        if removed_linktraces:
            ids_to_delete = [entry.id for entry in removed_linktraces]
            LinkTrace.objects.filter(id__in=ids_to_delete).delete()

        Thread.objects.bulk_update(updated_threads, ["creator"])
        Comment.objects.bulk_update(updated_comments, ["user"])

        # pylint: disable=C0103
        ReactionThroughModel = Reaction.users.through
        reactions_to_create = []
        for updated_reaction in updated_reactions:
            reactions_to_create.append(
                ReactionThroughModel(
                    user_id=self.active_user.pk, reaction_id=updated_reaction.pk
                )
            )

        if reactions_to_create:
            ReactionThroughModel.objects.bulk_create(reactions_to_create)

        if removed_reactions:
            ids_to_delete = [entry.id for entry in removed_reactions]
            ReactionThroughModel.objects.filter(
                reaction_id__in=ids_to_delete, user_id=self.inactive_user.pk
            ).delete()

        User.objects.bulk_update([self.active_user, self.inactive_user], ["is_active"])

        # Wrap up the reconciliation entry
        self.logs += f"""Requested update for {len(updated_accesses)} DocumentAccess items
            and deletion for {len(removed_accesses)} DocumentAccess items.\n"""
        self.status = "done"
        self.save()

        self.send_reconciliation_done_email()

    def prepare_documentaccess_reconciliation(self):
        """
        Prepare the reconciliation by transferring document accesses from the inactive user
        to the active user.
        """
        updated_accesses = []
        removed_accesses = []
        inactive_accesses = DocumentAccess.objects.filter(user=self.inactive_user)

        # Check documents where the active user already has access
        inactive_accesses_documents = inactive_accesses.values_list(
            "document", flat=True
        )
        existing_accesses = DocumentAccess.objects.filter(user=self.active_user).filter(
            document__in=inactive_accesses_documents
        )
        existing_roles_per_doc = dict(existing_accesses.values_list("document", "role"))

        for entry in inactive_accesses:
            if entry.document_id in existing_roles_per_doc:
                # Update role if needed
                existing_role = existing_roles_per_doc[entry.document_id]
                max_role = RoleChoices.max(entry.role, existing_role)
                if existing_role != max_role:
                    existing_access = existing_accesses.get(document=entry.document)
                    existing_access.role = max_role
                    updated_accesses.append(existing_access)
                removed_accesses.append(entry)
            else:
                entry.user = self.active_user
                updated_accesses.append(entry)

        return updated_accesses, removed_accesses

    def prepare_document_favorite_reconciliation(self):
        """
        Prepare the reconciliation by transferring document favorites from the inactive user
        to the active user.
        """
        updated_favorites = []
        removed_favorites = []

        existing_favorites = DocumentFavorite.objects.filter(user=self.active_user)
        existing_favorite_doc_ids = set(
            existing_favorites.values_list("document_id", flat=True)
        )

        inactive_favorites = DocumentFavorite.objects.filter(user=self.inactive_user)

        for entry in inactive_favorites:
            if entry.document_id in existing_favorite_doc_ids:
                removed_favorites.append(entry)
            else:
                entry.user = self.active_user
                updated_favorites.append(entry)

        return updated_favorites, removed_favorites

    def prepare_linktrace_reconciliation(self):
        """
        Prepare the reconciliation by transferring link traces from the inactive user
        to the active user.
        """
        updated_linktraces = []
        removed_linktraces = []

        existing_linktraces = LinkTrace.objects.filter(user=self.active_user)
        inactive_linktraces = LinkTrace.objects.filter(user=self.inactive_user)

        for entry in inactive_linktraces:
            if existing_linktraces.filter(document=entry.document).exists():
                removed_linktraces.append(entry)
            else:
                entry.user = self.active_user
                updated_linktraces.append(entry)

        return updated_linktraces, removed_linktraces

    def prepare_thread_reconciliation(self):
        """
        Prepare the reconciliation by transferring threads from the inactive user
        to the active user.
        """
        updated_threads = []

        inactive_threads = Thread.objects.filter(creator=self.inactive_user)

        for entry in inactive_threads:
            entry.creator = self.active_user
            updated_threads.append(entry)

        return updated_threads

    def prepare_comment_reconciliation(self):
        """
        Prepare the reconciliation by transferring comments from the inactive user
        to the active user.
        """
        updated_comments = []

        inactive_comments = Comment.objects.filter(user=self.inactive_user)

        for entry in inactive_comments:
            entry.user = self.active_user
            updated_comments.append(entry)

        return updated_comments

    def prepare_reaction_reconciliation(self):
        """
        Prepare the reconciliation by creating missing reactions for the active user
        (ie, the ones that exist for the inactive user but not the active user)
        and then deleting all reactions of the inactive user.
        """

        inactive_reactions = Reaction.objects.filter(users=self.inactive_user)
        updated_reactions = inactive_reactions.exclude(users=self.active_user)

        return updated_reactions, inactive_reactions

    def send_reconciliation_confirm_email(
        self, user, user_type, confirmation_id, language=None
    ):
        """Method allowing to send confirmation email for reconciliation requests."""
        language = language or get_language()
        domain = settings.EMAIL_URL_APP or Site.objects.get_current().domain

        message = _(
            """You have requested a reconciliation of your user accounts on Docs.
            To confirm that you are the one who initiated the request
            and that this email belongs to you:"""
        )

        with override(language):
            subject = _("Confirm by clicking the link to start the reconciliation")
            context = {
                "title": subject,
                "message": message,
                "link": f"{domain}/user-reconciliations/{user_type}/{confirmation_id}/",
                "link_label": str(_("Click here")),
                "button_label": str(_("Confirm")),
            }

        user.send_email(subject, context, language)

    def send_reconciliation_done_email(self, language=None):
        """Method allowing to send done email for reconciliation requests."""
        language = language or get_language()
        domain = settings.EMAIL_URL_APP or Site.objects.get_current().domain

        message = _(
            """Your reconciliation request has been processed.
            New documents are likely associated with your account:"""
        )

        with override(language):
            subject = _("Your accounts have been merged")
            context = {
                "title": subject,
                "message": message,
                "link": f"{domain}/",
                "link_label": str(_("Click here to see")),
                "button_label": str(_("See my pages")),
            }

        self.active_user.send_email(subject, context, language)


class UserReconciliationCsvImport(BaseModel):
    """Model to import reconciliations requests from an external source
    (eg, )"""

    file = models.FileField(upload_to="imports/", verbose_name=_("CSV file"))
    status = models.CharField(
        max_length=20,
        choices=[
            ("pending", _("Pending")),
            ("running", _("Running")),
            ("done", _("Done")),
            ("error", _("Error")),
        ],
        default="pending",
    )
    logs = models.TextField(blank=True)

    class Meta:
        db_table = "impress_user_reconciliation_csv_import"
        verbose_name = _("user reconciliation CSV import")
        verbose_name_plural = _("user reconciliation CSV imports")

    def __str__(self):
        return f"User reconciliation CSV import {self.id}"

    def send_email(self, subject, emails, context=None, language=None):
        """Generate and send email to the user from a template."""
        context = context or {}
        domain = settings.EMAIL_URL_APP or Site.objects.get_current().domain
        language = language or get_language()
        context.update(
            {
                "brandname": settings.EMAIL_BRAND_NAME,
                "domain": domain,
                "logo_img": settings.EMAIL_LOGO_IMG,
            }
        )

        with override(language):
            msg_html = render_to_string("mail/html/template.html", context)
            msg_plain = render_to_string("mail/text/template.txt", context)
            subject = str(subject)  # Force translation

            try:
                send_mail(
                    subject.capitalize(),
                    msg_plain,
                    settings.EMAIL_FROM,
                    emails,
                    html_message=msg_html,
                    fail_silently=False,
                )
            except smtplib.SMTPException as exception:
                logger.error("invitation to %s was not sent: %s", emails, exception)

    def send_reconciliation_error_email(
        self, recipient_email, other_email, language=None
    ):
        """Method allowing to send email for reconciliation requests with errors."""
        language = language or get_language()

        emails = [recipient_email]

        message = _(
            """Your request for reconciliation was unsuccessful.
            Reconciliation failed for the following email addresses:
            {recipient_email}, {other_email}.
            Please check for typos.
            You can submit another request with the valid email addresses."""
        ).format(recipient_email=recipient_email, other_email=other_email)

        with override(language):
            subject = _("Reconciliation of your Docs accounts not completed")
            context = {
                "title": subject,
                "message": message,
                "link": settings.USER_RECONCILIATION_FORM_URL,
                "link_label": str(_("Click here")),
                "button_label": str(_("Make a new request")),
            }

        self.send_email(subject, emails, context, language)


class BaseAccess(BaseModel):
    """Base model for accesses to handle resources."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    team = models.CharField(max_length=100, blank=True)
    role = models.CharField(
        max_length=20, choices=RoleChoices.choices, default=RoleChoices.READER
    )

    class Meta:
        abstract = True


class DocumentQuerySet(MP_NodeQuerySet):
    """
    Custom queryset for the Document model, providing additional methods
    to filter documents based on user permissions.
    """

    def readable_per_se(self, user):
        """
        Filters the queryset to return documents on which the given user has
        direct access, team access or link access. This will not return all the
        documents that a user can read because it can be obtained via an ancestor.
        :param user: The user for whom readable documents are to be fetched.
        :return: A queryset of documents for which the user has direct access,
            team access or link access.
        """
        return self.filter(role_readable_q(user) | link_readable_q(user))

    def readable_by_role(self, user):
        """Collaborators: readable through a role (on it, or by a link)."""
        return self.filter(role_readable_q(user))

    def readable_by_link(self, user):
        """Collaborators: readable through its link reach alone."""
        return self.filter(link_readable_q(user))

    def exclude_private_unreadable(self, user):
        """
        Leave out the pages kept private that the user can't open: they have
        no access to them (nor above them) and the page's own link is closed.
        """
        if not user.is_authenticated:
            return self.exclude(
                models.Q(keep_private=True)
                & ~models.Q(link_reach=LinkReachChoices.PUBLIC)
                # Collaborators: nor public through a space it is linked into
                & ~models.Q(linked_link_reach=LinkReachChoices.PUBLIC)
            )
        has_role = DocumentAccess.objects.filter(
            models.Q(user=user) | models.Q(team__in=user.teams),
            document__path=Left(models.OuterRef("path"), Length("document__path")),
        )
        return self.exclude(
            models.Q(keep_private=True)
            & models.Q(link_reach=LinkReachChoices.RESTRICTED)
            & models.Q(linked_link_reach=LinkReachChoices.RESTRICTED)
            & ~models.Exists(has_role)
            # Collaborators: read through a space it is linked into (it, or a
            # page above it, as `get_role` grants)
            & ~models.Exists(linked_reader_access(user))
        )

    def annotate_is_favorite(self, user):
        """
        Annotate document queryset with the favorite status for the current user.
        """
        if user.is_authenticated:
            favorite_exists_subquery = DocumentFavorite.objects.filter(
                document_id=models.OuterRef("pk"), user=user
            )
            return self.annotate(is_favorite=models.Exists(favorite_exists_subquery))

        return self.annotate(is_favorite=models.Value(False))

    def annotate_user_roles(self, user):
        """
        Annotate document queryset with the roles of the current user
        on the document or its ancestors.
        """
        output_field = ArrayField(base_field=models.CharField())

        if user.is_authenticated:
            user_roles_subquery = DocumentAccess.objects.filter(
                models.Q(user=user) | models.Q(team__in=user.teams),
                document__path=Left(models.OuterRef("path"), Length("document__path")),
            ).values_list("role", flat=True)
            roles = models.Func(
                user_roles_subquery, function="ARRAY", output_field=output_field
            )

            # Pages linked into a space the user has a role on: reader too
            return self.annotate(
                user_roles=models.Case(
                    models.When(
                        models.Exists(linked_reader_access(user)),
                        then=models.Func(
                            roles,
                            models.Value(
                                [RoleChoices.READER], output_field=output_field
                            ),
                            function="array_cat",
                            output_field=output_field,
                        ),
                    ),
                    default=roles,
                    output_field=output_field,
                )
            )

        return self.annotate(
            user_roles=models.Value([], output_field=output_field),
        )

    def annotate_user_has_link_trace(self, user):
        """
        Annotate document queryset with a boolean to know if the current user
        has a link_trace on the current document.
        """

        if user.is_authenticated:
            link_trace_exists_subquery = LinkTrace.objects.filter(
                document_id=models.OuterRef("pk"), user=user
            )
            return self.annotate(
                user_has_link_trace=models.Exists(link_trace_exists_subquery)
            )

        return self.annotate(user_has_link_trace=models.Value(False))


class DocumentManager(MP_NodeManager.from_queryset(DocumentQuerySet)):
    """
    Custom manager for the Document model, enabling the use of the custom
    queryset methods directly from the model manager.
    """

    def get_queryset(self):
        """Sets the custom queryset as the default."""
        return self._queryset_class(self.model).order_by("path")


# pylint: disable=too-many-public-methods
class Document(MP_Node, BaseModel):
    """Pad document, the content of which lives in the collaboration server."""

    title = models.CharField(_("title"), max_length=255, null=True, blank=True)
    kind = models.CharField(
        max_length=10,
        choices=DocumentKindChoices.choices,
        default=DocumentKindChoices.PAGE,
    )
    excerpt = models.TextField(_("excerpt"), max_length=300, null=True, blank=True)
    link_reach = models.CharField(
        max_length=20,
        choices=LinkReachChoices.choices,
        default=LinkReachChoices.RESTRICTED,
    )
    link_role = models.CharField(
        max_length=20, choices=LinkRoleChoices.choices, default=LinkRoleChoices.READER
    )
    # Publishing (Collaborators). A page kept private inherits no link access
    # (public, or any signed-in collaborator) from the pages above it: it is
    # left out of a published wiki and of a published page's sub-pages.
    keep_private = models.BooleanField(default=False)
    # Let search engines index the page when it is public
    allow_indexing = models.BooleanField(default=False)
    # Collaborators: a space's link before it was published as a wiki, given
    # back when the wiki is unpublished
    pre_wiki_link_reach = models.CharField(
        max_length=20, choices=LinkReachChoices.choices, null=True, blank=True
    )
    pre_wiki_link_role = models.CharField(
        max_length=20, choices=LinkRoleChoices.choices, null=True, blank=True
    )
    # Collaborators: the widest link of the spaces the page is linked into
    # (PageSpaceLink), kept up to date by `refresh_linked_reach`. It reaches
    # the page and the pages below it, as its own link does, down to a page
    # kept private
    linked_link_reach = models.CharField(
        max_length=20,
        choices=LinkReachChoices.choices,
        default=LinkReachChoices.RESTRICTED,
    )
    linked_link_role = models.CharField(
        max_length=20, choices=LinkRoleChoices.choices, default=LinkRoleChoices.READER
    )
    # A space published as a wiki, at /wiki/<slug>, in its accent colour
    wiki_slug = models.SlugField(max_length=100, unique=True, null=True, blank=True)
    wiki_accent = models.CharField(max_length=7, blank=True, default="")
    # The wiki's logo: the address of an image attached to the space
    wiki_logo = models.CharField(max_length=500, blank=True, default="")
    # A domain of its own (e.g. help.example.com), pointed at Collaborators
    wiki_domain = models.CharField(max_length=253, unique=True, null=True, blank=True)
    # A fixed version readers see instead of the live pages, if published
    wiki_release = models.ForeignKey(
        "WikiRelease",
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )
    # The page's text, as the collaboration server last saved it, for the
    # full-text search of wikis (refreshed when its content changes)
    text_content = models.TextField(blank=True, default="")
    # Collaborators: taken down by a platform administrator after a report
    # (core.reports): in the trash, and its owners can't restore it
    taken_down_at = models.DateTimeField(null=True, blank=True)
    text_updated_at = models.DateTimeField(null=True, blank=True)
    creator = models.ForeignKey(
        User,
        on_delete=models.RESTRICT,
        related_name="documents_created",
        blank=True,
        null=True,
    )
    deleted_at = models.DateTimeField(null=True, blank=True)
    ancestors_deleted_at = models.DateTimeField(null=True, blank=True)
    has_deleted_children = models.BooleanField(default=False)
    duplicated_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="duplicates",
        editable=False,
        blank=True,
        null=True,
    )
    attachments = ArrayField(
        models.CharField(max_length=255),
        default=list,
        editable=False,
        blank=True,
        null=True,
    )

    # Tree structure
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    steplen = 7  # nb siblings max: 3,521,614,606,208
    node_order_by = []  # Manual ordering

    path = models.CharField(max_length=7 * 36, unique=True, db_collation="C")

    objects = DocumentManager()

    class Meta:
        db_table = "impress_document"
        ordering = ("path",)
        verbose_name = _("Document")
        verbose_name_plural = _("Documents")
        indexes = [
            # Used by media-auth to find the document(s) holding an attachment
            # key without scanning the table (attachments @> [key]).
            GinIndex(fields=["attachments"], name="document_attachments_gin"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(deleted_at__isnull=True)
                    | models.Q(deleted_at=models.F("ancestors_deleted_at"))
                ),
                name="check_deleted_at_matches_ancestors_deleted_at_when_set",
            ),
        ]

    def __str__(self):
        return str(self.title) if self.title else str(_("Untitled page"))

    def __init__(self, *args, **kwargs):
        """Initialize cache property."""
        super().__init__(*args, **kwargs)
        self._ancestors_link_definition = None
        self._computed_link_definition = None

    def clean(self):
        """A space is always the root of its tree of pages."""
        super().clean()
        if self.kind == DocumentKindChoices.SPACE and self.depth and self.depth > 1:
            raise ValidationError({"kind": _("A space must be a top-level page.")})

    @property
    def is_space(self):
        """True if the document is the root of a space."""
        return self.kind == DocumentKindChoices.SPACE

    def is_leaf(self):
        """
        :returns: True if the node is has no children
        """
        return not self.has_deleted_children and self.numchild == 0

    @property
    def key_base(self):
        """Key base of the location where the document is stored in object storage."""
        if not self.pk:
            raise RuntimeError(
                "The document instance must be saved before requesting a storage key."
            )
        return str(self.pk)

    @property
    def file_key(self):
        """
        Key of the legacy object storage file that used to hold the content.

        The collaboration server owns the content now, and Django neither reads
        nor writes this object any more. The key outlives it: the collaboration
        server seeds a room from that object on first access and replays its
        versions to rebuild the history, and `clean_document` purges it so that
        a document it reset cannot be seeded back from what it left behind.
        """
        return f"{self.key_base}/file"

    def get_self_and_ancestors_paths(self):
        """
        Return the paths of the document and of all its ancestors, computed from
        the materialized path without querying the database.

        Filtering on `path__in` with this list hits the unique index on `path`,
        whereas comparing `path` with `LEFT(value, LENGTH(path))` forces a
        sequential scan of the whole table.
        """
        return [
            self.path[:pos]
            for pos in range(self.steplen, len(self.path) + 1, self.steplen)
        ]

    def get_nb_accesses_cache_key(self):
        """Generate a unique cache key for each document."""
        return f"document_{self.id!s}_nb_accesses"

    def get_nb_accesses(self):
        """
        Calculate the number of accesses:
        - directly attached to the document
        - attached to any of the document's ancestors
        """
        cache_key = self.get_nb_accesses_cache_key()
        nb_accesses = cache.get(cache_key)

        if nb_accesses is None:
            nb_accesses = (
                DocumentAccess.objects.filter(document=self).count(),
                DocumentAccess.objects.filter(
                    document__path__in=self.get_self_and_ancestors_paths(),
                    document__ancestors_deleted_at__isnull=True,
                ).count(),
            )
            cache.set(
                cache_key, nb_accesses, settings.DOCUMENT_NB_ACCESSES_CACHE_TIMEOUT
            )

        return nb_accesses

    @property
    def nb_accesses_direct(self):
        """Returns the number of accesses related to the document or one of its ancestors."""
        return self.get_nb_accesses()[0]

    @property
    def nb_accesses_ancestors(self):
        """Returns the number of accesses related to the document or one of its ancestors."""
        return self.get_nb_accesses()[1]

    # the link definition as it was loaded from, or saved to, the database
    _saved_link_definition = None

    @classmethod
    def from_db(cls, db, field_names, values):
        """Load a document, remembering its link definition to spot its changes."""
        instance = super().from_db(db, field_names, values)
        instance.remember_link_definition()  # pylint: disable=no-member
        return instance

    def refresh_from_db(self, *args, **kwargs):
        """
        Reload a document, taking a new snapshot of the link fields reloaded.

        Django reloads a single field this way when a deferred one is read:
        the other one keeps its snapshot, its value in memory may be unsaved.
        """
        super().refresh_from_db(*args, **kwargs)
        # `fields` is the second positional argument of Django's signature
        fields = kwargs.get("fields", args[1] if len(args) > 1 else None)
        if fields is None or {"link_reach", "link_role"} & set(fields):
            self.remember_link_definition(fields)

    def remember_link_definition(self, fields=None):
        """
        Snapshot the link definition as it is in the database.

        Read from the instance's own state so that a deferred field is not
        loaded for it; a field not loaded is remembered as unknown. Naming
        `fields` restricts the snapshot to the link fields among them, the
        others keep what was remembered of them.
        """
        reach, role, private = self._saved_link_definition or (None, None, None)
        if fields is None or "link_reach" in fields:
            reach = self.__dict__.get("link_reach")
        if fields is None or "link_role" in fields:
            role = self.__dict__.get("link_role")
        if fields is None or "keep_private" in fields:
            private = self.__dict__.get("keep_private")
        self._saved_link_definition = (reach, role, private)

    def link_definition_changed(self):
        """
        Tell whether `link_reach` or `link_role` differ from the last snapshot.

        A document that was never loaded from the database, nor saved, is
        reported as changed: nothing is known of what its link definition was.
        """
        if self._saved_link_definition is None:
            return True
        return self._saved_link_definition != (
            self.link_reach,
            self.link_role,
            self.keep_private,
        )

    def invalidate_nb_accesses_cache(self):
        """
        Invalidate the cache for number of accesses, including on affected descendants.
        Args:
            path: can optionally be passed as argument (useful when invalidating cache for a
                document we just deleted)
        """

        for document in Document.objects.filter(path__startswith=self.path).only("id"):
            cache_key = document.get_nb_accesses_cache_key()
            cache.delete(cache_key)

    def get_role(self, user):
        """Return the roles a user has on a document."""
        if not user.is_authenticated:
            return None

        try:
            roles = self.user_roles or []
        except AttributeError:
            paths = self.get_self_and_ancestors_paths()
            # Linked into a space the user has a role on: reader too (in the
            # same query)
            linked = (
                PageSpaceLink.objects.filter(
                    models.Q(space__accesses__user=user)
                    | models.Q(space__accesses__team__in=user.teams),
                    page__path__in=paths,
                    space__ancestors_deleted_at__isnull=True,
                )
                .annotate(
                    linked_role=models.Value(
                        RoleChoices.READER, output_field=models.CharField()
                    )
                )
                .values_list("linked_role", flat=True)
            )
            roles = (
                DocumentAccess.objects.filter(
                    models.Q(user=user) | models.Q(team__in=user.teams),
                    document__path__in=paths,
                )
                .values_list("role", flat=True)
                .union(linked, all=True)
            )

        return RoleChoices.max(*roles)

    def has_link_trace(self, user):
        """Return if the user has a link trace on this document."""

        if not user.is_authenticated:
            return False

        try:
            return self.user_has_link_trace
        except AttributeError:
            return LinkTrace.objects.filter(document=self, user=user).exists()

    def compute_ancestors_links_paths_mapping(self):
        """
        Compute the ancestors links for the current document up to the highest readable ancestor.
        """
        ancestors = (
            (self.get_ancestors() | self._meta.model.objects.filter(pk=self.pk))
            .filter(ancestors_deleted_at__isnull=True)
            .order_by("path")
        )
        ancestors_links = []
        paths_links_mapping = {}

        for ancestor in ancestors:
            if ancestor.keep_private:
                # nothing above a page kept private reaches it
                ancestors_links = []
            ancestors_links.extend(ancestor.own_link_definitions)
            paths_links_mapping[ancestor.path] = ancestors_links.copy()

        return paths_links_mapping

    @property
    def own_link_definitions(self):
        """
        Collaborators: the links the document gives itself and the pages
        below it: its own, and that of the spaces it is linked into.
        """
        definitions = [self.link_definition]
        if self.linked_link_reach != LinkReachChoices.RESTRICTED:
            definitions.append(
                {
                    "link_reach": self.linked_link_reach,
                    "link_role": self.linked_link_role,
                }
            )
        return definitions

    @property
    def link_definition(self):
        """Returns link reach/role as a definition in dictionary format."""
        return {"link_reach": self.link_reach, "link_role": self.link_role}

    @property
    def ancestors_link_definition(self):
        """Link definition equivalent to all document's ancestors."""
        if self.keep_private:
            return get_equivalent_link_definition([])
        if getattr(self, "_ancestors_link_definition", None) is None:
            if self.depth <= 1:
                ancestors_links = []
            else:
                mapping = self.compute_ancestors_links_paths_mapping()
                ancestors_links = mapping.get(self.path[: -self.steplen], [])
            self._ancestors_link_definition = get_equivalent_link_definition(
                ancestors_links
            )

        return self._ancestors_link_definition

    @ancestors_link_definition.setter
    def ancestors_link_definition(self, definition):
        """Cache the ancestors_link_definition."""
        self._ancestors_link_definition = definition

    @property
    def ancestors_link_reach(self):
        """Link reach equivalent to all document's ancestors."""
        return self.ancestors_link_definition["link_reach"]

    @property
    def ancestors_link_role(self):
        """Link role equivalent to all document's ancestors."""
        return self.ancestors_link_definition["link_role"]

    @property
    def computed_link_definition(self):
        """
        Link reach/role on the document, combining inherited ancestors' link
        definitions and the document's own link definition.
        """
        if getattr(self, "_computed_link_definition", None) is None:
            self._computed_link_definition = get_equivalent_link_definition(
                [self.ancestors_link_definition, self.link_definition]
            )
        return self._computed_link_definition

    @property
    def computed_link_reach(self):
        """Actual link reach on the document."""
        return self.computed_link_definition["link_reach"]

    @property
    def computed_link_role(self):
        """Actual link role on the document."""
        return self.computed_link_definition["link_role"]

    def get_abilities(self, user):  # pylint: disable=too-many-locals
        """
        Compute and return abilities for a given user on the document.
        """
        # First get the role based on specific access
        role = self.get_role(user)

        # Characteristics that are based only on specific access
        is_owner = role == RoleChoices.OWNER
        is_deleted = self.ancestors_deleted_at
        is_owner_or_admin = (is_owner or role == RoleChoices.ADMIN) and not is_deleted

        # Compute access roles before adding link roles because we don't
        # want anonymous users to access versions (we wouldn't know from
        # which date to allow them anyway)
        # Anonymous users should also not see document accesses
        #
        # This is what `versions_list` reports. The history itself lives in the
        # collaboration server, which reads the ability to decide whether to ask
        # this backend for the caller's access — the `created_at` it answers with
        # bounds what it serves. So the ability and `accesses/me/` have to agree,
        # and a test holds them to it
        # (test_api_document_accesses_me_agrees_with_the_versions_list_ability).
        has_access_role = bool(role) and not is_deleted
        can_update_from_access = (
            is_owner_or_admin or role == RoleChoices.EDITOR
        ) and not is_deleted

        # compute can_leave
        # An authenticated user can leave a document if it has a non
        # privileged role on the document or access to it with a link_trace
        can_leave = (
            user.is_authenticated
            and not is_deleted
            and (
                (has_access_role and not is_owner_or_admin)
                or (not has_access_role and self.has_link_trace(user))
            )
        )

        link_select_options = LinkReachChoices.get_select_options(
            **self.ancestors_link_definition
        )
        link_definition = get_equivalent_link_definition(
            # Collaborators: the spaces it is linked into too
            [self.ancestors_link_definition, *self.own_link_definitions]
        )

        link_reach = link_definition["link_reach"]
        if link_reach == LinkReachChoices.PUBLIC or (
            link_reach == LinkReachChoices.AUTHENTICATED and user.is_authenticated
        ):
            role = RoleChoices.max(role, link_definition["link_role"])

        can_get = bool(role) and not is_deleted
        retrieve = can_get or is_owner
        can_update = (
            is_owner_or_admin or role == RoleChoices.EDITOR
        ) and not is_deleted
        can_comment = (can_update or role == RoleChoices.COMMENTER) and not is_deleted
        can_create_children = can_update and user.is_authenticated
        can_destroy = (
            is_owner
            if self.is_root()
            else (is_owner_or_admin or (user.is_authenticated and self.creator == user))
        ) and not is_deleted

        ai_allow_reach_from = settings.AI_ALLOW_REACH_FROM
        ai_access = any(
            [
                ai_allow_reach_from == LinkReachChoices.PUBLIC and can_update,
                ai_allow_reach_from == LinkReachChoices.AUTHENTICATED
                and user.is_authenticated
                and can_update,
                ai_allow_reach_from == LinkReachChoices.RESTRICTED
                and can_update_from_access,
            ]
        )

        return {
            "accesses_manage": is_owner_or_admin,
            "accesses_view": has_access_role,
            "ai_proxy": ai_access,
            "ai_transform": ai_access,
            "ai_translate": ai_access,
            "attachment_upload": can_update,
            "media_check": can_get,
            "children_list": can_get,
            "children_create": can_create_children,
            "collaboration_auth": can_get,
            "comment": can_comment,
            "formatted_content": can_get,
            "cors_proxy": can_get,
            "descendants": can_get,
            "destroy": can_destroy,
            "duplicate": can_get and user.is_authenticated,
            "favorite": can_get and user.is_authenticated,
            "link_configuration": is_owner_or_admin,
            "invite_owner": is_owner and not is_deleted,
            "leave": can_leave,
            "mention": has_access_role and can_comment,
            "move": is_owner_or_admin and not is_deleted,
            "partial_update": can_update,
            "restore": is_owner and bool(self.deleted_at),
            "retrieve": retrieve,
            "media_auth": can_get,
            "link_select_options": link_select_options,
            "tree": retrieve,
            "update": can_update,
            "versions_list": has_access_role,
            "search": can_get,
        }

    @property
    def app_path(self):
        """Collaborators: a space lives at /space/<id>/, a page at /page/<id>/."""
        return "space" if self.kind == DocumentKindChoices.SPACE else "page"

    def send_email(self, subject, emails, context=None, language=None):
        """Generate and send email from a template.

        Keys passed in `context` take precedence over the default values.
        """
        domain = settings.EMAIL_URL_APP or Site.objects.get_current().domain
        language = language or get_language()
        context = {
            "brandname": settings.EMAIL_BRAND_NAME,
            "document": self,
            "domain": domain,
            "link": f"{domain}/{self.app_path}/{self.id}/?utm_source=docssharelink&utm_campaign={self.id}",
            "link_label": self.title or str(_("Untitled page")),
            "button_label": _("Open"),
            "logo_img": settings.EMAIL_LOGO_IMG,
            **(context or {}),
        }

        with override(language):
            msg_html = render_to_string("mail/html/template.html", context)
            msg_plain = render_to_string("mail/text/template.txt", context)
            subject = str(subject)  # Force translation

            try:
                send_mail(
                    subject.capitalize(),
                    msg_plain,
                    settings.EMAIL_FROM,
                    emails,
                    html_message=msg_html,
                    fail_silently=False,
                )
            except smtplib.SMTPException as exception:
                logger.error("invitation to %s was not sent: %s", emails, exception)

    def send_invitation_email(self, email, role, sender, language=None, link=None):
        """
        Method allowing a user to send an email invitation to another user for a document.

        Collaborators: `link`, to the page accepting an invitation by email.
        """
        language = language or get_language()
        role = RoleChoices(role).label
        sender_name = sender.full_name or sender.email
        sender_name_email = (
            f"{sender.full_name:s} ({sender.email})"
            if sender.full_name
            else sender.email
        )

        with override(language):
            context = {
                **(
                    {"link": link, "button_label": _("Accept the invitation")}
                    if link
                    else {}
                ),
                "title": _("{name} shared a page with you!").format(name=sender_name),
                "message": _(
                    '{name} invited you with the role "{role}" on the following document:'
                ).format(name=sender_name_email, role=role.lower()),
            }
            subject = (
                context["title"]
                if not self.title
                else _("{name} shared a page with you: {title}").format(
                    name=sender_name, title=self.title
                )
            )

        self.send_email(subject, [email], context, language)

    @transaction.atomic
    def soft_delete(self):
        """
        Soft delete the document, marking the deletion on descendants.
        We still keep the .delete() method untouched for programmatic purposes.
        """
        if (
            self._meta.model.objects.filter(
                models.Q(deleted_at__isnull=False)
                | models.Q(ancestors_deleted_at__isnull=False),
                pk=self.pk,
            ).exists()
            or self.get_ancestors().filter(deleted_at__isnull=False).exists()
        ):
            raise RuntimeError(
                "This document is already deleted or has deleted ancestors."
            )

        self.ancestors_deleted_at = self.deleted_at = timezone.now()
        self.save()
        self.invalidate_nb_accesses_cache()

        if self.depth > 1:
            self._meta.model.objects.filter(pk=self.get_parent().pk).update(
                numchild=models.F("numchild") - 1,
                has_deleted_children=True,
            )

        # Mark all descendants as soft deleted
        self.get_descendants().filter(ancestors_deleted_at__isnull=True).update(
            ancestors_deleted_at=self.ancestors_deleted_at,
            updated_at=self.updated_at,
        )

    @transaction.atomic
    def restore(self):
        """Cancelling a soft delete with checks."""
        # This should not happen
        if self._meta.model.objects.filter(
            pk=self.pk, deleted_at__isnull=True
        ).exists():
            raise RuntimeError("This document is not deleted.")

        if self.deleted_at < get_trashbin_cutoff():
            raise RuntimeError(
                "This document was permanently deleted and cannot be restored."
            )
        # Collaborators: only a platform administrator puts it back
        if self.taken_down_at:
            raise RuntimeError(
                "A platform administrator took this page down after a report."
            )

        # save the current deleted_at value to exclude it from the descendants update
        current_deleted_at = self.deleted_at

        # Restore the current document
        self.deleted_at = None

        # Calculate the minimum `deleted_at` among all ancestors
        ancestors_deleted_at = (
            self.get_ancestors()
            .filter(deleted_at__isnull=False)
            .order_by("deleted_at")
            .values_list("deleted_at", flat=True)
            .first()
        )
        self.ancestors_deleted_at = ancestors_deleted_at
        self.save(update_fields=["deleted_at", "ancestors_deleted_at"])
        self.invalidate_nb_accesses_cache()

        self.get_descendants().exclude(
            models.Q(deleted_at__isnull=False)
            | models.Q(ancestors_deleted_at__lt=current_deleted_at)
        ).update(ancestors_deleted_at=self.ancestors_deleted_at)

        if self.depth > 1:
            self._meta.model.objects.filter(pk=self.get_parent().pk).update(
                numchild=models.F("numchild") + 1
            )


class LinkTrace(BaseModel):
    """
    Relation model to trace accesses to a document via a link by a logged-in user.
    This is necessary to show the document in the user's list of documents even
    though the user does not have a role on the document.
    """

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="link_traces",
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="link_traces")

    class Meta:
        db_table = "impress_link_trace"
        verbose_name = _("Document/user link trace")
        verbose_name_plural = _("Document/user link traces")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "document"],
                name="unique_link_trace_document_user",
                violation_error_message=_(
                    "A link trace already exists for this document/user."
                ),
            ),
        ]

    def __str__(self):
        return f"{self.user!s} trace on document {self.document!s}"


class DocumentFavorite(BaseModel):
    """Relation model to store a user's favorite documents."""

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="favorited_by_users",
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="favorite_documents"
    )

    class Meta:
        db_table = "impress_document_favorite"
        verbose_name = _("Document favorite")
        verbose_name_plural = _("Document favorites")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "document"],
                name="unique_document_favorite_user",
                violation_error_message=_(
                    "This document is already targeted by a favorite relation instance "
                    "for the same user."
                ),
            ),
        ]

    def __str__(self):
        return f"{self.user!s} favorite on document {self.document!s}"


class DocumentAccess(BaseAccess):
    """Relation model to give access to a document for a user or a team with a role."""

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="accesses",
    )

    class Meta:
        db_table = "impress_document_access"
        ordering = ("-created_at",)
        verbose_name = _("Document/user relation")
        verbose_name_plural = _("Document/user relations")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "document"],
                condition=models.Q(user__isnull=False),  # Exclude null users
                name="unique_document_user",
                violation_error_message=_("This user is already in this document."),
            ),
            models.UniqueConstraint(
                fields=["team", "document"],
                condition=models.Q(team__gt=""),  # Exclude empty string teams
                name="unique_document_team",
                violation_error_message=_("This team is already in this document."),
            ),
            models.CheckConstraint(
                condition=models.Q(user__isnull=False, team="")
                | models.Q(user__isnull=True, team__gt=""),
                name="check_document_access_either_user_or_team",
                violation_error_message=_("Either user or team must be set, not both."),
            ),
        ]

    def __str__(self):
        return f"{self.user!s} is {self.role:s} in document {self.document!s}"

    def save(self, *args, **kwargs):
        """Override save to clear the document's cache for number of accesses."""
        super().save(*args, **kwargs)
        self.document.invalidate_nb_accesses_cache()

    @property
    def target_key(self):
        """Get a unique key for the actor targeted by the access, without possible conflict."""
        return f"user:{self.user_id!s}" if self.user_id else f"team:{self.team:s}"

    def delete(self, *args, **kwargs):
        """Override delete to clear the document's cache for number of accesses."""
        super().delete(*args, **kwargs)
        self.document.invalidate_nb_accesses_cache()

    def set_user_roles_tuple(self, ancestors_role, current_role):
        """
        Set a precomputed (ancestor_role, current_role) tuple for this instance.

        This avoids querying the database in `get_roles_tuple()` and is useful
        when roles are already known, such as in bulk serialization.

        Args:
            ancestor_role (str | None): Highest role on any ancestor document.
            current_role (str | None): Role on the current document.
        """
        # pylint: disable=attribute-defined-outside-init
        self._prefetched_user_roles_tuple = (ancestors_role, current_role)

    def get_user_roles_tuple(self, user):
        """
        Return a tuple of:
        - the highest role the user has on any ancestor of the document
        - the role the user has on the current document

        If roles have been explicitly set using `set_user_roles_tuple()`,
        those will be returned instead of querying the database.

        This allows viewsets or serializers to precompute roles for performance
        when handling multiple documents at once.

        Args:
            user (User): The user whose roles are being evaluated.

        Returns:
            tuple[str | None, str | None]: (max_ancestor_role, current_document_role)
        """
        if not user.is_authenticated:
            return None, None

        try:
            return self._prefetched_user_roles_tuple
        except AttributeError:
            pass

        ancestors = (
            self.document.get_ancestors() | Document.objects.filter(pk=self.document_id)
        ).filter(ancestors_deleted_at__isnull=True)

        access_tuples = DocumentAccess.objects.filter(
            models.Q(user=user) | models.Q(team__in=user.teams),
            document__in=ancestors,
        ).values_list("document_id", "role")

        ancestors_roles = []
        current_roles = []
        for doc_id, role in access_tuples:
            if doc_id == self.document_id:
                current_roles.append(role)
            else:
                ancestors_roles.append(role)

        return RoleChoices.max(*ancestors_roles), RoleChoices.max(*current_roles)

    def get_abilities(self, user):
        """
        Compute and return abilities for a given user on the document access.
        """
        ancestors_role, current_role = self.get_user_roles_tuple(user)
        role = RoleChoices.max(ancestors_role, current_role)
        is_owner_or_admin = role in PRIVILEGED_ROLES

        if self.role == RoleChoices.OWNER:
            can_delete = role == RoleChoices.OWNER and (
                # check if document is not root trying to avoid an extra query
                self.document.depth > 1
                or DocumentAccess.objects.filter(
                    document_id=self.document_id, role=RoleChoices.OWNER
                ).count()
                > 1
            )
            set_role_to = RoleChoices.values if can_delete else []
        else:
            can_delete = is_owner_or_admin
            set_role_to = []
            if is_owner_or_admin:
                set_role_to.extend(
                    [
                        RoleChoices.READER,
                        RoleChoices.COMMENTER,
                        RoleChoices.EDITOR,
                        RoleChoices.ADMIN,
                    ]
                )
            if role == RoleChoices.OWNER:
                set_role_to.append(RoleChoices.OWNER)

        # Filter out roles that would be lower than the one the user already has
        ancestors_role_priority = RoleChoices.get_priority(
            getattr(self, "max_ancestors_role", None)
        )
        set_role_to = [
            candidate_role
            for candidate_role in set_role_to
            if RoleChoices.get_priority(candidate_role) >= ancestors_role_priority
        ]
        if len(set_role_to) == 1:
            set_role_to = []

        return {
            "destroy": can_delete,
            "update": bool(set_role_to) and is_owner_or_admin,
            "partial_update": bool(set_role_to) and is_owner_or_admin,
            "retrieve": (self.user and self.user.id == user.id) or is_owner_or_admin,
            "set_role_to": set_role_to,
        }


class DocumentAskForAccess(BaseModel):
    """Relation model to ask for access to a document."""

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="ask_for_accesses"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="ask_for_accesses"
    )

    role = models.CharField(
        max_length=20, choices=RoleChoices.choices, default=RoleChoices.READER
    )

    class Meta:
        db_table = "impress_document_ask_for_access"
        verbose_name = _("Document ask for access")
        verbose_name_plural = _("Document ask for accesses")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "document"],
                name="unique_document_ask_for_access_user",
                violation_error_message=_(
                    "This user has already asked for access to this document."
                ),
            ),
        ]

    def __str__(self):
        return f"{self.user!s} asked for access to document {self.document!s}"

    def get_abilities(self, user):
        """Compute and return abilities for a given user."""
        user_role = self.document.get_role(user)
        is_admin_or_owner = user_role in PRIVILEGED_ROLES

        set_role_to = [
            role
            for role in RoleChoices.values
            if RoleChoices.get_priority(role) <= RoleChoices.get_priority(user_role)
        ]

        return {
            "destroy": is_admin_or_owner,
            "update": is_admin_or_owner,
            "partial_update": is_admin_or_owner,
            "retrieve": is_admin_or_owner,
            "accept": is_admin_or_owner,
            "set_role_to": set_role_to,
        }

    def accept(self, role=None):
        """Accept a document ask for access resource."""
        if role is None:
            role = self.role

        DocumentAccess.objects.update_or_create(
            document=self.document,
            user=self.user,
            defaults={"role": role},
            create_defaults={"role": role},
        )
        self.delete()

    def send_ask_for_access_email(self, email, language=None):
        """
        Method allowing a user to send an email notification when asking for access to a document.
        """

        language = language or get_language()
        sender = self.user
        sender_name = sender.full_name or sender.email
        sender_name_email = (
            f"{sender.full_name:s} ({sender.email})"
            if sender.full_name
            else sender.email
        )

        with override(language):
            context = {
                "title": _("{name} would like access to a page!").format(
                    name=sender_name
                ),
                "message": _(
                    "{name} would like access to the following document:"
                ).format(name=sender_name_email),
            }
            subject = (
                context["title"]
                if not self.document.title
                else _("{name} is asking for access to the page: {title}").format(
                    name=sender_name, title=self.document.title
                )
            )

        self.document.send_email(subject, [email], context, language)


class Thread(BaseModel):
    """Discussion thread attached to a document.

    A thread groups one or many comments. For backward compatibility with the
    existing frontend (useComments hook) we still expose a flattened serializer
    that returns a "content" field representing the first comment's body.
    """

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="threads",
    )
    creator = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="threads",
        null=True,
        blank=True,
    )
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="resolved_threads",
        null=True,
        blank=True,
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "impress_thread"
        ordering = ("-created_at",)
        verbose_name = _("Thread")
        verbose_name_plural = _("Threads")

    def __str__(self):
        author = self.creator or _("Anonymous")
        return f"Thread by {author!s} on {self.document!s}"

    def get_abilities(self, user):
        """Compute and return abilities for a given user (mirrors comment logic)."""
        role = self.document.get_role(user)
        doc_abilities = self.document.get_abilities(user)
        read_access = doc_abilities.get("comment", False)
        write_access = self.creator == user or role in [
            RoleChoices.OWNER,
            RoleChoices.ADMIN,
        ]
        return {
            "destroy": write_access,
            "update": write_access,
            "partial_update": write_access,
            "resolve": write_access,
            "unresolve": write_access,
            "retrieve": read_access,
        }

    @property
    def first_comment(self):
        """Return the first createdcomment of the thread."""
        return self.comments.order_by("created_at").first()


class Comment(BaseModel):
    """A comment belonging to a thread."""

    thread = models.ForeignKey(
        Thread,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="thread_comment",
        null=True,
        blank=True,
    )
    body = models.JSONField()
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "impress_comment"
        ordering = ("created_at",)
        verbose_name = _("Comment")
        verbose_name_plural = _("Comments")

    def __str__(self):
        """Return the string representation of the comment."""
        author = self.user or _("Anonymous")
        return f"Comment by {author!s} on thread {self.thread_id}"

    def get_abilities(self, user):
        """Return the abilities of the comment."""
        role = self.thread.document.get_role(user)
        doc_abilities = self.thread.document.get_abilities(user)
        read_access = doc_abilities.get("comment", False)
        can_react = read_access and user.is_authenticated
        is_author = self.user == user
        can_moderate = is_author or role in [
            RoleChoices.OWNER,
            RoleChoices.ADMIN,
        ]
        return {
            "destroy": can_moderate,
            "update": is_author,
            "partial_update": is_author,
            "reactions": can_react,
            "retrieve": read_access,
        }


class Reaction(BaseModel):
    """Aggregated reactions for a given emoji on a comment.

    We store one row per (comment, emoji) and maintain the list of user IDs who
    reacted with that emoji. This matches the frontend interface where a
    reaction exposes: emoji, createdAt (first reaction date) and userIds.
    """

    comment = models.ForeignKey(
        Comment,
        on_delete=models.CASCADE,
        related_name="reactions",
    )
    emoji = models.CharField(max_length=32)
    users = models.ManyToManyField(User, related_name="reactions")

    class Meta:
        db_table = "impress_comment_reaction"
        constraints = [
            models.UniqueConstraint(
                fields=["comment", "emoji"],
                name="unique_comment_emoji",
                violation_error_message=_(
                    "This emoji has already been reacted to this comment."
                ),
            ),
        ]
        verbose_name = _("Reaction")
        verbose_name_plural = _("Reactions")

    def __str__(self):
        """Return the string representation of the reaction."""
        return f"Reaction {self.emoji} on comment {self.comment.id}"


# The notification guard only has to cover the window between the cooldown
# check and the `notified_at` save: a leaked key (e.g. killed worker) must not
# silence a context for the whole cooldown period
MENTION_NOTIFICATION_GUARD_TIMEOUT_SECONDS = 60


class Mention(BaseModel):
    """A mention of a user in a document body or in a comment thread.

    A mention record is always created, but the email notification is only
    sent if no notification was already sent to the same user in the same
    context (the document or a specific thread) within the cooldown period.
    """

    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="mentions",
    )
    anchor_id = models.TextField()
    thread = models.ForeignKey(
        Thread,
        on_delete=models.CASCADE,
        related_name="mentions",
        null=True,
        blank=True,
    )
    mentioned_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="mentions_received",
        null=True,
        blank=True,
    )
    mentioned_by_user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="mentions_sent",
    )
    notified_at = models.DateTimeField(null=True, blank=True)
    # When a group was mentioned, the mention of each of its members carries
    # the group's team string (see `make_team`)
    mentioned_team = models.CharField(max_length=100, blank=True, default="")
    reason = models.CharField(
        max_length=20,
        choices=[("mention", _("Mention")), ("assignment", _("Assignment"))],
        default="mention",
    )

    class Meta:
        db_table = "impress_mention"
        ordering = ("-created_at",)
        verbose_name = _("Mention")
        verbose_name_plural = _("Mentions")
        indexes = [
            models.Index(
                fields=["mentioned_user", "-created_at"],
                name="mention_user_created_idx",
            ),
            models.Index(
                fields=["document", "mentioned_user"],
                name="mention_document_user_idx",
            ),
        ]

    def __str__(self):
        mentioned = self.mentioned_user or _("a deleted user")
        return (
            f"{self.mentioned_by_user!s} mentioned {mentioned!s} on {self.document!s}"
        )

    def clean(self):
        """Validate that the thread, if any, belongs to the mention's document."""
        super().clean()
        if self.thread_id and self.thread.document_id != self.document_id:
            raise ValidationError(
                {"thread_id": [_("The thread does not belong to this page.")]}
            )

    def is_notification_in_cooldown(self):
        """Return whether the mentioned user was already notified in the same context
        (same document and thread, the document body when the thread is null) within
        the cooldown period."""
        cooldown_start = timezone.now() - timedelta(
            minutes=settings.MENTION_NOTIFICATION_COOLDOWN_MINUTES
        )
        return (
            self._meta.model.objects.filter(
                document_id=self.document_id,
                mentioned_user_id=self.mentioned_user_id,
                thread_id=self.thread_id,
                notified_at__isnull=False,
                created_at__gt=cooldown_start,
            )
            .exclude(pk=self.pk)
            .exists()
        )

    @property
    def notification_guard_key(self):
        """Cache key claiming a notification slot for this mention's context."""
        return (
            "mention-notify:"
            f"{self.document_id}:{self.mentioned_user_id}:{self.thread_id or ''}"
        )

    def notify(self, language=None):
        """Send the mention notification email unless the context is in cooldown.

        Set `notified_at` on the mention and return True if an email was sent,
        return False otherwise.
        """

        if self.mentioned_user_id == self.mentioned_by_user_id:
            return False

        user = self.mentioned_user
        if (
            user is None
            or not user.email
            or not user.collaborator_email_notifications
            or self.is_notification_in_cooldown()
        ):
            return False

        # Guard against concurrent notification tasks for the same context.
        # cache.add is atomic on the shared Redis backend: only the first task
        # acquires the key and proceeds, the others get False
        if not cache.add(
            self.notification_guard_key,
            str(self.pk),
            timeout=MENTION_NOTIFICATION_GUARD_TIMEOUT_SECONDS,
        ):
            return False

        sender = self.mentioned_by_user
        language = (
            language or user.language or sender.language or settings.LANGUAGE_CODE
        )
        sender_name = sender.full_name or sender.email
        domain = settings.EMAIL_URL_APP or Site.objects.get_current().domain

        with override(language):
            title = self.document.title or str(_("Untitled page"))
            if self.reason == "assignment":
                subject = _('{name} assigned you in "{title}"').format(
                    name=sender_name, title=title
                )
                message = _("{name} assigned you something in this page:").format(
                    name=sender_name
                )
            elif self.mentioned_team:
                group = get_team_label(self.mentioned_team)
                subject = _('{name} mentioned {group} in "{title}"').format(
                    name=sender_name, group=group, title=title
                )
                message = _(
                    "{name} mentioned {group}, a group you belong to, in the "
                    "following document:"
                ).format(name=sender_name, group=group)
            elif self.thread_id:
                subject = _('{name} mentioned you in a comment in "{title}"').format(
                    name=sender_name, title=title
                )
                message = _(
                    "{name} mentioned you in a comment in the following document:"
                ).format(name=sender_name)
            else:
                subject = _('{name} mentioned you in "{title}"').format(
                    name=sender_name, title=title
                )
                message = _("{name} mentioned you in the following page:").format(
                    name=sender_name
                )
            context = {
                "title": subject,
                "message": message,
                "link": f"{domain}/{self.document.app_path}/{self.document_id}/#{self.anchor_id}",
            }

        sent = False
        try:
            self.document.send_email(subject, [user.email], context, language)
            self.notified_at = timezone.now()
            self.save(update_fields=["notified_at", "updated_at"])
            sent = True
        finally:
            # Release the context so the next mention can notify
            if not sent:
                cache.delete(self.notification_guard_key)

        return True


class Invitation(BaseModel):
    """User invitation to a document."""

    email = models.EmailField(_("email address"), null=False, blank=False)
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    role = models.CharField(
        max_length=20, choices=RoleChoices.choices, default=RoleChoices.READER
    )
    issuer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="invitations",
        blank=True,
        null=True,
    )

    class Meta:
        db_table = "impress_invitation"
        verbose_name = _("Document invitation")
        verbose_name_plural = _("Document invitations")
        constraints = [
            models.UniqueConstraint(
                fields=["email", "document"], name="email_and_document_unique_together"
            )
        ]

    def __str__(self):
        return f"{self.email} invited to {self.document}"

    # Collaborators: someone with an account may be invited by email too, when
    # the inviter can't find them (they share nothing yet): the invitation
    # waits for them to accept it from its email

    @property
    def is_expired(self):
        """Calculate if invitation is still valid or has expired."""
        if not self.created_at:
            return None

        validity_duration = timedelta(seconds=settings.INVITATION_VALIDITY_DURATION)
        return timezone.now() > (self.created_at + validity_duration)

    def get_abilities(self, user):
        """Compute and return abilities for a given user."""
        roles = []

        if user.is_authenticated:
            teams = user.teams
            try:
                roles = self.user_roles or []
            except AttributeError:
                try:
                    roles = self.document.accesses.filter(
                        models.Q(user=user) | models.Q(team__in=teams),
                    ).values_list("role", flat=True)
                except self._meta.model.DoesNotExist, IndexError:
                    roles = []

        is_admin_or_owner = bool(
            set(roles).intersection({RoleChoices.OWNER, RoleChoices.ADMIN})
        )

        return {
            "destroy": is_admin_or_owner,
            "update": is_admin_or_owner,
            "partial_update": is_admin_or_owner,
            "retrieve": is_admin_or_owner,
        }


class DocumentMigrationStatus(models.TextChoices):
    """What became of a document handed to the collaboration server to migrate."""

    MIGRATED = "ok", _("Migrated")
    ALREADY = "already", _("Already migrated")
    EMPTY = "empty", _("Nothing in the object storage")
    NOTHING = "nothing", _("No readable version")
    FAILED = "failed", _("Failed")


class DocumentMigration(models.Model):
    """
    What the collaboration server did with the legacy content of a document.

    The ledger of the backfill: the collaboration server keeps its own set of
    the documents it migrated, but only of those it actually wrote history for.
    A document it found nothing for is not in it and would be handed over again
    on every run, and a valkey configured to evict would lose the set entirely.
    This table is what the command reads to know what is left to do, and what
    an operator reads to know how it went.
    """

    document = models.OneToOneField(
        Document,
        on_delete=models.CASCADE,
        related_name="migration",
        primary_key=True,
    )
    status = models.CharField(
        max_length=10,
        choices=DocumentMigrationStatus.choices,
        verbose_name=_("status"),
    )
    versions = models.PositiveIntegerField(default=0, verbose_name=_("versions"))
    applied = models.PositiveIntegerField(
        default=0,
        verbose_name=_("applied"),
        help_text=_("versions that added content, one activity entry each"),
    )
    skipped = models.PositiveIntegerField(
        default=0,
        verbose_name=_("skipped"),
        help_text=_("versions that could not be read"),
    )
    dropped = models.PositiveIntegerField(
        default=0,
        verbose_name=_("dropped"),
        help_text=_("versions older than the ones the server replays"),
    )
    duration_ms = models.PositiveIntegerField(default=0, verbose_name=_("duration"))
    error = models.TextField(blank=True, default="", verbose_name=_("error"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("updated on"))

    class Meta:
        db_table = "impress_document_migration"
        verbose_name = _("Document migration")
        verbose_name_plural = _("Document migrations")
        indexes = [models.Index(fields=["status"])]

    def __str__(self):
        return f"{self.document_id!s}: {self.status:s}"


class Workspace(BaseModel):
    """An organisation-level area (a company, a university, a community) holding spaces."""

    name = models.CharField(_("name"), max_length=100)
    slug = models.SlugField(_("slug"), max_length=100, unique=True)
    description = models.TextField(_("description"), blank=True, default="")
    publishing_policy = models.CharField(
        max_length=20,
        choices=PublishingPolicyChoices.choices,
        default=PublishingPolicyChoices.SPACE_ADMINS,
    )
    # Collaborators whose verified email is at one of these domains join the
    # workspace when they sign in, and its organisation group if one is set
    join_domains = ArrayField(
        models.CharField(max_length=253), default=list, blank=True
    )
    join_group = models.ForeignKey(
        "Group",
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )
    # Collaborators of these organisations (a Google Workspace, a Microsoft
    # tenant) join when they sign in: [{"id", "name"}], see
    # User.collaborator_organizations
    join_organizations = models.JSONField(default=list, blank=True)
    # The secret of the workspace's join link, or none when it is turned off
    join_token = models.CharField(max_length=43, unique=True, null=True, blank=True)
    # People joining by link, domain or organisation wait for an admin's yes
    join_approval = models.BooleanField(default=False)
    # Who can find it in "Discover workspaces" and ask to join
    visibility = models.CharField(
        max_length=20,
        choices=WorkspaceVisibilityChoices.choices,
        default=WorkspaceVisibilityChoices.HIDDEN,
    )

    class Meta:
        db_table = "collaborators_workspace"
        ordering = ("name",)
        verbose_name = _("Workspace")
        verbose_name_plural = _("Workspaces")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """Derive a unique slug from the name on creation."""
        if not self.slug:
            base = slugify(self.name)[:90] or "workspace"
            slug, index = base, 1
            while Workspace.objects.filter(slug=slug).exists():
                index += 1
                slug = f"{base}-{index}"
            self.slug = slug
        super().save(*args, **kwargs)

    def get_role(self, user):
        """Return the role of a user in the workspace, or None."""
        if not user.is_authenticated:
            return None
        return self.accesses.filter(user=user).values_list("role", flat=True).first()

    def is_shown_to(self, user):
        """
        Collaborators: whether the user may know the workspace (its name, its
        address): its members, and those its visibility lets find it.
        """
        if self.visibility == WorkspaceVisibilityChoices.PUBLIC:
            return True
        if not user.is_authenticated:
            return False
        return (
            self.visibility == WorkspaceVisibilityChoices.PLATFORM
            or self.accesses.filter(user=user).exists()
        )

    def get_abilities(self, user):
        """Compute and return the abilities of a user on the workspace."""
        role = self.get_role(user)
        is_privileged = role in WORKSPACE_PRIVILEGED_ROLES
        return {
            "create_groups": role is not None,
            "destroy": role == WorkspaceRoleChoices.OWNER,
            "manage_accesses": is_privileged,
            "manage_groups": is_privileged,
            "partial_update": is_privileged,
            "retrieve": role is not None,
            "spaces_create": role is not None,
            "update": is_privileged,
        }


class WorkspaceFavorite(BaseModel):
    """A workspace a collaborator starred, listed under "Starred"."""

    workspace = models.ForeignKey(
        "Workspace", on_delete=models.CASCADE, related_name="favorited_by"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="favorite_workspaces"
    )

    class Meta:
        db_table = "collaborators_workspace_favorite"
        verbose_name = _("Workspace favorite")
        verbose_name_plural = _("Workspace favorites")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "workspace"], name="unique_workspace_favorite_user"
            ),
        ]

    def __str__(self):
        return f"{self.user!s} starred {self.workspace!s}"


class WorkspaceAccess(BaseModel):
    """The membership of a collaborator in a workspace, with a role."""

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="accesses"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="workspace_accesses"
    )
    role = models.CharField(
        max_length=20,
        choices=WorkspaceRoleChoices.choices,
        default=WorkspaceRoleChoices.MEMBER,
    )

    class Meta:
        db_table = "collaborators_workspace_access"
        ordering = ("-created_at",)
        verbose_name = _("Workspace/user relation")
        verbose_name_plural = _("Workspace/user relations")
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"],
                name="unique_workspace_user",
                violation_error_message=_("This user is already in this workspace."),
            ),
        ]

    def __str__(self):
        return f"{self.user!s} is {self.role:s} in workspace {self.workspace!s}"


class Group(BaseModel):
    """
    A set of collaborators of a workspace: a team working on a task, or the
    people of an organization. Any member can create a team; administrators
    also create organizations. The creator manages their groups, like the
    administrators.
    """

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="groups"
    )
    name = models.CharField(_("name"), max_length=100)
    kind = models.CharField(
        max_length=20, choices=GroupKindChoices.choices, default=GroupKindChoices.TEAM
    )
    description = models.TextField(_("description"), blank=True, default="")
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="created_groups",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "collaborators_group"
        ordering = ("name",)
        verbose_name = _("Group")
        verbose_name_plural = _("Groups")
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "name"],
                name="unique_group_name_per_workspace",
                violation_error_message=_(
                    "A group with this name already exists in this workspace."
                ),
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def team(self):
        """The team string granting a role to this group on documents."""
        return make_team(TEAM_GROUP, self.id)

    def get_abilities(self, user):
        """
        Workspace administrators and the group's creator manage the group;
        group managers manage its members.
        """
        role = self.workspace.get_role(user)
        is_owner = role in WORKSPACE_PRIVILEGED_ROLES or (
            role is not None
            and self.created_by_id is not None
            and self.created_by_id == user.id
        )
        is_manager = (
            user.is_authenticated
            and self.memberships.filter(user=user, is_manager=True).exists()
        )
        return {
            "destroy": is_owner,
            "manage_managers": is_owner,
            "manage_members": is_owner or is_manager,
            "partial_update": is_owner,
            "retrieve": role is not None,
            "update": is_owner,
        }


class GroupMembership(BaseModel):
    """The membership of a collaborator in a group."""

    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="group_memberships"
    )
    is_manager = models.BooleanField(default=False)

    class Meta:
        db_table = "collaborators_group_membership"
        ordering = ("-created_at",)
        verbose_name = _("Group membership")
        verbose_name_plural = _("Group memberships")
        constraints = [
            models.UniqueConstraint(
                fields=["group", "user"],
                name="unique_group_user",
                violation_error_message=_("This user is already in this group."),
            ),
        ]

    def __str__(self):
        return f"{self.user!s} in group {self.group!s}"


class SpaceWorkspaceLink(BaseModel):
    """
    Places a space in a workspace. Each space linked to workspaces has exactly
    one home workspace, which owns it; the other links share it with more
    workspaces.
    """

    space = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="workspace_links"
    )
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="space_links"
    )
    is_home = models.BooleanField(default=False)

    class Meta:
        db_table = "collaborators_space_workspace_link"
        ordering = ("-is_home", "created_at")
        verbose_name = _("Space/workspace link")
        verbose_name_plural = _("Space/workspace links")
        constraints = [
            models.UniqueConstraint(
                fields=["space", "workspace"],
                name="unique_space_workspace",
                violation_error_message=_(
                    "This space is already linked to this workspace."
                ),
            ),
            models.UniqueConstraint(
                fields=["space"],
                condition=models.Q(is_home=True),
                name="unique_home_workspace_per_space",
                violation_error_message=_("This space already has a home workspace."),
            ),
        ]

    def __str__(self):
        return f"{self.space!s} in workspace {self.workspace!s}"

    def clean(self):
        """
        Spaces are placed in workspaces, and so are top-level pages, directly
        (in none of the workspace's spaces).
        """
        super().clean()
        if self.space_id and not (self.space.is_space or self.space.is_root()):
            raise ValidationError(
                {"space": _("Only a space or a top-level page can join a workspace.")}
            )


class Label(BaseModel):
    """
    A label of the platform's shared vocabulary (a "tag", Web 2.0 style),
    put on workspaces, spaces and pages. One per spelling, whatever its case:
    the first spelling is kept.
    """

    name = models.CharField(max_length=40)
    # The name in lower case, so "AI" and "ai" are one label
    key = models.CharField(max_length=40, unique=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name="+", null=True, blank=True
    )

    class Meta:
        db_table = "collaborators_label"
        ordering = ("key",)
        verbose_name = _("Label")
        verbose_name_plural = _("Labels")

    def __str__(self):
        return self.name

    @classmethod
    def normalize(cls, name):
        """The name as stored: trimmed, single spaces, no leading "#"."""
        return " ".join(str(name or "").strip().lstrip("#").split())[:40]

    @classmethod
    def get_or_create_named(cls, name, user=None):
        """The label with this name (any case), created if new."""
        name = cls.normalize(name)
        if not name:
            raise ValueError("empty label")
        label, _created = cls.objects.get_or_create(
            key=name.lower(),
            defaults={
                "name": name,
                "created_by": user if user and user.is_authenticated else None,
            },
        )
        return label


class DocumentLabel(BaseModel):
    """A label put on a page or a space."""

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="labels"
    )
    label = models.ForeignKey(Label, on_delete=models.CASCADE, related_name="documents")
    added_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name="+", null=True, blank=True
    )

    class Meta:
        db_table = "collaborators_document_label"
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["document", "label"], name="unique_document_label"
            ),
        ]

    def __str__(self):
        return f"{self.label!s} on {self.document!s}"


class WorkspaceLabel(BaseModel):
    """A label put on a workspace."""

    workspace = models.ForeignKey(
        "Workspace", on_delete=models.CASCADE, related_name="labels"
    )
    label = models.ForeignKey(
        Label, on_delete=models.CASCADE, related_name="workspaces"
    )
    added_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name="+", null=True, blank=True
    )

    class Meta:
        db_table = "collaborators_workspace_label"
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "label"], name="unique_workspace_label"
            ),
        ]

    def __str__(self):
        return f"{self.label!s} on {self.workspace!s}"


class ProfileAudience(models.TextChoices):
    """Who can see a piece of a profile."""

    PUBLIC = "public", _("Public on the internet")
    PLATFORM = "platform", _("Everyone on Collaborators")
    COLLEAGUES = "colleagues", _("People I work with")
    SELECTED = "selected", _("Chosen workspaces and spaces")


# The pieces of a profile, and who sees each one unless the person changes it:
# the people they work with (Collaborators: the same default everywhere)
PROFILE_FIELDS = {
    "name": ProfileAudience.COLLEAGUES,
    "headline": ProfileAudience.COLLEAGUES,
    "organization": ProfileAudience.COLLEAGUES,
    "location": ProfileAudience.COLLEAGUES,
    "bio": ProfileAudience.COLLEAGUES,
    "website": ProfileAudience.COLLEAGUES,
    "email": ProfileAudience.COLLEAGUES,
    "interests": ProfileAudience.COLLEAGUES,
    # Collaborators: no "workspaces" piece: a profile lists the workspaces,
    # spaces and pages of the person that their own visibility lets show
}


class UserProfile(BaseModel):
    """
    What a collaborator tells about themselves, each piece with its own
    audience (`visibility`: {field: {"level", "workspaces", "spaces"}}). A
    profile can't be fully hidden: the name stays visible at least to the
    people one works with.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    headline = models.CharField(max_length=120, blank=True, default="")
    organization = models.CharField(max_length=120, blank=True, default="")
    location = models.CharField(max_length=120, blank=True, default="")
    bio = models.TextField(max_length=2000, blank=True, default="")
    website = models.URLField(max_length=300, blank=True, default="")
    interests = models.ManyToManyField(Label, blank=True, related_name="profiles")
    visibility = models.JSONField(default=dict, blank=True)
    # The address shown as the profile's email, among the person's own (the
    # account's, and those of the accounts merged into it); empty: the account's
    shown_email = models.EmailField(blank=True, default="")
    # Who can find this collaborator (search, "My Collaborators") and invite
    # them: the people they share a workspace, space or page with, or
    # everyone. It also caps the audience of each piece of the profile.
    reach = models.CharField(
        max_length=10,
        choices=[
            (choice.value, choice.label)
            for choice in ProfileAudience
            if choice != ProfileAudience.SELECTED
        ],
        default=ProfileAudience.COLLEAGUES,
    )

    class Meta:
        db_table = "collaborators_user_profile"
        verbose_name = _("Profile")
        verbose_name_plural = _("Profiles")

    def __str__(self):
        return f"Profile of {self.user!s}"

    def audience(self, field):
        """{"level", "workspaces", "spaces"} of a field, with its default."""
        setting = (self.visibility or {}).get(field) or {}
        return {
            "level": setting.get("level") or PROFILE_FIELDS[field],
            "workspaces": list(setting.get("workspaces") or []),
            "spaces": list(setting.get("spaces") or []),
        }


class PageSpaceLink(BaseModel):
    """
    Shows a page (with its subpages) in a space other than its home: the same
    page, not a copy. Its home space (or its owner, for an independent page)
    keeps controlling it; whoever has a role on the linking space may read it.
    """

    page = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="space_links"
    )
    space = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="linked_pages"
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, related_name="+", null=True, blank=True
    )

    class Meta:
        db_table = "collaborators_page_space_link"
        ordering = ("created_at",)
        verbose_name = _("Page/space link")
        verbose_name_plural = _("Page/space links")
        constraints = [
            models.UniqueConstraint(
                fields=["page", "space"],
                name="unique_page_space",
                violation_error_message=_("This page is already in this space."),
            ),
        ]

    def __str__(self):
        return f"{self.page!s} linked into {self.space!s}"


def drop_workspace_roles(document, workspace_ids):
    """
    Collaborators: the roles these workspaces gave (their members, admins
    and groups) go, on the document and every page below it: it left them.
    """
    workspace_ids = list(workspace_ids)
    if not workspace_ids:
        return
    teams = [
        make_team(kind, workspace_id)
        for workspace_id in workspace_ids
        for kind in (TEAM_WORKSPACE, TEAM_WORKSPACE_ADMINS)
    ] + [
        make_team(TEAM_GROUP, group_id)
        for group_id in Group.objects.filter(
            workspace_id__in=workspace_ids
        ).values_list("id", flat=True)
    ]
    DocumentAccess.objects.filter(
        document__path__startswith=document.path, team__in=teams
    ).delete()


def follow_workspaces_after_move(document, old_root, old_workspaces):
    """
    Collaborators: under another page, a page placed directly in a workspace
    leaves it; the workspaces of its former space (or top page) give no more
    roles on it and below it; still on top, a page placed in a workspace
    keeps its members and administrators.
    """
    new_root = document if document.is_root() else document.get_root()
    if not document.is_root():
        document.workspace_links.all().delete()
    if new_root.pk != old_root.pk:
        kept = set(new_root.workspace_links.values_list("workspace_id", flat=True))
        drop_workspace_roles(document, [w for w in old_workspaces if w not in kept])
    home = (
        document.workspace_links.filter(is_home=True).first()
        if document.is_root() and not document.is_space
        else None
    )
    if home is not None:
        DocumentAccess.objects.update_or_create(
            document=document,
            team=make_team(TEAM_WORKSPACE_ADMINS, home.workspace_id),
            defaults={"role": RoleChoices.OWNER},
        )
        DocumentAccess.objects.get_or_create(
            document=document,
            team=make_team(TEAM_WORKSPACE, home.workspace_id),
            defaults={"role": RoleChoices.READER},
        )


def role_readable_q(user):
    """
    Collaborators: documents a user may read through a role: theirs, their
    teams', or one on a space the document (or a page above it) is linked
    into. Roles reach every page below, kept private or not.
    """
    if not user.is_authenticated:
        return models.Q(pk__in=[])
    return (
        models.Q(accesses__user=user)
        | models.Q(accesses__team__in=user.teams)
        | models.Exists(linked_reader_access(user))
    )


def link_readable_q(user):
    """
    Collaborators: documents a user may read through their link reach. A
    page kept private takes none from the pages above it.
    """
    if user.is_authenticated:
        return ~models.Q(link_reach=LinkReachChoices.RESTRICTED) | ~models.Q(
            linked_link_reach=LinkReachChoices.RESTRICTED
        )
    return models.Q(link_reach=LinkReachChoices.PUBLIC) | models.Q(
        linked_link_reach=LinkReachChoices.PUBLIC
    )


def refresh_linked_reach(page_ids):
    """
    Collaborators: give these pages the widest link of the spaces they are
    linked into (none in the trashbin). Returns the pages whose link changed.
    """
    changed = []
    for page in Document.objects.filter(pk__in=list(page_ids)):
        linked = get_equivalent_link_definition(
            [
                {"link_reach": reach, "link_role": role}
                for reach, role in PageSpaceLink.objects.filter(
                    page=page, space__ancestors_deleted_at__isnull=True
                ).values_list("space__link_reach", "space__link_role")
            ]
        )
        values = (
            linked["link_reach"] or LinkReachChoices.RESTRICTED,
            linked["link_role"] or LinkRoleChoices.READER,
        )
        if values != (page.linked_link_reach, page.linked_link_role):
            Document.objects.filter(pk=page.pk).update(
                linked_link_reach=values[0], linked_link_role=values[1]
            )
            changed.append(page.pk)
    return changed


def linked_reader_access(user, outer_path="path"):
    """
    The links that let the user read a page (or one of its subpages: the
    page's path starts the document's), through a role on the linking space.
    For a subquery on documents, by their `path`.
    """
    return PageSpaceLink.objects.filter(
        models.Q(space__accesses__user=user)
        | models.Q(space__accesses__team__in=user.teams),
        page__path=Left(models.OuterRef(outer_path), Length("page__path")),
        page__ancestors_deleted_at__isnull=True,
        # Collaborators: a space in the trashbin links nothing
        space__ancestors_deleted_at__isnull=True,
    )


def get_team_label(team):
    """Return a human readable name for a team string, or the string itself."""
    kind, obj_id = parse_team(team)
    if kind == TEAM_GROUP:
        group = Group.objects.filter(id=obj_id).select_related("workspace").first()
        return f"{group.name} ({group.workspace.name})" if group else team
    if kind in (TEAM_WORKSPACE, TEAM_WORKSPACE_ADMINS):
        workspace = Workspace.objects.filter(id=obj_id).first()
        if not workspace:
            return team
        if kind == TEAM_WORKSPACE:
            return str(_("All members of {name}")).format(name=workspace.name)
        return str(_("Administrators of {name}")).format(name=workspace.name)
    return team


class SignInIdentity(BaseModel):
    """
    One more Google or Microsoft account that opens a collaborator's
    account. Keycloak links one account per provider to a person; the
    others are separate Keycloak users, sent to this collaborator here (by
    the `sub` they sign in with).
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="sign_in_identities"
    )
    provider = models.CharField(max_length=40)
    sub = models.CharField(max_length=255, unique=True)
    # The account's email, to show which one it is
    account = models.CharField(max_length=255, blank=True, default="")
    # The organisations it vouches for, see User.collaborator_organizations
    organizations = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "collaborators_sign_in_identity"
        ordering = ("created_at",)
        verbose_name = _("Sign-in identity")
        verbose_name_plural = _("Sign-in identities")

    def __str__(self):
        return f"{self.provider} {self.account} for {self.user!s}"


class WorkspaceJoinRequest(BaseModel):
    """
    Someone asking to join a workspace whose admins approve who joins. A
    declined request is kept, so joining by domain doesn't ask again at each
    sign-in.
    """

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="join_requests"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="workspace_join_requests"
    )
    via = models.CharField(
        max_length=20,
        choices=JoinViaChoices.choices,
        default=JoinViaChoices.LINK,
    )
    # The organisation group they also join once approved
    group = models.ForeignKey(
        "Group",
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=JoinRequestStatusChoices.choices,
        default=JoinRequestStatusChoices.PENDING,
    )

    class Meta:
        db_table = "collaborators_workspace_join_request"
        ordering = ("created_at",)
        verbose_name = _("Workspace join request")
        verbose_name_plural = _("Workspace join requests")
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"],
                name="unique_workspace_join_request",
            ),
        ]

    def __str__(self):
        return f"{self.user!s} asks to join {self.workspace!s}"


class Notification(BaseModel):
    """
    An entry of a collaborator's notification inbox: they were mentioned
    (directly or through a group) or assigned somewhere in a document, or
    someone asks to join a workspace they administer, or they were let in;
    for platform managers, someone registered and waits for them; for
    platform administrators, someone reported a page.
    """

    KIND_MENTION = "mention"
    KIND_COMMENT_MENTION = "comment_mention"
    KIND_ASSIGNMENT = "assignment"
    KIND_JOIN_REQUEST = "join_request"
    KIND_JOIN_APPROVED = "join_approved"
    KIND_SIGNUP = "signup"
    KIND_SIGNUP_APPROVED = "signup_approved"
    KIND_REPORT = "report"

    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications"
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="notifications_sent",
        null=True,
        blank=True,
    )
    kind = models.CharField(
        max_length=20,
        choices=[
            (KIND_MENTION, _("Mention")),
            (KIND_COMMENT_MENTION, _("Mention in a comment")),
            (KIND_ASSIGNMENT, _("Assignment")),
            (KIND_JOIN_REQUEST, _("Request to join a workspace")),
            (KIND_JOIN_APPROVED, _("Request to join approved")),
            (KIND_SIGNUP, _("New registration")),
            (KIND_SIGNUP_APPROVED, _("Registration approved")),
            (KIND_REPORT, _("Page reported")),
        ],
        default=KIND_MENTION,
    )
    # Where: a document, or a workspace for joining
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )
    # Where to go: a block id, or "cell:<table>:<row>:<column>" for a table cell
    anchor_id = models.TextField(blank=True, default="")
    thread = models.ForeignKey(
        Thread,
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )
    # The group the recipient was reached through, if any
    team = models.CharField(max_length=100, blank=True, default="")
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "collaborators_notification"
        ordering = ("-created_at",)
        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")
        indexes = [
            models.Index(
                fields=["recipient", "read_at", "-created_at"],
                name="notification_inbox_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.kind} for {self.recipient!s} on {self.document or self.workspace!s}"
        )


class TableAssignment(BaseModel):
    """
    A person or a group set in a Person cell of a Loop table. Tables live in
    the documents' Yjs content, out of the database's reach: this index lets
    the dashboard list what is assigned to someone. The browser keeps it up to
    date as cells change.
    """

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="table_assignments"
    )
    # "cell:<table>:<row>:<column>"
    anchor_id = models.CharField(max_length=160)
    assignee = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="table_assignments",
        null=True,
        blank=True,
    )
    team = models.CharField(max_length=100, blank=True, default="")
    # What the row is about (its first text), as it was when assigned
    row_label = models.CharField(max_length=255, blank=True, default="")
    assigned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="table_assignments_made",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "collaborators_table_assignment"
        ordering = ("-updated_at",)
        verbose_name = _("Table assignment")
        verbose_name_plural = _("Table assignments")
        constraints = [
            models.UniqueConstraint(
                fields=["document", "anchor_id", "assignee"],
                condition=models.Q(assignee__isnull=False),
                name="unique_table_assignment_user",
            ),
            models.UniqueConstraint(
                fields=["document", "anchor_id", "team"],
                condition=models.Q(team__gt=""),
                name="unique_table_assignment_team",
            ),
            models.CheckConstraint(
                condition=models.Q(assignee__isnull=False, team="")
                | models.Q(assignee__isnull=True, team__gt=""),
                name="check_table_assignment_user_or_team",
            ),
        ]

    def __str__(self):
        return f"{self.assignee or self.team} on {self.document!s}"


class WikiRelease(BaseModel):
    """
    A fixed version of a wiki: its pages as they were when it was published.
    Readers see it until the next one, while editors keep working on the
    live pages, which are not public meanwhile. The content of each page is
    kept in object storage, under `wiki-releases/<release>/<page>`.
    """

    space = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="wiki_releases"
    )
    published_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="wiki_releases",
        null=True,
        blank=True,
    )
    # The tree of pages, as the wiki reader shows it
    tree = models.JSONField(default=list, blank=True)
    # By page id: its title and text (for search)
    pages = models.JSONField(default=dict, blank=True)
    # The files of its pages (images...), which its readers may load
    attachments = ArrayField(models.CharField(max_length=255), default=list, blank=True)

    class Meta:
        db_table = "collaborators_wiki_release"
        ordering = ("-created_at",)
        verbose_name = _("Wiki release")
        verbose_name_plural = _("Wiki releases")

    def __str__(self):
        return f"{self.space_id!s} {self.created_at:%Y-%m-%d %H:%M}"

    def content_key(self, page_id):
        """Where the content of one of its pages is kept."""
        return f"wiki-releases/{self.id!s}/{page_id!s}"


class PublicationLog(BaseModel):
    """The publishing log: who published what to the web, and when."""

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="publication_logs"
    )
    # The home workspace of the page's space when it happened, if any
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="publication_logs",
        null=True,
        blank=True,
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="publication_logs",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=20, choices=PublicationActionChoices.choices)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "collaborators_publication_log"
        ordering = ("-created_at",)
        verbose_name = _("Publication log entry")
        verbose_name_plural = _("Publication log entries")

    def __str__(self):
        return f"{self.action} {self.document_id!s}"


class PlatformLog(BaseModel):
    """
    Collaborators: what platform managers, administrators and owners did
    (and changes made from the command line or by settings, without an
    actor). Names are kept as they were, should the accounts go.
    """

    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="platform_actions",
        null=True,
        blank=True,
    )
    actor_name = models.CharField(max_length=255, blank=True)
    target = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="platform_log",
        null=True,
        blank=True,
    )
    target_name = models.CharField(max_length=255, blank=True)
    action = models.CharField(max_length=20, choices=PlatformLogActionChoices.choices)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "collaborators_platform_log"
        ordering = ("-created_at",)
        verbose_name = _("Platform log entry")
        verbose_name_plural = _("Platform log entries")

    def __str__(self):
        return f"{self.action} {self.target_name}"


class BlockedEmail(BaseModel):
    """
    Collaborators: an email platform owners blocked (core.accounts). Nobody
    signs in with it, whether or not it has an account yet.
    """

    # Kept lower case
    email = models.EmailField(unique=True)
    reason = models.CharField(max_length=500, blank=True)
    blocked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="blocked_emails",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "collaborators_blocked_email"
        ordering = ("-created_at",)
        verbose_name = _("Blocked email")
        verbose_name_plural = _("Blocked emails")

    def __str__(self):
        return self.email


class AssistantUse(BaseModel):
    """
    Collaborators: when an AI assistant (a client of the sign-in server)
    last did something for a collaborator through the MCP server
    (core.api.mcp), shown with the assistants connected.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="assistant_uses"
    )
    client_id = models.CharField(max_length=255)
    last_used_at = models.DateTimeField()

    class Meta:
        db_table = "collaborators_assistant_use"
        verbose_name = _("Assistant use")
        verbose_name_plural = _("Assistant uses")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "client_id"], name="unique_assistant_use"
            )
        ]

    def __str__(self):
        return f"{self.client_id} for {self.user!s}"


class ContentReport(BaseModel):
    """
    Collaborators: someone reported a page; platform administrators dismiss
    the report or take the page down (core.reports). What was reported is
    kept as it was, should the page or the accounts go.
    """

    document = models.ForeignKey(
        Document,
        on_delete=models.SET_NULL,
        related_name="reports",
        null=True,
        blank=True,
    )
    document_title = models.CharField(max_length=255, blank=True)
    # The page's text when it was reported
    excerpt = models.TextField(blank=True)
    reporter = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="reports_made",
        null=True,
        blank=True,
    )
    reporter_name = models.CharField(max_length=255, blank=True)
    reason = models.CharField(max_length=20, choices=ReportReasonChoices.choices)
    details = models.TextField(blank=True, max_length=2000)
    status = models.CharField(
        max_length=20,
        choices=ReportStatusChoices.choices,
        default=ReportStatusChoices.OPEN,
    )
    resolved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="reports_resolved",
        null=True,
        blank=True,
    )
    resolved_by_name = models.CharField(max_length=255, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    # Why, as told to the page's owners
    resolution_note = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "collaborators_content_report"
        ordering = ("-created_at",)
        verbose_name = _("Content report")
        verbose_name_plural = _("Content reports")

    def __str__(self):
        return f"{self.reason} {self.document_title}"


class PlatformSettings(BaseModel):
    """
    Collaborators: the settings platform owners change in the app (one row,
    core.platform_settings). Empty, a setting follows the server's own
    (its environment).
    """

    signup_approval = models.BooleanField(null=True, blank=True)
    email_invitations = models.BooleanField(null=True, blank=True)
    presentation_storage_mb = models.PositiveIntegerField(null=True, blank=True)
    presentation_versions = models.PositiveIntegerField(null=True, blank=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "collaborators_platform_settings"
        verbose_name = _("Platform settings")
        verbose_name_plural = _("Platform settings")

    def __str__(self):
        return "Platform settings"


class WorkspaceInvitation(BaseModel):
    """
    An invitation by email to a workspace, for someone without an account
    (or whom the inviter can't find): its email links to a page to sign up
    and accept it. Signing up with the same email accepts it too.
    """

    email = models.EmailField(_("email address"))
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="invitations"
    )
    role = models.CharField(
        max_length=20,
        choices=WorkspaceRoleChoices.choices,
        default=WorkspaceRoleChoices.MEMBER,
    )
    issuer = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="workspace_invitations",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "collaborators_workspace_invitation"
        verbose_name = _("Workspace invitation")
        verbose_name_plural = _("Workspace invitations")
        constraints = [
            models.UniqueConstraint(
                fields=["email", "workspace"],
                name="workspace_invitation_email_unique",
            )
        ]

    def __str__(self):
        return f"{self.email} invited to {self.workspace}"

    @property
    def is_expired(self):
        """Older than INVITATION_VALIDITY_DURATION."""
        validity = timedelta(seconds=settings.INVITATION_VALIDITY_DURATION)
        return timezone.now() > self.created_at + validity

    @classmethod
    def convert_for(cls, user):
        """A newcomer's valid invitations to workspaces become memberships."""
        valid = cls.objects.filter(
            email__iexact=user.email,
            created_at__gte=timezone.now()
            - timedelta(seconds=settings.INVITATION_VALIDITY_DURATION),
        )
        if not valid.exists():
            return
        for invitation in valid.select_related("workspace"):
            WorkspaceAccess.objects.get_or_create(
                workspace=invitation.workspace,
                user=user,
                defaults={"role": invitation.role},
            )
        valid.delete()
        user.mark_invited()


class ItemLogo(BaseModel):
    """
    The image standing for a workspace, a space or a page (in invitations, on
    the page to accept one, in its settings), kept small in the database.
    """

    MAX_BYTES = 512 * 1024
    CONTENT_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")

    workspace = models.OneToOneField(
        Workspace,
        on_delete=models.CASCADE,
        related_name="logo",
        null=True,
        blank=True,
    )
    document = models.OneToOneField(
        Document,
        on_delete=models.CASCADE,
        related_name="logo",
        null=True,
        blank=True,
    )
    content_type = models.CharField(max_length=20)
    data = models.BinaryField()

    class Meta:
        db_table = "collaborators_item_logo"
        verbose_name = _("Logo")
        verbose_name_plural = _("Logos")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(workspace__isnull=False, document__isnull=True)
                | models.Q(workspace__isnull=True, document__isnull=False),
                name="item_logo_of_one_item",
            )
        ]

    def __str__(self):
        return f"Logo of {self.workspace or self.document}"


class Presentation(BaseModel):
    """
    Collaborators: an HTML presentation shown in a page by its "presentation"
    block (core.presentations). Either stored here, as versions (the current
    one shown), or a link to an HTML file hosted elsewhere, fetched when it is
    shown. Whoever reads the page sees it; whoever edits the page changes it.
    """

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="presentations"
    )
    title = models.CharField(max_length=255, blank=True)
    # An HTML file hosted elsewhere; empty for a presentation stored here
    link_url = models.URLField(max_length=2000, blank=True)
    # The fingerprint (sha256) of the linked file when last fetched
    link_sha256 = models.CharField(max_length=64, blank=True)
    current = models.ForeignKey(
        "PresentationVersion",
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "collaborators_presentation"
        verbose_name = _("Presentation")
        verbose_name_plural = _("Presentations")

    def __str__(self):
        return self.title or str(self.pk)


class PresentationVersion(BaseModel):
    """
    One stored file of a presentation. It counts against the storage of
    whoever uploaded it; the oldest beyond the platform's number of versions
    go, with their file.
    """

    presentation = models.ForeignKey(
        Presentation, on_delete=models.CASCADE, related_name="versions"
    )
    file_key = models.CharField(max_length=255)
    size = models.PositiveIntegerField()
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="presentation_uploads",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "collaborators_presentation_version"
        verbose_name = _("Presentation version")
        verbose_name_plural = _("Presentation versions")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.presentation} ({self.created_at:%Y-%m-%d %H:%M})"


class PresentationPdf(BaseModel):
    """
    The PDF made with a presentation, its twin: what "Export to PDF" gives,
    and what the block's "Slides" tab shows page by page. That of a stored
    version goes with it (replaced, restored and removed together); a linked
    presentation has one of its own, made for the HTML at its link when it
    was added (a fingerprint tells when that file changed since). Stored
    here, counting against whoever uploaded it, or a link to one elsewhere.
    """

    presentation = models.ForeignKey(
        Presentation, on_delete=models.CASCADE, related_name="pdfs"
    )
    # The stored version it goes with; none for a linked presentation's
    version = models.OneToOneField(
        PresentationVersion,
        on_delete=models.CASCADE,
        related_name="pdf",
        null=True,
        blank=True,
    )
    file_key = models.CharField(max_length=255, blank=True)
    link_url = models.URLField(max_length=2000, blank=True)
    size = models.PositiveIntegerField(default=0)
    pages = models.PositiveIntegerField(null=True, blank=True)
    # The fingerprint (sha256) of the HTML it was made for, when linked
    html_sha256 = models.CharField(max_length=64, blank=True)
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="presentation_pdf_uploads",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "collaborators_presentation_pdf"
        verbose_name = _("Presentation PDF")
        verbose_name_plural = _("Presentation PDFs")
        ordering = ["-created_at"]

    def __str__(self):
        return f"PDF of {self.presentation}"
