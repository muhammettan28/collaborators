import {
  UseQueryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';

import { APIError, errorCauses, fetchAPI } from '@/api';
import { User } from '@/features/auth';
import { KEY_DOC, KEY_LIST_DOC } from '@/features/docs/doc-management';

import {
  GrantableTeam,
  Group,
  GroupKind,
  GroupMembership,
  PublishingPolicy,
  Space,
  SpaceVisibility,
  Workspace,
  WorkspaceAccess,
  WorkspaceGrant,
  WorkspaceRole,
  WorkspaceVisibility,
} from './types';

export const KEY_LIST_WORKSPACE = 'workspaces';
export const KEY_LIST_WORKSPACE_ACCESS = 'workspace-accesses';
export const KEY_LIST_GROUP = 'workspace-groups';
export const KEY_LIST_GROUP_MEMBER = 'group-members';
export const KEY_LIST_SPACE = 'spaces';
export const KEY_LIST_GRANTABLE_TEAM = 'grantable-teams';
export const KEY_LIST_WORKSPACE_GRANT = 'workspace-grants';

/** Call the API and parse the JSON answer, or throw an APIError. */
const request = async <T>(
  url: string,
  errorMessage: string,
  init?: RequestInit,
): Promise<T> => {
  const response = await fetchAPI(url, init);
  if (!response.ok) {
    throw new APIError(errorMessage, await errorCauses(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
};

const jsonInit = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
});

// -- Workspaces

export function useWorkspaces(
  queryConfig?: Omit<UseQueryOptions<Workspace[], APIError>, 'queryKey'>,
) {
  return useQuery<Workspace[], APIError>({
    queryKey: [KEY_LIST_WORKSPACE],
    queryFn: () =>
      request<Workspace[]>('workspaces/', 'Failed to get the workspaces'),
    ...queryConfig,
  });
}

export function useCreateWorkspace() {
  const queryClient = useQueryClient();
  return useMutation<Workspace, APIError, { name: string }>({
    mutationFn: (data) =>
      request<Workspace>(
        'workspaces/',
        'Failed to create the workspace',
        jsonInit('POST', data),
      ),
    onSuccess: (workspace) => {
      // Known right away, so it can be selected before the list is refetched
      queryClient.setQueryData<Workspace[]>([KEY_LIST_WORKSPACE], (list) => [
        ...(list ?? []),
        workspace,
      ]);
      void queryClient.invalidateQueries({ queryKey: [KEY_LIST_WORKSPACE] });
    },
  });
}

export function useUpdateWorkspace() {
  const queryClient = useQueryClient();
  return useMutation<
    Workspace,
    APIError,
    {
      id: string;
      name?: string;
      description?: string;
      publishing_policy?: PublishingPolicy;
      visibility?: WorkspaceVisibility;
      join_domains?: string[];
      join_group?: string | null;
      /** Organisation ids */
      join_organizations?: string[];
      join_approval?: boolean;
    }
  >({
    mutationFn: ({ id, ...data }) =>
      request<Workspace>(
        `workspaces/${id}/`,
        'Failed to update the workspace',
        jsonInit('PATCH', data),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [KEY_LIST_WORKSPACE] });
    },
  });
}

export function useDeleteWorkspace() {
  const queryClient = useQueryClient();
  return useMutation<void, APIError, { id: string }>({
    mutationFn: ({ id }) =>
      request<void>(
        `workspaces/${id}/`,
        'Failed to delete the workspace',
        jsonInit('DELETE'),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [KEY_LIST_WORKSPACE] });
      void queryClient.invalidateQueries({ queryKey: [KEY_LIST_SPACE] });
    },
  });
}

// -- Workspace members

export function useWorkspaceAccesses(workspaceId: string) {
  return useQuery<WorkspaceAccess[], APIError>({
    queryKey: [KEY_LIST_WORKSPACE_ACCESS, workspaceId],
    queryFn: () =>
      request<WorkspaceAccess[]>(
        `workspaces/${workspaceId}/accesses/`,
        'Failed to get the members',
      ),
    enabled: !!workspaceId,
  });
}

