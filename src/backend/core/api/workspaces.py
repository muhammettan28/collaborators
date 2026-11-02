"""
API endpoints for the structure Collaborators adds on top of documents:
workspaces, their members and groups, and spaces.

A space is a root document of kind "space": its pages are its descendants, so
they inherit its accesses. Groups and workspaces are granted on documents as
teams (see `core.models.make_team`), which is how existing team accesses
already work.
"""

from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

import rest_framework as drf
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.views import APIView

from core import choices, joining, models
from core.api import permissions, publishing
from core.api.people_privacy import check_can_find
from core.api.serializers import ListDocumentSerializer, UserSerializer
from core.utils.treebeard import create_tree_node_with_retry

# pylint: disable=abstract-method,too-many-ancestors

# -- Serializers


class WorkspaceSerializer(serializers.ModelSerializer):
    """Serialize workspaces."""

    abilities = serializers.SerializerMethodField(read_only=True)
    user_role = serializers.SerializerMethodField(read_only=True)
    join_token = serializers.SerializerMethodField(read_only=True)
    join_domains = serializers.ListField(
        child=serializers.CharField(max_length=253), required=False
    )
    join_group = serializers.PrimaryKeyRelatedField(
        queryset=models.Group.objects.all(), required=False, allow_null=True
    )
    # Written as a list of organisation ids, read as [{"id", "name"}]
    join_organizations = serializers.JSONField(required=False)
    join_organization_choices = serializers.SerializerMethodField(read_only=True)
    pending_join_requests = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = models.Workspace
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "publishing_policy",
            "visibility",
            "join_approval",
            "join_domains",
            "join_group",
            "join_organizations",
            "join_organization_choices",
            "join_token",
            "pending_join_requests",
            "abilities",
            "user_role",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "slug",
            "abilities",
            "user_role",
            "created_at",
            "updated_at",
        ]

    def get_abilities(self, instance) -> dict:
        """Return abilities of the logged-in user on the workspace."""
        return instance.get_abilities(self.context["request"].user)

    def get_user_role(self, instance):
        """Return the role of the logged-in user in the workspace."""
        return instance.get_role(self.context["request"].user)

    def get_join_token(self, instance):
        """The secret of the join link, for the workspace's admins only."""
        if is_workspace_admin(instance, self.context["request"].user):
            return instance.join_token
        return None

    def get_join_organization_choices(self, instance):
        """The organisations an admin signed in with, which they may add."""
        user = self.context["request"].user
        if is_workspace_admin(instance, user):
            return user.collaborator_organizations or []
        return []

    def get_pending_join_requests(self, instance):
        """How many people wait for an admin's answer, for admins."""
        if is_workspace_admin(instance, self.context["request"].user):
            return instance.join_requests.filter(
                status=choices.JoinRequestStatusChoices.PENDING
            ).count()
        return 0

    def to_representation(self, instance):
        """Only admins see how people join without an invitation."""
        data = super().to_representation(instance)
        if not is_workspace_admin(instance, self.context["request"].user):
            data["join_domains"] = []
            data["join_group"] = None
            data["join_organizations"] = []
            data["join_approval"] = False
        return data

    def validate_join_organizations(self, value):
        """Organisations the admin signed in with, or already there."""
        if not isinstance(value, list):
            raise serializers.ValidationError(_("Expected a list."))
        ids = [item.get("id") if isinstance(item, dict) else item for item in value]
        try:
            return joining.check_join_organizations(
                ids,
                self.context["request"].user,
                self.instance.join_organizations if self.instance else [],
            )
        except ValueError as error:
            raise serializers.ValidationError(str(error)) from error

    def validate_join_domains(self, value):
        """Domains the admin's own verified email proves they hold."""
        admin = self.context["request"].user
        cleaned = []
        for raw in value:
            try:
                domain = joining.check_join_domain(raw, admin)
            except ValueError as error:
                raise serializers.ValidationError(str(error)) from error
            if domain not in cleaned:
                cleaned.append(domain)
        return cleaned

    def validate_join_group(self, value):
        """The organisation group must be one of the workspace's groups."""
        if value is not None and (
            self.instance is None or value.workspace_id != self.instance.id
        ):
            raise serializers.ValidationError(
                _("Choose a user group of this workspace.")
            )
        return value


class WorkspaceAccessSerializer(serializers.ModelSerializer):
    """Serialize the members of a workspace."""

    user = UserSerializer(read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=models.User.objects.all(), write_only=True, source="user"
    )

    class Meta:
        model = models.WorkspaceAccess
        fields = ["id", "user", "user_id", "role", "created_at"]
        read_only_fields = ["id", "created_at"]

    def update(self, instance, validated_data):
        """The member of an access can't be changed, only its role."""
        validated_data.pop("user", None)
        return super().update(instance, validated_data)


class GroupSerializer(serializers.ModelSerializer):
    """Serialize groups."""

    abilities = serializers.SerializerMethodField(read_only=True)
    nb_members = serializers.IntegerField(read_only=True)
    team = serializers.CharField(read_only=True)
    created_by = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = models.Group
        fields = [
            "id",
            "workspace",
            "document",
            "name",
            "kind",
            "description",
            "team",
            "nb_members",
            "created_by",
            "abilities",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "workspace",
            "document",
            "team",
            "nb_members",
            "created_by",
            "abilities",
            "created_at",
        ]

    def get_created_by(self, instance):
        """Who created the group, if known."""
        user = instance.created_by
        if user is None:
            return None
        return {"id": str(user.id), "full_name": user.full_name or user.email}

    def get_abilities(self, instance) -> dict:
        """Return abilities of the logged-in user on the group."""
        return instance.get_abilities(self.context["request"].user)


