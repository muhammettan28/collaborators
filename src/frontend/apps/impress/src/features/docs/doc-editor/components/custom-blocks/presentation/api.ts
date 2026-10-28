import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { APIError, errorCauses, fetchAPI } from '@/api';

/** An HTML presentation shown in a page (the backend's core/presentations.py). */
export interface Presentation {
  id: string;
  title: string;
  /** Stored here, or a link to an HTML file hosted elsewhere */
  source: 'file' | 'link';
  link: string;
  page: { id: string; title: string };
  /** Of the version shown, when stored here */
  size: number | null;
  /** False until its first file arrives */
  has_content: boolean;
  updated_at: string;
  /** Where it is shown on its own, full screen */
  view_url: string;
  /** Its PDF, always of the current version */
  pdf_url: string;
  abilities: { edit: boolean; remove: boolean };
}

export interface PresentationVersion {
  id: string;
  size: number;
  created_at: string;
  uploaded_by: string;
  current: boolean;
}

export interface PresentationStorage {
  used: number;
  limit: number;
  presentations: {
    id: string;
    title: string;
    page: { id: string; title: string };
    size: number;
    can_remove: boolean;
  }[];
}

export const KEY_PRESENTATION = 'presentation';
export const KEY_PRESENTATION_CONTENT = 'presentation-content';
export const KEY_PRESENTATION_STORAGE = 'presentation-storage';

/** The message the backend gave, else a fallback. */
const failure = async (response: Response, message: string) => {
  const { status, cause } = await errorCauses(response);
  return new APIError(cause?.[0] ? String(cause[0]) : message, {
    status,
    cause,
  });
};

export const usePresentation = (id: string) =>
  useQuery<Presentation, APIError>({
    queryKey: [KEY_PRESENTATION, id],
    queryFn: async () => {
      const response = await fetchAPI(`presentations/${id}/`);
      if (!response.ok) {
        throw await failure(response, 'Failed to read the presentation');
      }
      return (await response.json()) as Presentation;
    },
    enabled: !!id,
    retry: (count, error) => error.status !== 404 && count < 2,
  });

/** The HTML shown now, as text (never run as a page of the app). */
export const usePresentationContent = (id: string, version: string) =>
  useQuery<string, APIError>({
    queryKey: [KEY_PRESENTATION_CONTENT, id, version],
    queryFn: async () => {
      const response = await fetchAPI(`presentations/${id}/content/`);
      if (!response.ok) {
        throw new APIError(await response.text(), { status: response.status });
      }
      return response.text();
    },
    enabled: !!id && !!version,
    staleTime: 60_000,
  });

const formOf = (fields: Record<string, string | File | undefined>) => {
  const form = new FormData();
  Object.entries(fields).forEach(([name, value]) => {
    if (value !== undefined) {
      form.append(name, value);
    }
  });
  return form;
};

/** Add one to a page: an HTML file, or a link to one. */
export const useCreatePresentation = () => {
  const queryClient = useQueryClient();
  return useMutation<
    Presentation,
    APIError,
    { document: string; file?: File; link?: string; title?: string }
  >({
    mutationFn: async ({ document, file, link, title }) => {
      const response = file
        ? await fetchAPI('presentations/', {
            method: 'POST',
            body: formOf({ document, file, title }),
            withoutContentType: true,
          })
        : await fetchAPI('presentations/', {
            method: 'POST',
            body: JSON.stringify({ document, link, title }),
          });
      if (!response.ok) {
        throw await failure(response, 'Failed to add the presentation');
      }
      return (await response.json()) as Presentation;
    },
    onSuccess: (presentation) => {
      queryClient.setQueryData(
        [KEY_PRESENTATION, presentation.id],
        presentation,
      );
      void queryClient.invalidateQueries({
        queryKey: [KEY_PRESENTATION_STORAGE],
      });
    },
  });
};