export function useWorkspaceAccessMutations(workspaceId: string) {
  const queryClient = useQueryClient();
  const onSuccess = () => {
    void queryClient.invalidateQueries({
      queryKey: [KEY_LIST_WORKSPACE_ACCESS, workspaceId],
    });
    void queryClient.invalidateQueries({ queryKey: [KEY_LIST_WORKSPACE] });
  };
  const url = `workspaces/${workspaceId}/accesses/`;

  return {
    add: useMutation<
      WorkspaceAccess,
      APIError,
      { userId: string; role?: WorkspaceRole }
    >({
      mutationFn: ({ userId, role }) =>
        request(
          url,
          'Failed to add the member',
          jsonInit('POST', { user_id: userId, role }),
        ),
      onSuccess,
    }),
    update: useMutation<
      WorkspaceAccess,
      APIError,
      { accessId: string; role: WorkspaceRole }
    >({
      mutationFn: ({ accessId, role }) =>
        request(
          `${url}${accessId}/`,
          'Failed to change the role',
          jsonInit('PATCH', { role }),
        ),
      onSuccess,
    }),
    remove: useMutation<void, APIError, { accessId: string }>({
      mutationFn: ({ accessId }) =>
        request(
          `${url}${accessId}/`,
          'Failed to remove the member',
          jsonInit('DELETE'),
        ),
      onSuccess,
    }),
  };
}

// -- Groups

export function useGroups(workspaceId: string) {
  return useQuery<Group[], APIError>({
    queryKey: [KEY_LIST_GROUP, workspaceId],
    queryFn: () =>
      request<Group[]>(
        `workspaces/${workspaceId}/groups/`,
        'Failed to get the groups',
      ),
    enabled: !!workspaceId,
  });
}

export function useGroupMutations(workspaceId: string) {
  const queryClient = useQueryClient();
  const onSuccess = () => {
    void queryClient.invalidateQueries({
      queryKey: [KEY_LIST_GROUP, workspaceId],
    });
  };
  const url = `workspaces/${workspaceId}/groups/`;

  return {
    create: useMutation<Group, APIError, { name: string; kind: GroupKind }>({
      mutationFn: (data) =>
        request(url, 'Failed to create the group', jsonInit('POST', data)),
      onSuccess,
    }),
    update: useMutation<
      Group,
      APIError,
      { groupId: string; name?: string; kind?: GroupKind }
    >({
      mutationFn: ({ groupId, ...data }) =>
        request(
          `${url}${groupId}/`,
          'Failed to update the group',
          jsonInit('PATCH', data),
        ),
      onSuccess,
    }),
    remove: useMutation<void, APIError, { groupId: string }>({
      mutationFn: ({ groupId }) =>
        request(
          `${url}${groupId}/`,
          'Failed to delete the group',
          jsonInit('DELETE'),
        ),
      onSuccess,
    }),
  };
}

// -- User groups of a page or a space, for mentions only

export function useDocUserGroups(docId: string) {
  return useQuery<Group[], APIError>({
    queryKey: [KEY_LIST_GROUP, 'document', docId],
    queryFn: () =>
      request<Group[]>(
        `documents/${docId}/user-groups/`,
        'Failed to get the groups',
      ),
    enabled: !!docId,
  });
}

export function useDocUserGroupMutations(docId: string) {
  const queryClient = useQueryClient();
  const onSuccess = () => {
    void queryClient.invalidateQueries({
      queryKey: [KEY_LIST_GROUP, 'document', docId],
    });
    // The @ menu offers them
    void queryClient.invalidateQueries({ queryKey: [KEY_LIST_GRANTABLE_TEAM] });
  };
  const url = `documents/${docId}/user-groups/`;

  return {
    create: useMutation<Group, APIError, { name: string }>({
      mutationFn: (data) =>
        request(url, 'Failed to create the group', jsonInit('POST', data)),
      onSuccess,
    }),
    remove: useMutation<void, APIError, { groupId: string }>({
      mutationFn: ({ groupId }) =>
        request(
          `${url}${groupId}/`,
          'Failed to delete the group',
          jsonInit('DELETE'),
        ),
      onSuccess,
    }),
  };
}