class GroupMembershipSerializer(serializers.ModelSerializer):
    """Serialize the members of a group."""

    user = UserSerializer(read_only=True)
    user_id = serializers.PrimaryKeyRelatedField(
        queryset=models.User.objects.all(), write_only=True, source="user"
    )

    class Meta:
        model = models.GroupMembership
        fields = ["id", "user", "user_id", "is_manager", "created_at"]
        read_only_fields = ["id", "created_at"]

    def update(self, instance, validated_data):
        """The member of a membership can't be changed, only its manager flag."""
        validated_data.pop("user", None)
        return super().update(instance, validated_data)


class SpaceSerializer(ListDocumentSerializer):
    """Serialize spaces, with the workspaces they are placed in."""

    linked_workspaces = serializers.SerializerMethodField(read_only=True)
    members_role = serializers.SerializerMethodField(read_only=True)

    class Meta(ListDocumentSerializer.Meta):
        fields = [
            *ListDocumentSerializer.Meta.fields,
            "linked_workspaces",
            "members_role",
        ]
        read_only_fields = fields

    def get_linked_workspaces(self, instance):
        """
        All the workspaces the space appears in, its home first.
        Collaborators: those the viewer may know only.
        """
        request = self.context.get("request")
        return [
            {
                "id": str(link.workspace.id),
                "name": link.workspace.name,
                "slug": link.workspace.slug,
                "is_home": link.is_home,
            }
            for link in instance.workspace_links.select_related("workspace")
            if request and link.workspace.is_shown_to(request.user)
        ]

    def get_members_role(self, instance):
        """
        Collaborators: in the list of a workspace's spaces (`?workspace=`),
        the role all its members have on the space, if they have one.
        """
        accesses = getattr(instance, "members_accesses", None)
        return accesses[0].role if accesses else None


class SpaceCreateSerializer(serializers.Serializer):
    """Validate the creation of a space."""

    title = serializers.CharField(max_length=255)
    workspace_id = serializers.UUIDField(required=False, allow_null=True)
    visibility = serializers.ChoiceField(
        choices=choices.SpaceVisibilityChoices.choices,
        default=choices.SpaceVisibilityChoices.INVITED,
    )
    editor_user_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )
    editor_group_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, default=list
    )

    def validate(self, attrs):
        """Check the workspace membership and the editors."""
        user = self.context["request"].user
        workspace = None

        if attrs.get("workspace_id"):
            workspace = models.Workspace.objects.filter(
                id=attrs["workspace_id"]
            ).first()
            if workspace is None or workspace.get_role(user) is None:
                raise serializers.ValidationError(
                    {"workspace_id": _("You are not a member of this workspace.")}
                )
        elif attrs["visibility"] == choices.SpaceVisibilityChoices.WORKSPACE:
            raise serializers.ValidationError(
                {"visibility": _("An independent space has no workspace members.")}
            )

        users = list(models.User.objects.filter(id__in=attrs["editor_user_ids"]))
        if len(users) != len(set(attrs["editor_user_ids"])):
            raise serializers.ValidationError(
                {"editor_user_ids": _("Some of these collaborators don't exist.")}
            )

        groups = list(models.Group.objects.filter(id__in=attrs["editor_group_ids"]))
        if len(groups) != len(set(attrs["editor_group_ids"])) or any(
            workspace is None or group.workspace_id != workspace.id for group in groups
        ):
            raise serializers.ValidationError(
                {
                    "editor_group_ids": _(
                        "User groups must belong to the space's workspace."
                    )
                }
            )

        attrs["workspace"] = workspace
        attrs["editor_users"] = users
        attrs["editor_groups"] = groups
        return attrs


class WorkspaceGrantSerializer(serializers.Serializer):
    """A role granted on a space to a group or to all members of a workspace."""

    team = serializers.CharField(max_length=100)
    role = serializers.ChoiceField(
        choices=[role for role in choices.RoleChoices.choices if role[0] != "owner"],
        default=choices.RoleChoices.READER,
    )


# -- Helpers


def get_team_workspace_id(team):
    """Return the id of the workspace a team string belongs to, or None."""
    kind, obj_id = models.parse_team(team)
    if kind in (models.TEAM_WORKSPACE, models.TEAM_WORKSPACE_ADMINS):
        return obj_id
    if kind == models.TEAM_GROUP:
        return (
            models.Group.objects.filter(id=obj_id)
            .values_list("workspace_id", flat=True)
            .first()
        )
    return None


def get_workspace_teams(workspace):
    """All the team strings that belong to a workspace."""
    return [
        models.make_team(models.TEAM_WORKSPACE, workspace.id),
        models.make_team(models.TEAM_WORKSPACE_ADMINS, workspace.id),
        *[
            models.make_team(models.TEAM_GROUP, group_id)
            for group_id in workspace.groups.values_list("id", flat=True)
        ],
    ]


def place_space_in_workspace(space, workspace):
    """Make a workspace the home of a space; its administrators own the space."""
    models.SpaceWorkspaceLink.objects.update_or_create(
        space=space, workspace=workspace, defaults={"is_home": True}
    )
    models.DocumentAccess.objects.update_or_create(
        document=space,
        team=models.make_team(models.TEAM_WORKSPACE_ADMINS, workspace.id),
        defaults={"role": choices.RoleChoices.OWNER},
    )


def is_workspace_admin(workspace, user):
    """True if the user owns or administers the workspace."""
    return workspace.get_role(user) in choices.WORKSPACE_PRIVILEGED_ROLES


# -- Viewsets


