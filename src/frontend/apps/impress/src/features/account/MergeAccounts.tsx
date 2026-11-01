import {
  Button,
  VariantType,
  useToastProvider,
} from '@gouvfr-lasuite/ui-components';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { Box, Text } from '@/components';

import { useDecideMerge, useMergeProposal } from './api';

const proposalCss = css`
  padding: var(--c--globals--spacings--sm);
  border-radius: var(--c--globals--spacings--3xs);
  border: 1px solid var(--c--contextuals--border--semantic--brand--primary);
`;

/**
 * The merge offered when an account added ("Add another Google account")
 * already opens a separate Collaborators account of the same person:
 * what it brings, and merging it into this one, or not now.
 */
export const MergeProposal = () => {
  const { t } = useTranslation();
  const { toast } = useToastProvider();
  const { data } = useMergeProposal();
  const decide = useDecideMerge();
  const proposal = data?.proposal;

  if (!proposal) {
    return null;
  }

  return (
    <Box $gap="xs" $css={proposalCss} data-testid="merge-proposal" role="alert">
      <Text $weight="600">
        {t(
          '{{email}} already has its own Collaborators account. Merge it into this one?',
          {
            description: 'Question offering to merge an account added',
            email: proposal.email || proposal.full_name,
          },
        )}
      </Text>
      <Text $size="sm">
        {t(
          'Pages it owns: {{pages}} · shared with it: {{shared}} · workspaces: {{workspaces}} · user groups: {{groups}}.',
          {
            description: 'What the account merged brings',
            pages: proposal.pages,
            shared: proposal.shared_with_it,
            workspaces: proposal.workspaces,
            groups: proposal.groups,
          },
        )}
      </Text>
      <Text $size="sm" $variation="secondary">
        {t(
          'They all move here, and it goes; signing in with it will open this account. This can’t be undone.',
          { description: 'What merging does' },
        )}
      </Text>
      <Box $direction="row" $gap="xs">
        <Button
          size="small"
          color="error"
          disabled={decide.isPending}
          onClick={() =>
            decide.mutate('merge', {
              onSuccess: ({ merged }) =>
                toast(
                  t('{{name}} is merged into this account.', {
                    description: 'Toast after merging accounts',
                    name: merged,
                  }),
                  VariantType.SUCCESS,
                ),
            })
          }
        >
          {t('Merge into this account', {
            description: 'Button confirming a merge',
          })}
        </Button>
        <Button
          size="small"
          variant="secondary"
          disabled={decide.isPending}
          onClick={() => decide.mutate('cancel')}
        >
          {t('Not now', { description: 'Button declining a merge offered' })}
        </Button>
      </Box>
      {decide.error && (
        <Text $size="sm" $theme="error">
          {decide.error.cause?.[0]}
        </Text>
      )}
    </Box>
  );
};