export function useGroupMembers(groupId: string) {
  return useQuery<GroupMembership[], APIError>({
    queryKey: [KEY_LIST_GROUP_MEMBER, groupId],
    queryFn: () =>
      request<GroupMembership[]>(
        `groups/${groupId}/members/`,
        'Failed to get the group members',
      ),
    enabled: !!groupId,
  });
}

export function useGroupMemberMutations(groupId: string) {
  const queryClient = useQueryClient();
  const onSuccess = () => {
    void queryClient.invalidateQueries({
      queryKey: [KEY_LIST_GROUP_MEMBER, groupId],
    });
    void queryClient.invalidateQueries({ queryKey: [KEY_LIST_GROUP] });
  };
  const url = `groups/${groupId}/members/`;

  return {
    add: useMutation<GroupMembership, APIError, { userId: string }>({
      mutationFn: ({ userId }) =>
        request(
          url,
          'Failed to add the member',
          jsonInit('POST', { user_id: userId }),
        ),
      onSuccess,
    }),
    update: useMutation<
      GroupMembership,
      APIError,
      { membershipId: string; isManager: boolean }
    >({
      mutationFn: ({ membershipId, isManager }) =>
        request(
          `${url}${membershipId}/`,
          'Failed to update the member',
          jsonInit('PATCH', { is_manager: isManager }),
        ),
      onSuccess,
    }),
    transfer: useMutation<
      { count: number },
      APIError,
      { userIds: string[]; toGroupId: string; mode: 'move' | 'copy' }
    >({
      mutationFn: ({ userIds, toGroupId, mode }) =>
        request(
          `${url}transfer/`,
          'Failed to move the members',
          jsonInit('POST', {
            user_ids: userIds,
            to_group_id: toGroupId,
            mode,
          }),
        ),
      onSuccess: () => {
        // Both groups changed
        void queryClient.invalidateQueries({
          queryKey: [KEY_LIST_GROUP_MEMBER],
        });
        void queryClient.invalidateQueries({ queryKey: [KEY_LIST_GROUP] });
      },
    }),
    remove: useMutation<void, APIError, { membershipId: string }>({
      mutationFn: ({ membershipId }) =>
        request(
          `${url}${membershipId}/`,
          'Failed to remove the member',
          jsonInit('DELETE'),
        ),
      onSuccess,
    }),
  };
}

// -- Spaces

export type SpacesParams =
  | {
      workspaceId: string;
      /** The pages placed directly in the workspace, not its spaces */
      pages?: boolean;
      independent?: never;
      mine?: never;
    }
  | { independent: true; workspaceId?: never; mine?: never; pages?: never }
  | { mine: true; workspaceId?: never; independent?: never; pages?: never };

export function useSpaces(params: SpacesParams, enabled = true) {
  return useQuery<Space[], APIError>({
    queryKey: [KEY_LIST_SPACE, params],
    queryFn: () =>
      request<Space[]>(
        `spaces/?${
          params.mine
            ? 'mine=true'
            : params.independent
              ? 'independent=true'
              : `workspace=${params.workspaceId}${
                  params.pages ? '&kind=page' : ''
                }`
        }`,
        'Failed to get the spaces',
      ),
    enabled,
  });
}

export interface CreateSpaceParams {
  title: string;
  workspaceId?: string;
  visibility: SpaceVisibility;
  editorUserIds: string[];
  editorGroupIds: string[];
}

export function useCreateSpace() {
  const queryClient = useQueryClient();
  return useMutation<Space, APIError, CreateSpaceParams>({
    mutationFn: (params) =>
      request<Space>(
        'spaces/',
        'Failed to create the space',
        jsonInit('POST', {
          title: params.title,
          workspace_id: params.workspaceId,
          visibility: params.visibility,
          editor_user_ids: params.editorUserIds,
          editor_group_ids: params.editorGroupIds,
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [KEY_LIST_SPACE] });
    },
  });
}