class WorkspaceViewSet(viewsets.ModelViewSet):
    """
    Workspaces of the logged-in collaborator.

    GET /api/v1.0/workspaces/ — the workspaces I belong to
    POST /api/v1.0/workspaces/ — create a workspace, I become its owner
    GET, PATCH, DELETE /api/v1.0/workspaces/<id>/
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = WorkspaceSerializer
    pagination_class = None

    def get_queryset(self):
        """Only the workspaces the user belongs to."""
        return models.Workspace.objects.filter(
            accesses__user=self.request.user
        ).distinct()

    @drf.decorators.action(detail=False, methods=["get"], url_path="my-teams")
    def my_teams(self, request):
        """
        The teams of the logged-in user (their groups and workspaces), e.g. to
        find the table rows assigned to one of their groups.
        """
        return drf.response.Response(request.user.teams)

    @drf.decorators.action(
        detail=True, methods=["post", "delete"], url_path="join-link"
    )
    def join_link(self, request, *args, **kwargs):
        """
        POST: turn the join link on, or change its secret (the old link stops
        working). DELETE: turn it off. For the workspace's admins.
        """
        workspace = self.get_object()
        if not is_workspace_admin(workspace, request.user):
            raise drf.exceptions.PermissionDenied()
        workspace.join_token = (
            joining.new_join_token() if request.method == "POST" else None
        )
        workspace.save(update_fields=["join_token", "updated_at"])
        return drf.response.Response({"join_token": workspace.join_token})

    @drf.decorators.action(detail=True, methods=["get"], url_path="join-requests")
    def join_requests(self, request, *args, **kwargs):
        """The people waiting for an admin's answer. For the workspace's admins."""
        workspace = self.get_object()
        if not is_workspace_admin(workspace, request.user):
            raise drf.exceptions.PermissionDenied()
        pending = workspace.join_requests.filter(
            status=choices.JoinRequestStatusChoices.PENDING
        ).select_related("user")
        return drf.response.Response(
            [
                {
                    "id": str(item.id),
                    "user": UserSerializer(item.user).data,
                    "via": item.via,
                    "created_at": item.created_at,
                }
                for item in pending
            ]
        )

    @drf.decorators.action(
        detail=True,
        methods=["post"],
        url_path=r"join-requests/(?P<request_id>[^/.]+)/(?P<decision>approve|decline)",
    )
    def answer_join_request(self, request, request_id, decision, *args, **kwargs):
        """Let someone in, or decline. For the workspace's admins."""
        workspace = self.get_object()
        if not is_workspace_admin(workspace, request.user):
            raise drf.exceptions.PermissionDenied()
        join_request = (
            workspace.join_requests.filter(
                pk=request_id, status=choices.JoinRequestStatusChoices.PENDING
            )
            .select_related("user", "group", "workspace")
            .first()
        )
        if join_request is None:
            raise drf.exceptions.NotFound()
        if decision == "approve":
            joining.approve(join_request, request.user)
        else:
            joining.decline(join_request)
        return drf.response.Response(status=status.HTTP_204_NO_CONTENT)

    def perform_create(self, serializer):
        """The creator becomes the owner of the workspace."""
        with transaction.atomic():
            workspace = serializer.save()
            models.WorkspaceAccess.objects.create(
                workspace=workspace,
                user=self.request.user,
                role=choices.WorkspaceRoleChoices.OWNER,
            )

    def perform_update(self, serializer):
        """Only administrators can rename a workspace."""
        if not is_workspace_admin(serializer.instance, self.request.user):
            raise drf.exceptions.PermissionDenied()
        serializer.save()

    def perform_destroy(self, instance):
        """Only owners delete a workspace; its spaces become independent."""
        if instance.get_role(self.request.user) != choices.WorkspaceRoleChoices.OWNER:
            raise drf.exceptions.PermissionDenied()
        with transaction.atomic():
            models.DocumentAccess.objects.filter(
                team__in=get_workspace_teams(instance)
            ).delete()
            instance.delete()


class WorkspaceNestedMixin:
    """Resolve the workspace of a nested route and check membership."""

    @cached_property
    def workspace(self):
        """The workspace in the URL, if the user belongs to it."""
        workspace = models.Workspace.objects.filter(
            id=self.kwargs["resource_id"]
        ).first()
        if workspace is None or workspace.get_role(self.request.user) is None:
            raise drf.exceptions.NotFound()
        return workspace

    def check_workspace_admin(self):
        """Raise unless the user administers the workspace."""
        if not is_workspace_admin(self.workspace, self.request.user):
            raise drf.exceptions.PermissionDenied()


