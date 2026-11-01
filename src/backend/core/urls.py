"""URL configuration for the core app."""

from django.conf import settings
from django.urls import include, path, re_path

from lasuite.oidc_login.urls import urlpatterns as oidc_urls
from lasuite.oidc_resource_server.urls import urlpatterns as oidc_resource_server_urls
from rest_framework.routers import DefaultRouter

from core.api import (
    assistants,
    collaborations,
    dashboard,
    invitations,
    labels,
    notifications,
    page_links,
    people,
    platform,
    presentations,
    profiles,
    publishing,
    registrations,
    search,
    signin_methods,
    viewsets,
    visibility,
    workspaces,
)
from core.external_api import viewsets as external_api_viewsets

# - Main endpoints
router = DefaultRouter()
router.register("documents", viewsets.DocumentViewSet, basename="documents")
router.register("users", viewsets.UserViewSet, basename="users")
router.register("workspaces", workspaces.WorkspaceViewSet, basename="workspaces")
router.register("spaces", workspaces.SpaceViewSet, basename="spaces")
router.register(
    "notifications", notifications.NotificationViewSet, basename="notifications"
)

# - Routes nested under a workspace
workspace_related_router = DefaultRouter()
workspace_related_router.register(
    "accesses", workspaces.WorkspaceAccessViewSet, basename="workspace_accesses"
)
workspace_related_router.register(
    "groups", workspaces.GroupViewSet, basename="workspace_groups"
)

# - Routes nested under a group
group_related_router = DefaultRouter()
group_related_router.register(
    "members", workspaces.GroupMembershipViewSet, basename="group_members"
)

# - Routes nested under a document
document_related_router = DefaultRouter()
document_related_router.register(
    "accesses",
    viewsets.DocumentAccessViewSet,
    basename="document_accesses",
)
document_related_router.register(
    "invitations",
    viewsets.InvitationViewset,
    basename="invitations",
)
document_related_router.register(
    "threads",
    viewsets.ThreadViewSet,
    basename="threads",
)
document_related_router.register(
    "ask-for-access",
    viewsets.DocumentAskForAccessViewSet,
    basename="ask_for_access",
)

thread_related_router = DefaultRouter()
thread_related_router.register(
    "comments",
    viewsets.CommentViewSet,
    basename="comments",
)

# - Resource server routes
external_api_router = DefaultRouter()
external_api_router.register(
    "documents",
    external_api_viewsets.ResourceServerDocumentViewSet,
    basename="resource_server_documents",
)
external_api_router.register(
    "users",
    external_api_viewsets.ResourceServerUserViewSet,
    basename="resource_server_users",
)