export function useSpaceMutations(spaceId: string) {
  const queryClient = useQueryClient();
  const onSuccess = () => {
    void queryClient.invalidateQueries({ queryKey: [KEY_LIST_SPACE] });
    void queryClient.invalidateQueries({ queryKey: [KEY_DOC] });
    void queryClient.invalidateQueries({ queryKey: [KEY_LIST_DOC] });
  };
  return {
    moveToWorkspace: useMutation<Space, APIError, { workspaceId: string }>({
      mutationFn: ({ workspaceId }) =>
        request(
          `spaces/${spaceId}/move-to-workspace/`,
          'Failed to move the space',
          jsonInit('POST', { workspace_id: workspaceId }),
        ),
      onSuccess,
    }),
    link: useMutation<Space, APIError, { workspaceId: string }>({
      mutationFn: ({ workspaceId }) =>
        request(
          `spaces/${spaceId}/links/`,
          'Failed to share the space',
          jsonInit('POST', { workspace_id: workspaceId }),
        ),
      onSuccess,
    }),
    unlink: useMutation<void, APIError, { workspaceId: string }>({
      mutationFn: ({ workspaceId }) =>
        request(
          `spaces/${spaceId}/links/`,
          'Failed to stop sharing the space',
          jsonInit('DELETE', { workspace_id: workspaceId }),
        ),
      onSuccess,
    }),
  };
}

export function useSpace(spaceId: string, enabled = true) {
  return useQuery<Space, APIError>({
    queryKey: [KEY_LIST_SPACE, 'detail', spaceId],
    queryFn: () =>
      request<Space>(`spaces/${spaceId}/`, 'Failed to get the space'),
    enabled: enabled && !!spaceId,
  });
}

// -- Grants to groups

/**
 * The groups of the workspaces a document's space belongs to, for sharing
 * (groups that already have a role are left out). For mentions
 * (`forMention`), every group of every workspace one belongs to, the
 * document's own first.
 */
export function useGrantableTeams(
  docId: string,
  query: string,
  forMention = false,
) {
  return useQuery<GrantableTeam[], APIError>({
    queryKey: [KEY_LIST_GRANTABLE_TEAM, docId, query, forMention],
    queryFn: () =>
      request<GrantableTeam[]>(
        `groups/?document_id=${docId}&q=${encodeURIComponent(query)}${
          forMention ? '&include_granted=true&every_workspace=true' : ''
        }`,
        'Failed to get the groups',
      ),
    enabled: !!docId || forMention,
  });
}

export function useWorkspaceGrants(spaceId: string, enabled = true) {
  return useQuery<WorkspaceGrant[], APIError>({
    queryKey: [KEY_LIST_WORKSPACE_GRANT, spaceId],
    queryFn: () =>
      request<WorkspaceGrant[]>(
        `spaces/${spaceId}/workspace-grants/`,
        'Failed to get the grants',
      ),
    enabled: enabled && !!spaceId,
  });
}

export function useWorkspaceGrantMutations(spaceId: string) {
  const queryClient = useQueryClient();
  const onSuccess = () => {
    void queryClient.invalidateQueries({
      queryKey: [KEY_LIST_WORKSPACE_GRANT, spaceId],
    });
  };
  const url = `spaces/${spaceId}/workspace-grants/`;
  return {
    grant: useMutation<
      WorkspaceGrant,
      APIError,
      { team: string; role: string }
    >({
      mutationFn: (data) =>
        request(url, 'Failed to grant the role', jsonInit('POST', data)),
      onSuccess,
    }),
    revoke: useMutation<void, APIError, { team: string }>({
      mutationFn: (data) =>
        request(url, 'Failed to revoke the role', jsonInit('DELETE', data)),
      onSuccess,
    }),
  };
}

// -- Joining without an invitation

export interface JoinPreview {
  id: string;
  name: string;
  description: string;
  member_count: number;
  is_member: boolean;
  /** The admins approve who joins */
  join_approval: boolean;
  /** Where the request to join stands, once asked */
  request_status: 'pending' | 'declined' | null;
}

export const KEY_JOIN_PREVIEW = 'join-preview';

/** Where a join link leads; anyone holding the link may see it. */
export function useJoinPreview(token: string) {
  return useQuery<JoinPreview, APIError>({
    queryKey: [KEY_JOIN_PREVIEW, token],
    queryFn: () =>
      request<JoinPreview>(`join/${token}/`, 'This join link does not work'),
    enabled: !!token,
    retry: false,
  });
}