class WorkspaceAccessViewSet(WorkspaceNestedMixin, viewsets.ModelViewSet):
    """
    Members of a workspace. Members can list them; administrators add existing
    collaborators, change roles and remove members; anyone can leave.

    /api/v1.0/workspaces/<resource_id>/accesses/[<id>/]
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = WorkspaceAccessSerializer
    pagination_class = None

    def get_queryset(self):
        """Members of the workspace in the URL."""
        return self.workspace.accesses.select_related("user").order_by(
            "user__full_name", "user__email"
        )

    def _check_role_change(self, role):
        """Only owners can make or unmake owners."""
        if (
            role == choices.WorkspaceRoleChoices.OWNER
            and self.workspace.get_role(self.request.user)
            != choices.WorkspaceRoleChoices.OWNER
        ):
            raise drf.exceptions.PermissionDenied(
                _("Only an owner can make someone an owner.")
            )

    def _check_not_last_owner(self, access):
        """A workspace always keeps at least one owner."""
        if (
            access.role == choices.WorkspaceRoleChoices.OWNER
            and self.workspace.accesses.filter(
                role=choices.WorkspaceRoleChoices.OWNER
            ).count()
            == 1
        ):
            raise drf.exceptions.ValidationError(
                {"role": _("A workspace must keep at least one owner.")}
            )

    def perform_create(self, serializer):
        """
        Administrators add existing collaborators, among those they may see;
        the others are invited by email.
        """
        self.check_workspace_admin()
        self._check_role_change(serializer.validated_data.get("role"))
        check_can_find(self.request.user, serializer.validated_data.get("user"))
        serializer.save(workspace=self.workspace)

    def perform_update(self, serializer):
        """Administrators change roles."""
        self.check_workspace_admin()
        new_role = serializer.validated_data.get("role", serializer.instance.role)
        self._check_role_change(new_role)
        self._check_role_change(serializer.instance.role)
        if new_role != choices.WorkspaceRoleChoices.OWNER:
            self._check_not_last_owner(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        """Administrators remove members; members can leave."""
        if instance.user_id != self.request.user.id:
            self.check_workspace_admin()
            self._check_role_change(instance.role)
        self._check_not_last_owner(instance)
        with transaction.atomic():
            models.GroupMembership.objects.filter(
                group__workspace=self.workspace, user_id=instance.user_id
            ).delete()
            instance.delete()


class GroupViewSet(WorkspaceNestedMixin, viewsets.ModelViewSet):
    """
    Groups of a workspace. Members can list them and create teams;
    administrators also create organizations. Administrators and each
    group's creator manage it.

    /api/v1.0/workspaces/<resource_id>/groups/[<id>/]
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = GroupSerializer
    pagination_class = None

    def get_queryset(self):
        """Groups of the workspace in the URL, with their size."""
        return self.workspace.groups.annotate(
            nb_members=Count("memberships")
        ).select_related("created_by", "workspace")

    def perform_create(self, serializer):
        """Members create teams; administrators also organizations."""
        if serializer.validated_data.get(
            "kind"
        ) == choices.GroupKindChoices.ORGANIZATION and not is_workspace_admin(
            self.workspace, self.request.user
        ):
            raise drf.exceptions.ValidationError(
                {"kind": _("Only administrators create organizations.")}
            )
        serializer.save(workspace=self.workspace, created_by=self.request.user)

    def _check_owner(self, group):
        if not group.get_abilities(self.request.user)["update"]:
            raise drf.exceptions.PermissionDenied()

    def perform_update(self, serializer):
        """Administrators and the creator rename the group."""
        self._check_owner(serializer.instance)
        if (
            serializer.validated_data.get("kind")
            == choices.GroupKindChoices.ORGANIZATION
            and serializer.instance.kind != choices.GroupKindChoices.ORGANIZATION
            and not is_workspace_admin(self.workspace, self.request.user)
        ):
            raise drf.exceptions.ValidationError(
                {"kind": _("Only administrators create organizations.")}
            )
        serializer.save()

    def perform_destroy(self, instance):
        """Administrators and the creator delete it, and the accesses granted to it."""
        self._check_owner(instance)
        with transaction.atomic():
            models.DocumentAccess.objects.filter(team=instance.team).delete()
            instance.delete()


class DocumentUserGroupViewSet(viewsets.ModelViewSet):
    """
    User groups of a page or a space, for mentions only (they never give
    access). Anyone who can see the page lists them; its owners and
    administrators create them, and manage them with each group's creator.
    Its members are managed with the members of any group, under `groups/`.

    /api/v1.0/documents/<resource_id>/user-groups/[<id>/]
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = GroupSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    @cached_property
    def document(self):
        """The page or space in the URL, if the user can see it."""
        document = models.Document.objects.filter(
            id=self.kwargs["resource_id"], ancestors_deleted_at__isnull=True
        ).first()
        if document is None or document.get_role(self.request.user) is None:
            raise drf.exceptions.NotFound()
        return document

    def get_queryset(self):
        """The groups of the page in the URL, with their size."""
        return self.document.user_groups.annotate(
            nb_members=Count("memberships")
        ).select_related("created_by", "document")

    def _check_name(self, name, group=None):
        taken = self.document.user_groups.filter(name=name)
        if group is not None:
            taken = taken.exclude(id=group.id)
        if taken.exists():
            raise drf.exceptions.ValidationError(
                {"name": _("A user group with this name already exists here.")}
            )

    def perform_create(self, serializer):
        """The page's owners and administrators create teams."""
        if self.document.get_role(self.request.user) not in choices.PRIVILEGED_ROLES:
            raise drf.exceptions.PermissionDenied()
        self._check_name(serializer.validated_data["name"])
        serializer.save(
            document=self.document,
            kind=choices.GroupKindChoices.TEAM,
            created_by=self.request.user,
        )

    def perform_update(self, serializer):
        """The page's owners and administrators, and the creator, rename it."""
        if not serializer.instance.get_abilities(self.request.user)["update"]:
            raise drf.exceptions.PermissionDenied()
        if "name" in serializer.validated_data:
            self._check_name(serializer.validated_data["name"], serializer.instance)
        serializer.save(kind=choices.GroupKindChoices.TEAM)

    def perform_destroy(self, instance):
        """The page's owners and administrators, and the creator, delete it."""
        if not instance.get_abilities(self.request.user)["destroy"]:
            raise drf.exceptions.PermissionDenied()
        instance.delete()