urlpatterns = [
    path(
        f"api/{settings.API_VERSION}/",
        include(
            [
                # before the router, whose users/<id>/ would take them
                path(
                    "users/me/sign-in-methods/",
                    signin_methods.SignInMethodsView.as_view(),
                ),
                path(
                    "users/me/sign-in-methods/<slug:provider>/",
                    signin_methods.SignInMethodView.as_view(),
                ),
                path(
                    "users/me/sign-in-methods/<slug:provider>/add/",
                    signin_methods.AddSignInAccountView.as_view(),
                ),
                path(
                    "users/me/sign-in-methods/<slug:provider>/accounts/<uuid:identity_id>/",
                    signin_methods.SignInAccountView.as_view(),
                ),
                path("users/me/merge/", signin_methods.MergeView.as_view()),
                path("users/me/assistants/", assistants.AssistantsView.as_view()),
                path(
                    "users/me/assistants/<str:client_id>/",
                    assistants.AssistantView.as_view(),
                ),
                path("users/me/hints/", signin_methods.HintsView.as_view()),
                path(
                    "documents/<uuid:pk>/space-links/",
                    page_links.PageSpaceLinksView.as_view(),
                ),
                path(
                    "documents/<uuid:pk>/space-links/<uuid:link_id>/",
                    page_links.PageSpaceLinkView.as_view(),
                ),
                path("profiles/me/", profiles.MyProfileView.as_view()),
                path("profiles/<uuid:user_id>/", profiles.ProfileView.as_view()),
                path("labels/", labels.LabelListView.as_view()),
                path("labels/cloud/", labels.LabelCloudView.as_view()),
                path("labels/<str:name>/", labels.LabelDetailView.as_view()),
                path(
                    "documents/<uuid:resource_id>/labels/",
                    labels.DocumentLabelsView.as_view(),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/labels/",
                    labels.WorkspaceLabelsView.as_view(),
                ),
                path(
                    "workspaces/discover/",
                    workspaces.WorkspaceDirectoryView.as_view(),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/ask-to-join/",
                    workspaces.AskToJoinView.as_view(),
                ),
                path(
                    "documents/<uuid:resource_id>/visibility/",
                    visibility.DocumentVisibilityView.as_view(),
                ),
                path(
                    "documents/<uuid:pk>/report/",
                    platform.ReportPageView.as_view(),
                ),
                path(
                    "documents/<uuid:pk>/make-independent/",
                    page_links.MakePageIndependentView.as_view(),
                ),
                path(
                    "documents/<uuid:pk>/move-to-workspace/",
                    page_links.MovePageToWorkspaceView.as_view(),
                ),
                *router.urls,
                *oidc_urls,
                path("groups/", workspaces.GrantableTeamsView.as_view()),
                path("registrations/", registrations.RegistrationListView.as_view()),
                path(
                    "registrations/<uuid:user_id>/approve/",
                    registrations.RegistrationDecisionView.as_view(decision="approve"),
                ),
                path(
                    "registrations/<uuid:user_id>/decline/",
                    registrations.RegistrationDecisionView.as_view(decision="decline"),
                ),
                path("platform/people/", platform.PlatformPeopleView.as_view()),
                path(
                    "platform/people/<uuid:user_id>/suspend/",
                    platform.AccountActionView.as_view(action="suspend"),
                ),
                path(
                    "platform/people/<uuid:user_id>/reinstate/",
                    platform.AccountActionView.as_view(action="reinstate"),
                ),
                path(
                    "platform/people/<uuid:user_id>/removal/",
                    platform.AccountActionView.as_view(action="remove"),
                ),
                path(
                    "platform/people/<uuid:user_id>/remove/",
                    platform.AccountActionView.as_view(action="remove"),
                ),
                path(
                    "platform/people/<uuid:user_id>/level/",
                    platform.AccountActionView.as_view(action="level"),
                ),
                path("platform/reports/", platform.PlatformReportsView.as_view()),
                path(
                    "platform/reports/<uuid:report_id>/dismiss/",
                    platform.ReportDecisionView.as_view(decision="dismiss"),
                ),
                path(
                    "platform/reports/<uuid:report_id>/take-down/",
                    platform.ReportDecisionView.as_view(decision="take_down"),
                ),
                path(
                    "platform/reports/<uuid:report_id>/put-back/",
                    platform.ReportDecisionView.as_view(decision="put_back"),
                ),
                path("platform/settings/", platform.PlatformSettingsView.as_view()),
                path("platform/blocked/", platform.BlockedEmailListView.as_view()),
                path(
                    "platform/blocked/<uuid:blocked_id>/",
                    platform.BlockedEmailView.as_view(),
                ),
                path("collaborations/", collaborations.CollaborationsView.as_view()),
                # Collaborators: HTML presentations shown in pages
                path("presentations/", presentations.PresentationListView.as_view()),
                path(
                    "presentations/storage/",
                    presentations.PresentationStorageView.as_view(),
                ),
                path(
                    "presentations/upload/<str:token>/",
                    presentations.PresentationUploadView.as_view(),
                ),
                path(
                    "presentations/<uuid:pk>/",
                    presentations.PresentationDetailView.as_view(),
                ),
                path(
                    "presentations/<uuid:pk>/file/",
                    presentations.PresentationFileView.as_view(),
                ),
                path(
                    "presentations/guide/",
                    presentations.PresentationGuideView.as_view(),
                ),
                path(
                    "presentations/<uuid:pk>/pdf-file/",
                    presentations.PresentationPdfFileView.as_view(),
                ),
                path(
                    "presentations/<uuid:pk>/slides/",
                    presentations.PresentationSlidesView.as_view(),
                ),
                path(
                    "presentations/<uuid:pk>/content/",
                    presentations.PresentationContentView.as_view(),
                ),
                path(
                    "presentations/<uuid:pk>/versions/",
                    presentations.PresentationVersionsView.as_view(),
                ),
                path(
                    "presentations/<uuid:pk>/versions/<uuid:version_id>/restore/",
                    presentations.PresentationRestoreView.as_view(),
                ),
                path(
                    "presentations/<uuid:pk>/pdf/",
                    presentations.PresentationPdfView.as_view(),
                ),
                path("search/", search.SearchView.as_view()),
                path(
                    "workspaces/<uuid:workspace_id>/favorite/",
                    collaborations.WorkspaceFavoriteView.as_view(),
                ),
                path("people/", people.KnownPeopleView.as_view()),
                path("people/directory/", people.PeopleDirectoryView.as_view()),
                path("invitations/<str:token>/", invitations.InvitationView.as_view()),
                path(
                    "invitations/<str:token>/logo/",
                    invitations.InvitationLogoView.as_view(),
                ),
                path(
                    "invitations/<str:token>/accept/",
                    invitations.AcceptInvitationView.as_view(),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/invitations/",
                    invitations.WorkspaceInvitationsView.as_view(),
                ),
                path(
                    "workspaces/<uuid:workspace_id>/invitations/<uuid:invitation_id>/",
                    invitations.WorkspaceInvitationView.as_view(),
                ),
                path(
                    "workspaces/<uuid:pk>/logo/",
                    invitations.WorkspaceLogoView.as_view(),
                ),
                path(
                    "documents/<uuid:pk>/logo/", invitations.DocumentLogoView.as_view()
                ),
                path("people/<uuid:user_id>/", people.PersonCardView.as_view()),
                path("teams/<str:team>/", people.TeamCardView.as_view()),
                path("join/<str:token>/", workspaces.JoinWorkspaceView.as_view()),
                path("dashboard/layout/", dashboard.DashboardLayoutView.as_view()),
                path("dashboard/sidebar/", dashboard.SidebarOrderView.as_view()),
                path("dashboard/sidebar/side/", dashboard.SidebarSideView.as_view()),
                path("dashboard/recent/", dashboard.DashboardRecentView.as_view()),
                path("dashboard/assigned/", dashboard.DashboardAssignedView.as_view()),
                path(
                    "documents/<uuid:resource_id>/assignments/",
                    dashboard.DocumentAssignmentsView.as_view(),
                ),
                path(
                    "documents/<uuid:resource_id>/publication/",
                    publishing.DocumentPublicationView.as_view(),
                ),
                path(
                    "spaces/<uuid:resource_id>/wiki/",
                    publishing.SpaceWikiView.as_view(),
                ),
                path(
                    "spaces/<uuid:resource_id>/wiki/release/",
                    publishing.SpaceWikiReleaseView.as_view(),
                ),
                path("wiki/<slug:slug>/", publishing.PublicWikiView.as_view()),
                path("wiki/<slug:slug>/search/", publishing.WikiSearchView.as_view()),
                path(
                    "wiki/<slug:slug>/pages/<uuid:page_id>/",
                    publishing.WikiPageView.as_view(),
                ),
                path("wiki-hosts/<str:host>/", publishing.WikiHostView.as_view()),
                path("tls-allowed/", publishing.TlsAllowedView.as_view()),
                path(
                    "workspaces/<uuid:resource_id>/publication-log/",
                    publishing.PublicationLogView.as_view(),
                ),
                re_path(
                    r"^workspaces/(?P<resource_id>[0-9a-z-]*)/",
                    include(workspace_related_router.urls),
                ),
                re_path(
                    r"^groups/(?P<resource_id>[0-9a-z-]*)/",
                    include(group_related_router.urls),
                ),
                re_path(
                    r"^documents/(?P<resource_id>[0-9a-z-]*)/",
                    include(document_related_router.urls),
                ),
                re_path(
                    r"^documents/(?P<resource_id>[0-9a-z-]*)/threads/(?P<thread_id>[0-9a-z-]*)/",
                    include(thread_related_router.urls),
                ),
                path(
                    "user-reconciliations/<str:user_type>/<uuid:confirmation_id>/",
                    viewsets.ReconciliationConfirmView.as_view(),
                ),
            ]
        ),
    ),
    path(f"api/{settings.API_VERSION}/config/", viewsets.ConfigView.as_view()),
    # Public keys validating the tokens we issue to call external services.
    # Nested under "api/" because this is the only prefix routed to the backend
    # by the ingress, a root "/.well-known/" would be served by the frontend.
    path(
        f"api/{settings.API_VERSION}/jwks",
        viewsets.JWKSView.as_view(),
        name="jwks",
    ),
]