export function useJoinWorkspace(token: string) {
  const queryClient = useQueryClient();
  return useMutation<JoinPreview, APIError, void>({
    mutationFn: () =>
      request<JoinPreview>(
        `join/${token}/`,
        'Failed to join the workspace',
        jsonInit('POST'),
      ),
    onSuccess: (data) => {
      queryClient.setQueryData([KEY_JOIN_PREVIEW, token], data);
      void queryClient.invalidateQueries({ queryKey: [KEY_LIST_WORKSPACE] });
    },
  });
}

/** Turn a workspace's join link on (or give it a new secret), or off. */
export function useJoinLinkMutations(workspaceId: string) {
  const queryClient = useQueryClient();
  const onSuccess = () =>
    void queryClient.invalidateQueries({ queryKey: [KEY_LIST_WORKSPACE] });
  const renew = useMutation<{ join_token: string }, APIError, void>({
    mutationFn: () =>
      request(
        `workspaces/${workspaceId}/join-link/`,
        'Failed to create the join link',
        jsonInit('POST'),
      ),
    onSuccess,
  });
  const remove = useMutation<{ join_token: null }, APIError, void>({
    mutationFn: () =>
      request(
        `workspaces/${workspaceId}/join-link/`,
        'Failed to turn the join link off',
        jsonInit('DELETE'),
      ),
    onSuccess,
  });
  return { renew, remove };
}

// -- Requests to join, when admins approve who joins

export interface JoinRequest {
  id: string;
  user: User;
  via: 'link' | 'domain' | 'organization' | 'directory';
  created_at: string;
}

export const KEY_LIST_JOIN_REQUEST = 'workspace-join-requests';

export function useJoinRequests(workspaceId: string, enabled: boolean) {
  return useQuery<JoinRequest[], APIError>({
    queryKey: [KEY_LIST_JOIN_REQUEST, workspaceId],
    queryFn: () =>
      request<JoinRequest[]>(
        `workspaces/${workspaceId}/join-requests/`,
        'Failed to get the requests to join',
      ),
    enabled,
  });
}

/** Let someone in, or decline. */
export function useAnswerJoinRequest(workspaceId: string) {
  const queryClient = useQueryClient();
  return useMutation<
    void,
    APIError,
    { id: string; decision: 'approve' | 'decline' }
  >({
    mutationFn: ({ id, decision }) =>
      request<void>(
        `workspaces/${workspaceId}/join-requests/${id}/${decision}/`,
        'Failed to answer the request to join',
        jsonInit('POST'),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: [KEY_LIST_JOIN_REQUEST, workspaceId],
      });
      void queryClient.invalidateQueries({ queryKey: [KEY_LIST_WORKSPACE] });
      void queryClient.invalidateQueries({
        queryKey: [KEY_LIST_WORKSPACE_ACCESS],
      });
    },
  });
}

// -- Pages moving freely between spaces

export interface PageSpaceLinks {
  /** The space the page belongs to; none for an independent page */
  home: { id: string; title: string } | null;
  /** The other spaces it is shown in */
  links: {
    id: string;
    space: { id: string; title: string };
    can_unlink: boolean;
  }[];
  can_link: boolean;
  can_make_independent: boolean;
}

export interface LinkedPage {
  link_id: string;
  page: { id: string; title: string };
  /** Where it lives; none for an independent page */
  home: { id: string; title: string } | null;
}

export const KEY_PAGE_SPACE_LINKS = 'page-space-links';
export const KEY_LINKED_PAGES = 'space-linked-pages';

export function usePageSpaceLinks(pageId: string, enabled = true) {
  return useQuery<PageSpaceLinks, APIError>({
    queryKey: [KEY_PAGE_SPACE_LINKS, pageId],
    queryFn: () =>
      request<PageSpaceLinks>(
        `documents/${pageId}/space-links/`,
        'Failed to get where the page is shown',
      ),
    enabled,
  });
}