class GroupMembershipViewSet(viewsets.ModelViewSet):
    """
    Members of a group. Those who can see where it belongs (its workspace,
    or its page or space) list them; its administrators, its creator and
    its managers add and remove them.

    /api/v1.0/groups/<resource_id>/members/[<id>/]
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = GroupMembershipSerializer
    pagination_class = None

    @cached_property
    def group(self):
        """The group in the URL, if the user can see where it belongs."""
        group = (
            models.Group.objects.filter(id=self.kwargs["resource_id"])
            .select_related("workspace", "document")
            .first()
        )
        if group is None or not group.get_abilities(self.request.user)["retrieve"]:
            raise drf.exceptions.NotFound()
        return group

    def get_queryset(self):
        """Members of the group in the URL."""
        return self.group.memberships.select_related("user").order_by(
            "user__full_name", "user__email"
        )

    def _check_manager(self):
        if not self.group.get_abilities(self.request.user)["manage_members"]:
            raise drf.exceptions.PermissionDenied()

    def perform_create(self, serializer):
        """
        Only members of the workspace can join its groups; anyone one may
        find can join those of a page or a space.
        """
        self._check_manager()
        user = serializer.validated_data["user"]
        if self.group.workspace_id is None:
            check_can_find(self.request.user, user)
        elif self.group.workspace.get_role(user) is None:
            raise drf.exceptions.ValidationError(
                {"user_id": _("Add this collaborator to the workspace first.")}
            )
        serializer.save(group=self.group)

    def perform_update(self, serializer):
        """Workspace administrators and the group's creator appoint managers."""
        if not self.group.get_abilities(self.request.user)["manage_managers"]:
            raise drf.exceptions.PermissionDenied()
        serializer.save()

    @drf.decorators.action(detail=False, methods=["post"], url_path="transfer")
    def transfer(self, request, *args, **kwargs):
        """
        POST {user_ids, to_group_id, mode: "move" | "copy"}: put members of
        this group in another group of the same place (its workspace, or its
        page or space), and, to move them, take them out of this one. Needs
        the right to manage the members of both (administrators, the groups'
        creator or managers).
        """
        self._check_manager()
        target = models.Group.objects.filter(
            id=request.data.get("to_group_id"),
            workspace_id=self.group.workspace_id,
            document_id=self.group.document_id,
        ).first()
        if target is None or target == self.group:
            raise drf.exceptions.ValidationError(
                {"to_group_id": _("Choose another user group of the same place.")}
            )
        if not target.get_abilities(request.user)["manage_members"]:
            raise drf.exceptions.PermissionDenied()
        mode = request.data.get("mode", "move")
        if mode not in ("move", "copy"):
            raise drf.exceptions.ValidationError({"mode": _("Move or copy.")})
        user_ids = [str(user_id) for user_id in request.data.get("user_ids") or []]
        memberships = list(self.group.memberships.filter(user_id__in=user_ids))
        with transaction.atomic():
            for membership in memberships:
                models.GroupMembership.objects.get_or_create(
                    group=target, user_id=membership.user_id
                )
                if mode == "move":
                    membership.delete()
        return drf.response.Response({"count": len(memberships)})

    def perform_destroy(self, instance):
        """Managers remove members; members can leave."""
        if instance.user_id != self.request.user.id:
            self._check_manager()
        instance.delete()


def document_user_groups(document, query=""):
    """
    The user groups offered for mentions on a document: its own and those of
    the pages above it, the closest first, as teams to mention.
    """
    steplen = models.Document.steplen
    paths = [
        document.path[:end] for end in range(steplen, len(document.path) + 1, steplen)
    ]
    groups = (
        models.Group.objects.filter(document__path__in=paths)
        .annotate(member_count=Count("memberships"))
        .select_related("document")
        .order_by("-document__depth", "name")
    )
    if query:
        groups = groups.filter(name__icontains=query)
    return [
        {
            "team": group.team,
            "label": group.name,
            "kind": group.kind,
            "workspace": None,
            "place": {
                "kind": group.document.kind,
                "id": str(group.document_id),
                "name": group.place_name,
            },
            "member_count": group.member_count,
        }
        for group in groups
    ]