/** A new version (a file), a new link or a new title, at the same address. */
export const useChangePresentation = (id: string) => {
  const queryClient = useQueryClient();
  return useMutation<
    Presentation,
    APIError,
    { file?: File; link?: string; title?: string }
  >({
    mutationFn: async ({ file, link, title }) => {
      const response = file
        ? await fetchAPI(`presentations/${id}/file/`, {
            method: 'POST',
            body: formOf({ file }),
            withoutContentType: true,
          })
        : await fetchAPI(`presentations/${id}/`, {
            method: 'PATCH',
            body: JSON.stringify({ link, title }),
          });
      if (!response.ok) {
        throw await failure(response, 'Failed to change the presentation');
      }
      return (await response.json()) as Presentation;
    },
    onSuccess: (presentation) => {
      queryClient.setQueryData([KEY_PRESENTATION, id], presentation);
      void queryClient.invalidateQueries({
        queryKey: [KEY_PRESENTATION_CONTENT, id],
      });
      void queryClient.invalidateQueries({
        queryKey: [KEY_PRESENTATION_STORAGE],
      });
    },
  });
};

export const useRemovePresentation = () => {
  const queryClient = useQueryClient();
  return useMutation<void, APIError, string>({
    mutationFn: async (id) => {
      const response = await fetchAPI(`presentations/${id}/`, {
        method: 'DELETE',
      });
      if (!response.ok) {
        throw await failure(response, 'Failed to remove the presentation');
      }
    },
    onSuccess: (_data, id) => {
      void queryClient.invalidateQueries({ queryKey: [KEY_PRESENTATION, id] });
      void queryClient.invalidateQueries({
        queryKey: [KEY_PRESENTATION_STORAGE],
      });
    },
  });
};

export const usePresentationVersions = (id: string, enabled: boolean) =>
  useQuery<PresentationVersion[], APIError>({
    queryKey: [KEY_PRESENTATION, id, 'versions'],
    queryFn: async () => {
      const response = await fetchAPI(`presentations/${id}/versions/`);
      if (!response.ok) {
        throw await failure(response, 'Failed to read the versions');
      }
      return (await response.json()) as PresentationVersion[];
    },
    enabled,
  });

export const useRestorePresentation = (id: string) => {
  const queryClient = useQueryClient();
  return useMutation<Presentation, APIError, string>({
    mutationFn: async (versionId) => {
      const response = await fetchAPI(
        `presentations/${id}/versions/${versionId}/restore/`,
        { method: 'POST' },
      );
      if (!response.ok) {
        throw await failure(response, 'Failed to restore the version');
      }
      return (await response.json()) as Presentation;
    },
    onSuccess: (presentation) => {
      queryClient.setQueryData([KEY_PRESENTATION, id], presentation);
      void queryClient.invalidateQueries({ queryKey: [KEY_PRESENTATION, id] });
      void queryClient.invalidateQueries({
        queryKey: [KEY_PRESENTATION_CONTENT, id],
      });
    },
  });
};

export const usePresentationStorage = (enabled: boolean) =>
  useQuery<PresentationStorage, APIError>({
    queryKey: [KEY_PRESENTATION_STORAGE],
    queryFn: async () => {
      const response = await fetchAPI('presentations/storage/');
      if (!response.ok) {
        throw await failure(response, 'Failed to read your storage');
      }
      return (await response.json()) as PresentationStorage;
    },
    enabled,
  });

/** "2.4 MB" */
export const megabytes = (bytes: number) =>
  `${(bytes / (1024 * 1024)).toLocaleString(undefined, {
    maximumFractionDigits: 1,
  })} MB`;

/** The PDF's address with the reader's time zone, for the dated page. */
export const pdfWithZone = (pdfUrl: string) => {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return zone ? `${pdfUrl}?tz=${encodeURIComponent(zone)}` : pdfUrl;
  } catch {
    return pdfUrl;
  }
};
