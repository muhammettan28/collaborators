import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { APIError, baseApiUrl, errorCauses, fetchAPI } from '@/api';

/** What an invitation by email is to, as its page shows it. */
export interface InvitationInfo {
  /** Collaborators: already used, by the one signed in: it opens it */
  is_accepted?: boolean;
  kind: 'workspace' | 'space' | 'page';
  name: string;
  description: string;
  issuer: string;
  email: string;
  has_logo: boolean;
  is_expired: boolean;
}

/** One of the invitations sent together, as their page lists it. */
export interface BundledInvitation {
  /** Its own token while it waits: for its logo, to accept it alone */
  token?: string;
  /** Accepted: what it opens */
  id?: string;
  is_accepted: boolean;
  kind: InvitationInfo['kind'];
  name: string;
  description: string;
  role: string;
  has_logo: boolean;
  is_expired: boolean;
}

/** Invitations someone sent the same person within a few minutes. */
export interface InvitationBundleInfo {
  is_bundle: true;
  issuer: string;
  email: string;
  invitations: BundledInvitation[];
}

export const isInvitationBundle = (
  info: InvitationInfo | InvitationBundleInfo,
): info is InvitationBundleInfo => 'is_bundle' in info;

export interface WorkspaceInvitation {
  id: string;
  email: string;
  role: string;
  created_at: string;
  is_expired: boolean;
}

const request = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetchAPI(path, init);
  if (!response.ok) {
    throw new APIError('Request failed', await errorCauses(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
};

/** The page accepting an invitation, from its email. */
export const INVITE_PATH = '/invite/';

export const useInvitationInfo = (token: string) =>
  useQuery<InvitationInfo | InvitationBundleInfo, APIError>({
    queryKey: ['invitation', token],
    queryFn: () =>
      request<InvitationInfo | InvitationBundleInfo>(`invitations/${token}/`),
    enabled: !!token,
    retry: false,
  });

export const invitationLogoUrl = (token: string) =>
  `${baseApiUrl()}invitations/${token}/logo/`;

/** With the token of invitations sent together, accepts all of them. */
export const useAcceptInvitation = () =>
  useMutation<{ kind: string; id: string }, APIError, string>({
    mutationFn: (token) =>
      request(`invitations/${token}/accept/`, { method: 'POST' }),
  });

// -- Workspaces

const KEY_WORKSPACE_INVITATIONS = 'workspace-invitations';

export const useWorkspaceInvitations = (workspaceId: string, enabled = true) =>
  useQuery<WorkspaceInvitation[], APIError>({
    queryKey: [KEY_WORKSPACE_INVITATIONS, workspaceId],
    queryFn: () =>
      request<WorkspaceInvitation[]>(`workspaces/${workspaceId}/invitations/`),
    enabled: enabled && !!workspaceId,
  });

export const inviteToWorkspace = (
  workspaceId: string,
  email: string,
  role = 'member',
) =>
  request<WorkspaceInvitation>(`workspaces/${workspaceId}/invitations/`, {
    method: 'POST',
    body: JSON.stringify({ email, role }),
  });

export const useWorkspaceInvitationMutations = (workspaceId: string) => {
  const queryClient = useQueryClient();
  const refresh = () =>
    void queryClient.invalidateQueries({
      queryKey: [KEY_WORKSPACE_INVITATIONS, workspaceId],
    });
  const invite = useMutation<
    WorkspaceInvitation,
    APIError,
    { email: string; role?: string }
  >({
    mutationFn: ({ email, role }) =>
      inviteToWorkspace(workspaceId, email, role),
    onSuccess: refresh,
  });
  const cancel = useMutation<void, APIError, string>({
    mutationFn: (id) =>
      request(`workspaces/${workspaceId}/invitations/${id}/`, {
        method: 'DELETE',
      }),
    onSuccess: refresh,
  });
  return { invite, cancel };
};

// -- Logos of workspaces, spaces and pages

export type LogoOwner = 'workspaces' | 'documents';

export const logoUrl = (owner: LogoOwner, id: string, version = 0) =>
  `${baseApiUrl()}${owner}/${id}/logo/${version ? `?v=${version}` : ''}`;

const KEY_LOGO = 'logo';

/** Whether the item has a logo (and a version to reload its image). */
export const useLogo = (owner: LogoOwner, id: string) =>
  useQuery<{ exists: boolean; version: number }>({
    queryKey: [KEY_LOGO, owner, id],
    queryFn: async () => {
      const response = await fetchAPI(`${owner}/${id}/logo/`);
      return { exists: response.ok, version: Date.now() };
    },
    enabled: !!id,
  });

export const useLogoMutations = (owner: LogoOwner, id: string) => {
  const queryClient = useQueryClient();
  const refresh = () =>
    void queryClient.invalidateQueries({ queryKey: [KEY_LOGO, owner, id] });
  const set = useMutation<unknown, APIError, string>({
    mutationFn: (data) =>
      request(`${owner}/${id}/logo/`, {
        method: 'PUT',
        body: JSON.stringify({ data }),
      }),
    onSuccess: refresh,
  });
  const remove = useMutation<unknown, APIError, void>({
    mutationFn: () => request(`${owner}/${id}/logo/`, { method: 'DELETE' }),
    onSuccess: refresh,
  });
  return { set, remove };
};

/**
 * An image file made small (at most 256px wide or high) as a data URL, so
 * that a logo stays light: PNG keeps transparency.
 */
export const shrinkImage = (file: File, max = 256): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('unreadable'));
    reader.onload = () => {
      const image = new Image();
      image.onerror = () => reject(new Error('not an image'));
      image.onload = () => {
        const scale = Math.min(1, max / Math.max(image.width, image.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(image.width * scale));
        canvas.height = Math.max(1, Math.round(image.height * scale));
        canvas
          .getContext('2d')
          ?.drawImage(image, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL('image/png'));
      };
      image.src = reader.result as string;
    };
    reader.readAsDataURL(file);
  });