/** The pages of elsewhere shown in a space. */
export function useLinkedPages(spaceId: string, enabled = true) {
  return useQuery<LinkedPage[], APIError>({
    queryKey: [KEY_LINKED_PAGES, spaceId],
    queryFn: () =>
      request<LinkedPage[]>(
        `spaces/${spaceId}/linked-pages/`,
        'Failed to get the linked pages',
      ),
    enabled,
  });
}

/** Link a page into a space, unlink it, move it into a space or out of one. */
export function usePageMoves(pageId: string) {
  const queryClient = useQueryClient();
  const onSuccess = () => {
    for (const key of [
      KEY_PAGE_SPACE_LINKS,
      KEY_LINKED_PAGES,
      KEY_DOC,
      KEY_LIST_DOC,
      KEY_LIST_SPACE,
    ]) {
      void queryClient.invalidateQueries({ queryKey: [key] });
    }
  };
  return {
    link: useMutation<unknown, APIError, { spaceId: string }>({
      mutationFn: ({ spaceId }) =>
        request(
          `documents/${pageId}/space-links/`,
          'Failed to show the page in the space',
          jsonInit('POST', { space_id: spaceId }),
        ),
      onSuccess,
    }),
    unlink: useMutation<void, APIError, { linkId: string }>({
      mutationFn: ({ linkId }) =>
        request(
          `documents/${pageId}/space-links/${linkId}/`,
          'Failed to remove the page from the space',
          jsonInit('DELETE'),
        ),
      onSuccess,
    }),
    moveIntoSpace: useMutation<unknown, APIError, { spaceId: string }>({
      mutationFn: ({ spaceId }) =>
        request(
          `documents/${pageId}/move/`,
          'Failed to move the page',
          jsonInit('POST', {
            target_document_id: spaceId,
            position: 'last-child',
          }),
        ),
      onSuccess,
    }),
    // Directly in a workspace, in none of its spaces
    moveToWorkspace: useMutation<unknown, APIError, { workspaceId: string }>({
      mutationFn: ({ workspaceId }) =>
        request(
          `documents/${pageId}/move-to-workspace/`,
          'Failed to move the page',
          jsonInit('POST', { workspace_id: workspaceId }),
        ),
      onSuccess,
    }),
    makeIndependent: useMutation<unknown, APIError, void>({
      mutationFn: () =>
        request(
          `documents/${pageId}/make-independent/`,
          'Failed to make the page independent',
          jsonInit('POST'),
        ),
      onSuccess,
    }),
  };
}

/** Take a space out of its workspaces. */
export function useMakeSpaceIndependent(spaceId: string) {
  const queryClient = useQueryClient();
  return useMutation<Space, APIError, void>({
    mutationFn: () =>
      request<Space>(
        `spaces/${spaceId}/make-independent/`,
        'Failed to make the space independent',
        jsonInit('POST'),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [KEY_LIST_SPACE] });
      void queryClient.invalidateQueries({ queryKey: [KEY_DOC] });
    },
  });
}

// -- Finding workspaces

export interface DirectoryWorkspace {
  id: string;
  name: string;
  slug: string;
  description: string;
  visibility: WorkspaceVisibility;
  member_count: number;
  is_member: boolean;
  request_status: 'pending' | 'declined' | null;
  public_spaces: { id: string; title: string }[];
}

export const KEY_WORKSPACE_DIRECTORY = 'workspace-directory';

/** The workspaces one can find: public ones, and more when signed in. */
export function useWorkspaceDirectory(query: string) {
  return useQuery<DirectoryWorkspace[], APIError>({
    queryKey: [KEY_WORKSPACE_DIRECTORY, query],
    queryFn: () =>
      request<DirectoryWorkspace[]>(
        `workspaces/discover/?q=${encodeURIComponent(query)}`,
        'Failed to get the workspaces',
      ),
  });
}

/** Ask the administrators of a workspace found in the directory to join. */
export function useAskToJoin() {
  const queryClient = useQueryClient();
  return useMutation<DirectoryWorkspace, APIError, { workspaceId: string }>({
    mutationFn: ({ workspaceId }) =>
      request<DirectoryWorkspace>(
        `workspaces/${workspaceId}/ask-to-join/`,
        'Failed to ask to join',
        jsonInit('POST'),
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: [KEY_WORKSPACE_DIRECTORY] }),
  });
}