class GrantableTeamsView(APIView):
    """
    GET /api/v1.0/groups/?document_id=<id>&q=<text>[&include_granted=true]
        [&every_workspace=true]

    The groups and workspaces the logged-in user can grant a role to on a
    document, or mention in it: those of the workspaces its space is placed in
    and that the user belongs to. Independent pages and spaces have none.
    Teams that already have a role on the document are left out, unless
    `include_granted` (for mentions). With `every_workspace` (for mentions),
    all the groups of every workspace the user belongs to, those of the
    document's own workspaces first. Each comes with its number of members,
    and `place`: the workspace, page or space it belongs to.

    For mentions (`include_granted`), the user groups of the document and of
    the pages above it come first, the closest first, if the user can see
    the document. They are never offered for sharing: they give no access.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """Search grantable teams."""
        document = models.Document.objects.filter(
            id=request.query_params.get("document_id")
        ).first()
        every_workspace = request.query_params.get("every_workspace") in (
            "true",
            "1",
        )
        if document is None and not every_workspace:
            return drf.response.Response([])
        include_granted = request.query_params.get("include_granted") in (
            "true",
            "1",
        )

        own_workspaces = []
        if document is not None:
            root = document if document.is_root() else document.get_root()
            own_workspaces = list(
                models.Workspace.objects.filter(
                    space_links__space=root, accesses__user=request.user
                ).distinct()
            )
        workspaces = own_workspaces
        if every_workspace:
            others = models.Workspace.objects.filter(
                accesses__user=request.user
            ).exclude(id__in=[workspace.id for workspace in own_workspaces])
            workspaces = own_workspaces + list(others.distinct().order_by("name"))
        query = (request.query_params.get("q") or "").strip().lower()
        # Teams that already have a role on the document itself are left out
        granted = (
            set(document.accesses.exclude(team="").values_list("team", flat=True))
            if document is not None
            else set()
        )

        results = []
        if (
            include_granted
            and document is not None
            and document.get_role(request.user) is not None
        ):
            results.extend(document_user_groups(document, query))
        for workspace in workspaces:
            label = str(_("All members of {name}")).format(name=workspace.name)
            place = {
                "kind": "workspace",
                "id": str(workspace.id),
                "name": workspace.name,
            }
            if not query or query in label.lower():
                results.append(
                    {
                        "team": models.make_team(models.TEAM_WORKSPACE, workspace.id),
                        "label": label,
                        "kind": "workspace",
                        "workspace": {"id": str(workspace.id), "name": workspace.name},
                        "place": place,
                        "member_count": workspace.accesses.count(),
                    }
                )
            groups = workspace.groups.annotate(member_count=Count("memberships"))
            if query:
                groups = groups.filter(name__icontains=query)
            results.extend(
                {
                    "team": group.team,
                    "label": group.name,
                    "kind": group.kind,
                    "workspace": {"id": str(workspace.id), "name": workspace.name},
                    "place": place,
                    "member_count": group.member_count,
                }
                for group in (groups if every_workspace else groups[:20])
            )
        if include_granted:
            return drf.response.Response(results)
        return drf.response.Response(
            [result for result in results if result["team"] not in granted]
        )


class SpaceViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    Spaces: root documents of kind "space" holding pages.

    GET /api/v1.0/spaces/?workspace=<id> — spaces placed in a workspace
    GET /api/v1.0/spaces/?workspace=<id>&kind=page — pages placed directly in
        a workspace, in none of its spaces
    GET /api/v1.0/spaces/?independent=true — my independent spaces
    GET /api/v1.0/spaces/?mine=true — every space I was given a role on
    POST /api/v1.0/spaces/ — create a space (see SpaceCreateSerializer)
    POST /api/v1.0/spaces/<id>/move-to-workspace/ — give an independent space a home
    POST /api/v1.0/spaces/<id>/make-independent/ — take a space out of its workspaces
    GET /api/v1.0/spaces/<id>/linked-pages/ — pages of elsewhere linked into it
    POST, DELETE /api/v1.0/spaces/<id>/links/ — share a space with another workspace
    GET, POST, DELETE /api/v1.0/spaces/<id>/workspace-grants/ — roles a linked
        workspace grants to its own groups on the space

    Everything else about a space (title, content, pages, sharing, deletion)
    goes through the documents API, as a space is a document.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SpaceSerializer
    pagination_class = None

    def get_queryset(self):
        """Spaces readable by the user, through an access or their link."""
        user = self.request.user
        kind = (
            choices.DocumentKindChoices.PAGE
            if self.request.query_params.get("kind") == "page"
            else choices.DocumentKindChoices.SPACE
        )
        return (
            models.Document.objects.filter(
                kind=kind,
                depth=1,
                ancestors_deleted_at__isnull=True,
            )
            .filter(
                Q(accesses__user=user)
                | Q(accesses__team__in=user.teams)
                | ~Q(link_reach=choices.LinkReachChoices.RESTRICTED)
            )
            .distinct()
            .order_by("title")
        )

    def filter_queryset(self, queryset):
        """Filter by workspace, or keep independent spaces with a direct access."""
        user = self.request.user
        workspace_id = self.request.query_params.get("workspace")
        if workspace_id:
            workspace = models.Workspace.objects.filter(id=workspace_id).first()
            if workspace is None or workspace.get_role(user) is None:
                return queryset.none()
            # The role its members have on each, read in one query
            members = models.make_team(models.TEAM_WORKSPACE, workspace.id)
            return queryset.filter(
                workspace_links__workspace=workspace
            ).prefetch_related(
                Prefetch(
                    "accesses",
                    queryset=models.DocumentAccess.objects.filter(team=members),
                    to_attr="members_accesses",
                )
            )

        # The spaces I was given a role on, directly or through my groups
        if self.request.query_params.get("mine") in ("true", "1"):
            return queryset.filter(
                Q(accesses__user=user) | Q(accesses__team__in=user.teams)
            )

        if self.request.query_params.get("independent") in ("true", "1"):
            return queryset.filter(workspace_links__isnull=True).filter(
                Q(accesses__user=user) | Q(accesses__team__in=user.teams)
            )

        return queryset

    def get_object(self):
        """A space the user can read."""
        space = super().get_object()
        if not space.get_abilities(self.request.user)["retrieve"]:
            raise drf.exceptions.NotFound()
        return space

    def create(self, request, *args, **kwargs):
        """Create a space with its visibility and its editors."""
        create_serializer = SpaceCreateSerializer(
            data=request.data, context=self.get_serializer_context()
        )
        create_serializer.is_valid(raise_exception=True)
        data = create_serializer.validated_data
        workspace = data["workspace"]
        visibility = data["visibility"]
        is_public = visibility == choices.SpaceVisibilityChoices.PUBLIC

        with transaction.atomic():
            space = create_tree_node_with_retry(
                lambda: models.Document.add_root(
                    creator=request.user,
                    title=data["title"],
                    kind=choices.DocumentKindChoices.SPACE,
                    link_reach=choices.LinkReachChoices.PUBLIC
                    if is_public
                    else choices.LinkReachChoices.RESTRICTED,
                    link_role=choices.LinkRoleChoices.READER,
                )
            )
            models.DocumentAccess.objects.create(
                document=space, user=request.user, role=choices.RoleChoices.OWNER
            )
            if workspace is not None:
                place_space_in_workspace(space, workspace)
                if visibility == choices.SpaceVisibilityChoices.WORKSPACE:
                    models.DocumentAccess.objects.create(
                        document=space,
                        team=models.make_team(models.TEAM_WORKSPACE, workspace.id),
                        role=choices.RoleChoices.READER,
                    )
            for user in data["editor_users"]:
                if user.id != request.user.id:
                    models.DocumentAccess.objects.create(
                        document=space, user=user, role=choices.RoleChoices.EDITOR
                    )
            for group in data["editor_groups"]:
                models.DocumentAccess.objects.create(
                    document=space, team=group.team, role=choices.RoleChoices.EDITOR
                )

        serializer = self.get_serializer(space)
        return drf.response.Response(serializer.data, status=status.HTTP_201_CREATED)

    @drf.decorators.action(detail=True, methods=["post"], url_path="move-to-workspace")
    def move_to_workspace(self, request, *args, **kwargs):
        """The owner of an independent space places it in one of their workspaces."""
        space = self.get_object()
        if space.get_role(request.user) != choices.RoleChoices.OWNER:
            raise drf.exceptions.PermissionDenied()
        if space.workspace_links.exists():
            raise drf.exceptions.ValidationError(
                {"workspace_id": _("This space already belongs to a workspace.")}
            )
        workspace = models.Workspace.objects.filter(
            id=request.data.get("workspace_id")
        ).first()
        if workspace is None or workspace.get_role(request.user) is None:
            raise drf.exceptions.ValidationError(
                {"workspace_id": _("You are not a member of this workspace.")}
            )
        # Collaborators: its publishing policy holds for what moves in
        publishing.check_public_moving_in(request.user, space, workspace)
        with transaction.atomic():
            place_space_in_workspace(space, workspace)
        return drf.response.Response(self.get_serializer(space).data)

    @drf.decorators.action(
        detail=True,
        methods=["get"],
        url_path="linked-pages",
        # Collaborators: a public space's linked pages are public through it
        permission_classes=[drf.permissions.AllowAny],
    )
    def linked_pages(self, request, *args, **kwargs):
        """The pages of other spaces (or independent ones) linked into this one."""
        space = get_object_or_404_space(kwargs["pk"])
        if not space.get_abilities(request.user)["retrieve"]:
            raise drf.exceptions.NotFound()
        links = (
            space.linked_pages.filter(page__ancestors_deleted_at__isnull=True)
            .select_related("page")
            .order_by("page__title")
        )
        result = []
        for link in links:
            page = link.page
            root = page if page.is_root() else page.get_root()
            result.append(
                {
                    "link_id": str(link.id),
                    "page": {"id": str(page.id), "title": page.title},
                    # Collaborators: its home, named to those who can open it
                    "home": {"id": str(root.id), "title": root.title}
                    if root.is_space
                    and root.get_abilities(request.user).get("retrieve")
                    else None,
                }
            )
        return drf.response.Response(result)

    @drf.decorators.action(detail=True, methods=["post"], url_path="make-independent")
    def make_independent(self, request, *args, **kwargs):
        """
        Take a space out of its workspaces: by an administrator of its home
        workspace, who becomes its owner. The roles the workspaces gave on it
        (their members, admins and groups) go with them.
        """
        space = self.get_object()
        home = self._get_home_workspace(space)
        if home is None:
            raise drf.exceptions.ValidationError(
                {"space": _("This space is already independent.")}
            )
        if not is_workspace_admin(home, request.user):
            raise drf.exceptions.PermissionDenied()
        with transaction.atomic():
            # Collaborators: on its pages too
            models.drop_workspace_roles(
                space, space.workspace_links.values_list("workspace_id", flat=True)
            )
            space.workspace_links.all().delete()
            models.DocumentAccess.objects.update_or_create(
                document=space,
                user=request.user,
                defaults={"role": choices.RoleChoices.OWNER},
            )
        return drf.response.Response(self.get_serializer(space).data)

    def _get_home_workspace(self, space):
        link = space.workspace_links.filter(is_home=True).first()
        return link.workspace if link else None

    @drf.decorators.action(detail=True, methods=["post", "delete"], url_path="links")
    def links(self, request, *args, **kwargs):
        """
        POST {workspace_id}: home administrators share the space with another
        workspace they belong to.
        DELETE {workspace_id}: home administrators, or the administrators of
        the linked workspace, stop sharing it. The roles that workspace granted
        on the space are removed with the link.
        """
        # The administrators of a linked workspace may have no role on the
        # space itself: permissions are checked below, per method.
        space = get_object_or_404_space(kwargs["pk"])
        home = self._get_home_workspace(space)
        workspace = models.Workspace.objects.filter(
            id=request.data.get("workspace_id")
        ).first()
        if home is None or workspace is None or workspace.id == home.id:
            raise drf.exceptions.ValidationError(
                {"workspace_id": _("Choose another workspace than the space's home.")}
            )
        is_home_admin = is_workspace_admin(home, request.user)

        if request.method == "POST":
            if not is_home_admin:
                raise drf.exceptions.PermissionDenied()
            if workspace.get_role(request.user) is None:
                raise drf.exceptions.ValidationError(
                    {"workspace_id": _("You are not a member of this workspace.")}
                )
            models.SpaceWorkspaceLink.objects.get_or_create(
                space=space, workspace=workspace, defaults={"is_home": False}
            )
            return drf.response.Response(
                self.get_serializer(space).data, status=status.HTTP_201_CREATED
            )

        if not (is_home_admin or is_workspace_admin(workspace, request.user)):
            raise drf.exceptions.PermissionDenied()
        with transaction.atomic():
            # Collaborators: on its pages too
            models.drop_workspace_roles(space, [workspace.id])
            models.SpaceWorkspaceLink.objects.filter(
                space=space, workspace=workspace, is_home=False
            ).delete()
        return drf.response.Response(status=status.HTTP_204_NO_CONTENT)

    @drf.decorators.action(
        detail=True, methods=["get", "post", "delete"], url_path="workspace-grants"
    )
    def workspace_grants(self, request, *args, **kwargs):
        """
        The administrators of a workspace the space is shared with grant roles
        on it to their own groups, or to all their members, without needing a
        role on the space themselves.

        GET: the grants of the workspaces the user administers
        POST {team, role}: grant (owner excepted)
        DELETE {team}: revoke
        """
        space = get_object_or_404_space(kwargs["pk"])

        if request.method == "GET":
            administered = [
                link.workspace
                for link in space.workspace_links.select_related("workspace")
                if is_workspace_admin(link.workspace, request.user)
            ]
            teams = [
                team
                for workspace in administered
                for team in get_workspace_teams(workspace)
            ]
            grants = space.accesses.filter(team__in=teams).exclude(
                team__startswith=f"{models.TEAM_WORKSPACE_ADMINS}:"
            )
            return drf.response.Response(
                [
                    {
                        "team": access.team,
                        "label": models.get_team_label(access.team),
                        "role": access.role,
                    }
                    for access in grants
                ]
            )

        serializer = WorkspaceGrantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        team = serializer.validated_data["team"]
        workspace_id = get_team_workspace_id(team)
        kind, _obj_id = models.parse_team(team)
        link = (
            space.workspace_links.filter(workspace_id=workspace_id)
            .select_related("workspace")
            .first()
        )
        if (
            link is None
            or kind == models.TEAM_WORKSPACE_ADMINS
            or not is_workspace_admin(link.workspace, request.user)
        ):
            raise drf.exceptions.PermissionDenied()

        if request.method == "POST":
            access, _created = models.DocumentAccess.objects.update_or_create(
                document=space,
                team=team,
                defaults={"role": serializer.validated_data["role"]},
            )
            return drf.response.Response(
                {
                    "team": access.team,
                    "label": models.get_team_label(access.team),
                    "role": access.role,
                },
                status=status.HTTP_201_CREATED,
            )

        space.accesses.filter(team=team).delete()
        return drf.response.Response(status=status.HTTP_204_NO_CONTENT)


def get_object_or_404_space(pk):
    """Any non deleted space, whatever the user's role on it."""
    space = models.Document.objects.filter(
        pk=pk,
        kind=choices.DocumentKindChoices.SPACE,
        ancestors_deleted_at__isnull=True,
    ).first()
    if space is None:
        raise drf.exceptions.NotFound()
    return space


