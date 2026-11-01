import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  APIError,
  APIList,
  errorCauses,
  fetchAPI,
  useAPIInfiniteQuery,
} from '@/api';
import { PlatformRole, User } from '@/features/auth/api';

/** Someone on the platform, as its managers see them. */
export interface PlatformPerson {
  id: string;
  full_name: string;
  email: string;
  /** Their identity provider vouches for the email */
  email_verified: boolean;
  platform_role: PlatformRole;
  registration_status: NonNullable<User['registration_status']>;
  created_at: string;
  last_login: string | null;
  /** The workspaces they are a member of */
  workspaces: number;
  /** The pages they own */
  pages: number;
  /** Suspended until reinstated */
  suspended: boolean;
  /** The viewer may suspend or remove them (below the viewer's level) */
  can_manage: boolean;
  /** The levels the viewer may put them at */
  levels_you_may_give: PlatformRole[];
}

export interface PlatformPeopleParams {
  q: string;
  role: PlatformRole | '';
  status: PlatformPerson['registration_status'] | '';
  account?: 'active' | 'suspended' | '';
}

export const KEY_PLATFORM_PEOPLE = 'platform-people';

const getPlatformPeople = async ({
  page,
  ...params
}: PlatformPeopleParams & { page: number }) => {
  const query = new URLSearchParams({ page: String(page) });
  Object.entries(params).forEach(([key, value]) => {
    if (value) {
      query.set(key, value);
    }
  });
  const response = await fetchAPI(`platform/people/?${query.toString()}`);
  if (!response.ok) {
    throw new APIError(
      'Failed to list the people of the platform',
      await errorCauses(response),
    );
  }
  return response.json() as Promise<APIList<PlatformPerson>>;
};

/** Everyone on the platform, newest first, fifty a page. */
export const usePlatformPeople = (params: PlatformPeopleParams) =>
  useAPIInfiniteQuery(KEY_PLATFORM_PEOPLE, getPlatformPeople, params);

/** What became of the account at the sign-in server. */
export type SignInServerOutcome = 'done' | 'failed' | 'not configured' | 'none';

const post = async (path: string, body?: object) => {
  const response = await fetchAPI(path, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    throw new APIError(
      'The account was not changed',
      await errorCauses(response),
    );
  }
  return response.json() as Promise<{ sign_in_server: SignInServerOutcome }>;
};

const useRefreshPeople = () => {
  const queryClient = useQueryClient();
  return () =>
    void queryClient.invalidateQueries({ queryKey: [KEY_PLATFORM_PEOPLE] });
};

/** Suspend someone below one's level; they are told by email. */
export const useSuspendPerson = () => {
  const refresh = useRefreshPeople();
  return useMutation<
    { sign_in_server: SignInServerOutcome },
    APIError,
    { id: string; reason: string }
  >({
    mutationFn: ({ id, reason }) =>
      post(`platform/people/${id}/suspend/`, { reason }),
    onSuccess: refresh,
  });
};

/** Let a suspended person in again; they are told by email. */
export const useReinstatePerson = () => {
  const refresh = useRefreshPeople();
  return useMutation<
    { sign_in_server: SignInServerOutcome },
    APIError,
    { id: string }
  >({
    mutationFn: ({ id }) => post(`platform/people/${id}/reinstate/`),
    onSuccess: refresh,
  });
};

/** Put someone at a level one may give; they are told by email. */
export const useAppointPerson = () => {
  const refresh = useRefreshPeople();
  return useMutation<
    { platform_role: PlatformRole },
    APIError,
    { id: string; role: PlatformRole }
  >({
    mutationFn: async ({ id, role }) => {
      const response = await fetchAPI(`platform/people/${id}/level/`, {
        method: 'POST',
        body: JSON.stringify({ role }),
      });
      if (!response.ok) {
        throw new APIError(
          'The level was not changed',
          await errorCauses(response),
        );
      }
      return response.json() as Promise<{ platform_role: PlatformRole }>;
    },
    onSuccess: refresh,
  });
};