if settings.OIDC_RESOURCE_SERVER_ENABLED:
    # - Routes nested under a document in external API
    external_api_document_related_router = DefaultRouter()

    document_access_config = settings.EXTERNAL_API.get("document_access", {})
    if document_access_config.get("enabled", False):
        external_api_document_related_router.register(
            "accesses",
            external_api_viewsets.ResourceServerDocumentAccessViewSet,
            basename="resource_server_document_accesses",
        )

    document_invitation_config = settings.EXTERNAL_API.get("document_invitation", {})
    if document_invitation_config.get("enabled", False):
        external_api_document_related_router.register(
            "invitations",
            external_api_viewsets.ResourceServerInvitationViewSet,
            basename="resource_server_document_invitations",
        )

    urlpatterns.append(
        path(
            f"external_api/{settings.API_VERSION}/",
            include(
                [
                    *external_api_router.urls,
                    re_path(
                        r"^documents/(?P<resource_id>[0-9a-z-]*)/",
                        include(external_api_document_related_router.urls),
                    ),
                ]
            ),
        )
    )

    if settings.OIDC_RS_PRIVATE_KEY_STR:
        # Served under "external_api/" alongside the rest of the resource
        # server, so that it does not collide with the JWKS of the tokens we
        # issue, which lives at "api/<version>/jwks".
        urlpatterns.append(
            path(
                f"external_api/{settings.API_VERSION}/",
                include([*oidc_resource_server_urls]),
            )
        )
