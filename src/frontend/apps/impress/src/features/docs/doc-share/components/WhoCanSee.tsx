import {
  Radio,
  RadioGroup,
  Select,
  VariantType,
  useToastProvider,
} from '@gouvfr-lasuite/ui-components';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import { APIError, errorCauses, fetchAPI } from '@/api';
import { Box, Icon, Text } from '@/components';
import { Doc, KEY_DOC, KEY_LIST_DOC } from '@/docs/doc-management';

/** See the backend's documents/<id>/visibility/ */
interface Visibility {
  /** "public" | "platform" | "workspace:<id>" | "space" | "invited" */
  value: string;
  link_role: 'reader' | 'commenter' | 'editor';
  options: string[];
  workspaces: Record<string, string>;
  /** The space a page is in */
  space: { id: string; title: string } | null;
  can_change: boolean;
}

const KEY_VISIBILITY = 'doc-visibility';

const request = async (docId: string, init?: RequestInit) => {
  const response = await fetchAPI(`documents/${docId}/visibility/`, init);
  if (!response.ok) {
    throw new APIError(
      'Failed to update who can see it',
      await errorCauses(response),
    );
  }
  return response.json() as Promise<Visibility>;
};

const ICONS: Record<string, string> = {
  public: 'public',
  platform: 'groups',
  space: 'folder',
  invited: 'lock',
};

/**
 * The share dialog's one "Who can see this?" choice for a page or a space:
 * public, everyone on Collaborators, a workspace's members, the space's
 * people, or only the people invited.
 */
export const WhoCanSee = ({ doc }: { doc: Doc }) => {
  const { t } = useTranslation();
  const { toast } = useToastProvider();
  const queryClient = useQueryClient();
  const { data } = useQuery<Visibility, APIError>({
    queryKey: [KEY_VISIBILITY, doc.id],
    queryFn: () => request(doc.id),
  });
  const update = useMutation<
    Visibility,
    APIError,
    { value: string; link_role?: string }
  >({
    mutationFn: (body) =>
      request(doc.id, { method: 'PUT', body: JSON.stringify(body) }),
    onSuccess: (state) => {
      queryClient.setQueryData([KEY_VISIBILITY, doc.id], state);
      void queryClient.invalidateQueries({ queryKey: [KEY_DOC] });
      void queryClient.invalidateQueries({ queryKey: [KEY_LIST_DOC] });
      void queryClient.invalidateQueries({ queryKey: ['publication'] });
    },
    onError: (error) =>
      toast(
        error.cause?.[0] ??
          t('Something went wrong.', { description: 'Generic error message' }),
        VariantType.ERROR,
      ),
  });

  if (!data) {
    return null;
  }

  const isSpace = doc.kind === 'space';
  const label = (option: string) => {
    if (option.startsWith('workspace:')) {
      return t('Members of {{name}}', {
        description: 'Visibility: the members of a workspace',
        name: data.workspaces[option],
      });
    }
    switch (option) {
      case 'public':
        return t('Public on the internet', {
          description: 'Visibility: anyone, even without an account',
        });
      case 'platform':
        return t('Everyone on Collaborators', {
          description: 'Visibility: every signed-in collaborator',
        });
      case 'space':
        return t('Same as {{space}}', {
          description: 'Visibility: the page follows its space',
          space: data.space?.title,
        });
      default:
        return t('Only invited people', {
          description: 'Visibility: the people and groups given a role',
        });
    }
  };
  const help = (option: string) => {
    if (option.startsWith('workspace:')) {
      return t('Its members can read it; invite people to let them edit.', {
        description: 'Help of the workspace visibility',
      });
    }
    switch (option) {
      case 'public':
        return t('Anyone with the link, signed in or not.', {
          description: 'Help of the public visibility',
        });
      case 'platform':
        return t('Anyone signed in to Collaborators, with the link.', {
          description: 'Help of the platform visibility',
        });
      case 'space':
        return t(
          'The people of the space see it, as its sharing says. To hide it from them, make it independent.',
          { description: 'Help of the space visibility' },
        );
      default:
        return isSpace
          ? t(
              'Only the people and user groups given a role, and the administrators of its workspace.',
              { description: 'Help of the invited visibility of a space' },
            )
          : t('Only the people and user groups given a role, above.', {
              description: 'Help of the invited visibility',
            });
    }
  };
  const isOpenLink = data.value === 'public' || data.value === 'platform';

  return (
    <Box
      $padding={{ horizontal: 'base' }}
      $gap="xs"
      className="--collaborators--who-can-see"
      data-testid="who-can-see"
    >
      <Text as="h2" $weight="700" $size="sm" $margin="none">
        {t('Who can see this?', {
          description: 'Heading of the visibility choice in the share dialog',
        })}
      </Text>
      <RadioGroup>
        {data.options.map((option) => (
          <Box key={option} $gap="4xs">
            <Radio
              name={`visibility-${doc.id}`}
              value={option}
              checked={data.value === option}
              disabled={!data.can_change || update.isPending}
              onChange={() =>
                update.mutate({ value: option, link_role: data.link_role })
              }
              label={label(option)}
            />
            <Box
              $direction="row"
              $align="center"
              $gap="4xs"
              $margin={{ left: '1.6rem' }}
            >
              <Icon
                iconName={
                  option.startsWith('workspace:')
                    ? 'domain'
                    : (ICONS[option] ?? 'lock')
                }
                $size="14px"
                $variation="secondary"
              />
              <Text $size="xs" $variation="secondary">
                {help(option)}
              </Text>
            </Box>
          </Box>
        ))}
      </RadioGroup>
      {isOpenLink && (
        <Select
          fullWidth
          label={t('With the link, people can', {
            description: 'Label of what an open link lets people do',
          })}
          clearable={false}
          disabled={!data.can_change || update.isPending}
          options={[
            {
              value: 'reader',
              label: t('Read', { description: 'Link role: read' }),
            },
            {
              value: 'commenter',
              label: t('Comment', { description: 'Link role: comment' }),
            },
            {
              value: 'editor',
              label: t('Edit', { description: 'Link role: edit' }),
            },
          ]}
          value={data.link_role}
          onChange={(event) =>
            update.mutate({
              value: data.value,
              link_role: event.target.value as string,
            })
          }
        />
      )}
      {!data.can_change && (
        <Text $size="xs" $variation="secondary">
          {t('Only its owners and administrators change who can see it.', {
            description: 'Shown when one cannot change the visibility',
          })}
        </Text>
      )}
    </Box>
  );
};