/** What removing someone would leave without an owner. */
export interface RemovalPreview {
  pages: { id: string; title: string }[];
  pages_count: number;
  /** The pages with everything below them */
  pages_with_subpages: number;
  workspaces: { id: string; name: string }[];
}

export const useRemovalPreview = (id: string) =>
  useQuery<RemovalPreview, APIError>({
    queryKey: [KEY_PLATFORM_PEOPLE, 'removal', id],
    queryFn: async () => {
      const response = await fetchAPI(`platform/people/${id}/removal/`);
      if (!response.ok) {
        throw new APIError(
          'Failed to see what removing leaves',
          await errorCauses(response),
        );
      }
      return response.json() as Promise<RemovalPreview>;
    },
  });

export interface RemovalChoice {
  id: string;
  pages: 'hand_over' | 'delete';
  recipient?: string;
  reason: string;
  block: boolean;
}

/** Remove someone's account, their pages handed over or deleted. */
export const useRemovePerson = () => {
  const refresh = useRefreshPeople();
  const queryClient = useQueryClient();
  return useMutation<
    { sign_in_server: SignInServerOutcome },
    APIError,
    RemovalChoice
  >({
    mutationFn: ({ id, ...choice }) =>
      post(`platform/people/${id}/remove/`, choice),
    onSuccess: () => {
      refresh();
      void queryClient.invalidateQueries({ queryKey: [KEY_BLOCKED_EMAILS] });
    },
  });
};

/** An email nobody signs in with (owners only). */
export interface BlockedEmail {
  id: string;
  email: string;
  reason: string;
  blocked_by: string;
  created_at: string;
  /** Someone with an account here */
  has_account: boolean;
}

export const KEY_BLOCKED_EMAILS = 'blocked-emails';

export const useBlockedEmails = () =>
  useQuery<BlockedEmail[], APIError>({
    queryKey: [KEY_BLOCKED_EMAILS],
    queryFn: async () => {
      const response = await fetchAPI('platform/blocked/');
      if (!response.ok) {
        throw new APIError(
          'Failed to list the blocked emails',
          await errorCauses(response),
        );
      }
      return response.json() as Promise<BlockedEmail[]>;
    },
  });

export const useBlockEmail = () => {
  const queryClient = useQueryClient();
  return useMutation<BlockedEmail, APIError, { email: string; reason: string }>(
    {
      mutationFn: async (body) => {
        const response = await fetchAPI('platform/blocked/', {
          method: 'POST',
          body: JSON.stringify(body),
        });
        if (!response.ok) {
          throw new APIError(
            'The email was not blocked',
            await errorCauses(response),
          );
        }
        return response.json() as Promise<BlockedEmail>;
      },
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: [KEY_BLOCKED_EMAILS] });
        void queryClient.invalidateQueries({ queryKey: [KEY_PLATFORM_PEOPLE] });
      },
    },
  );
};

export const useUnblockEmail = () => {
  const queryClient = useQueryClient();
  return useMutation<void, APIError, { id: string }>({
    mutationFn: async ({ id }) => {
      const response = await fetchAPI(`platform/blocked/${id}/`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        throw new APIError(
          'The email was not unblocked',
          await errorCauses(response),
        );
      }
    },
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: [KEY_BLOCKED_EMAILS] }),
  });
};

/** Why someone reports a page. */
export type ReportReason =
  'spam' | 'abuse' | 'illegal' | 'personal_data' | 'copyright' | 'other';

/** Report a page one reads to the platform administrators. */
export const useReportPage = () =>
  useMutation<
    void,
    APIError,
    { docId: string; reason: ReportReason; details: string }
  >({
    mutationFn: async ({ docId, ...body }) => {
      const response = await fetchAPI(`documents/${docId}/report/`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        throw new APIError(
          'The page was not reported',
          await errorCauses(response),
        );
      }
    },
  });