class JoinWorkspaceView(APIView):
    """
    GET  /join/<token>/ — which workspace the link opens, for anyone holding it
    POST /join/<token>/ — join it, signed in; or ask its admins, when they
    approve who joins
    """

    def get_permissions(self):
        """Anyone with the link can see where it leads."""
        if self.request.method == "GET":
            return [drf.permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def _workspace(self, token):
        workspace = models.Workspace.objects.filter(join_token=token).first()
        if not token or workspace is None:
            raise drf.exceptions.NotFound(_("This join link doesn't work any more."))
        return workspace

    def _describe(self, workspace, user):
        return {
            "id": str(workspace.id),
            "name": workspace.name,
            "description": workspace.description,
            "member_count": workspace.accesses.count(),
            "is_member": user.is_authenticated
            and workspace.accesses.filter(user=user).exists(),
            "join_approval": workspace.join_approval,
            # "pending" or "declined" once asked
            "request_status": joining.request_status(workspace, user),
        }

    def get(self, request, token):
        """Describe the workspace."""
        workspace = self._workspace(token)
        return drf.response.Response(self._describe(workspace, request.user))

    def post(self, request, token):
        """Join the workspace as a member, or ask to."""
        workspace = self._workspace(token)
        joining.admit(workspace, request.user)
        return drf.response.Response(self._describe(workspace, request.user))


# -- Finding workspaces


def directory_card(workspace, user):
    """What anyone allowed to find a workspace sees of it."""
    is_member = user.is_authenticated and workspace.accesses.filter(user=user).exists()
    # Collaborators: its own spaces and those shared with it, open to the
    # viewer by their link (public, or to everyone signed in)
    reaches = [choices.LinkReachChoices.PUBLIC]
    if user.is_authenticated:
        reaches.append(choices.LinkReachChoices.AUTHENTICATED)
    public_spaces = (
        models.Document.objects.filter(
            workspace_links__workspace=workspace,
            kind=choices.DocumentKindChoices.SPACE,
            link_reach__in=reaches,
            ancestors_deleted_at__isnull=True,
        )
        .distinct()
        .order_by("title")[:10]
    )
    return {
        "id": str(workspace.id),
        "name": workspace.name,
        "slug": workspace.slug,
        "description": workspace.description,
        "visibility": workspace.visibility,
        "member_count": workspace.accesses.count(),
        "is_member": is_member,
        "request_status": joining.request_status(workspace, user),
        "public_spaces": [
            {"id": str(space.id), "title": space.title} for space in public_spaces
        ],
    }


def findable_workspaces(user):
    """Public workspaces for anyone; those open to the platform when signed in."""
    visibilities = [choices.WorkspaceVisibilityChoices.PUBLIC]
    if user.is_authenticated:
        visibilities.append(choices.WorkspaceVisibilityChoices.PLATFORM)
    return models.Workspace.objects.filter(visibility__in=visibilities)


class WorkspaceDirectoryView(APIView):
    """
    GET /api/v1.0/workspaces/discover/?q=<text> — the workspaces one can find:
    public ones for anyone, and those open to everyone on Collaborators when
    signed in. Hidden workspaces never show.
    """

    permission_classes = [drf.permissions.AllowAny]

    def get(self, request):
        """Matching findable workspaces, by name."""
        workspaces = findable_workspaces(request.user)
        query = (request.query_params.get("q") or "").strip()
        if query:
            workspaces = workspaces.filter(
                Q(name__icontains=query) | Q(description__icontains=query)
            )
        return drf.response.Response(
            [
                directory_card(workspace, request.user)
                for workspace in workspaces.order_by("name")[:100]
            ]
        )


class AskToJoinView(APIView):
    """
    POST /api/v1.0/workspaces/<id>/ask-to-join/ — from "Discover workspaces":
    the workspace's administrators get a request to approve.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, workspace_id):
        """Ask to join a findable workspace."""
        workspace = findable_workspaces(request.user).filter(id=workspace_id).first()
        if workspace is None:
            raise drf.exceptions.NotFound()
        joining.admit(
            workspace,
            request.user,
            via=choices.JoinViaChoices.DIRECTORY,
            always_ask=True,
        )
        return drf.response.Response(directory_card(workspace, request.user))