/** A reported page, as platform administrators see it. */
export interface ContentReport {
  id: string;
  /** The page as it is now; null once deleted for good */
  document: {
    id: string;
    title: string;
    deleted: boolean;
    taken_down: boolean;
    owners: string[];
  } | null;
  /** The page's title when it was reported */
  document_title: string;
  /** The page's text when it was reported */
  excerpt: string;
  reporter: string;
  reason: ReportReason;
  details: string;
  status: 'open' | 'dismissed' | 'taken_down';
  resolved_by: string;
  resolved_at: string | null;
  resolution_note: string;
  created_at: string;
}

export const KEY_REPORTS = 'platform-reports';

export const useReports = (status: 'open' | 'decided') =>
  useQuery<ContentReport[], APIError>({
    queryKey: [KEY_REPORTS, status],
    queryFn: async () => {
      const response = await fetchAPI(`platform/reports/?status=${status}`);
      if (!response.ok) {
        throw new APIError(
          'Failed to list the reports',
          await errorCauses(response),
        );
      }
      return response.json() as Promise<ContentReport[]>;
    },
  });

/** Dismiss a report, take its page down, or put the page back. */
export const useDecideReport = () => {
  const queryClient = useQueryClient();
  return useMutation<
    ContentReport,
    APIError,
    {
      id: string;
      decision: 'dismiss' | 'take-down' | 'put-back';
      note?: string;
    }
  >({
    mutationFn: async ({ id, decision, note }) => {
      const response = await fetchAPI(`platform/reports/${id}/${decision}/`, {
        method: 'POST',
        body: JSON.stringify({ note: note ?? '' }),
      });
      if (!response.ok) {
        throw new APIError(
          'The report was not decided',
          await errorCauses(response),
        );
      }
      return response.json() as Promise<ContentReport>;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [KEY_REPORTS] });
      void queryClient.invalidateQueries({ queryKey: ['notifications'] });
      void queryClient.invalidateQueries({
        queryKey: ['notifications-unread-count'],
      });
    },
  });
};

/** A setting platform owners change, beside the server's own. */
export interface PlatformSetting<T = boolean> {
  value: T;
  server_default: T;
  /** Changed here; else it follows the server */
  set_here: boolean;
}

export type PlatformSettingName = 'signup_approval' | 'email_invitations';

/** The settings that are numbers: presentations each person stores, versions kept */
export type PlatformNumberSettingName =
  'presentation_storage_mb' | 'presentation_versions';

export type PlatformSettings = Record<PlatformSettingName, PlatformSetting> &
  Record<PlatformNumberSettingName, PlatformSetting<number>>;

export const KEY_PLATFORM_SETTINGS = 'platform-settings';

export const usePlatformSettings = () =>
  useQuery<PlatformSettings, APIError>({
    queryKey: [KEY_PLATFORM_SETTINGS],
    queryFn: async () => {
      const response = await fetchAPI('platform/settings/');
      if (!response.ok) {
        throw new APIError(
          'Failed to read the platform settings',
          await errorCauses(response),
        );
      }
      return response.json() as Promise<PlatformSettings>;
    },
  });

/** Change settings; null follows the server again. */
export const useUpdatePlatformSettings = () => {
  const queryClient = useQueryClient();
  return useMutation<
    PlatformSettings,
    APIError,
    Partial<
      Record<PlatformSettingName, boolean | null> &
        Record<PlatformNumberSettingName, number | null>
    >
  >({
    mutationFn: async (body) => {
      const response = await fetchAPI('platform/settings/', {
        method: 'PATCH',
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        throw new APIError(
          'The settings were not changed',
          await errorCauses(response),
        );
      }
      return response.json() as Promise<PlatformSettings>;
    },
    onSuccess: (data) =>
      queryClient.setQueryData([KEY_PLATFORM_SETTINGS], data),
  });
};
