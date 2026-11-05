import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { Box, Icon, StyledLink, Text } from '@/components';
import { Title } from '@/components/Title';

export const GUIDE_PATH = '/guide/';

/** One level of the hierarchy: an icon and its name. */
const Level = ({ icon, name }: { icon: string; name: string }) => (
  <Box
    $direction="row"
    $align="center"
    $gap="4xs"
    $padding={{ horizontal: 'xs', vertical: '4xs' }}
    $css={css`
      border-radius: 999px;
      border: 1px solid var(--c--contextuals--border--surface--primary);
      background: var(--c--contextuals--background--surface--primary);
    `}
  >
    <Icon iconName={icon} $size="18px" $theme="brand" />
    <Text $size="sm" $weight="600">
      {name}
    </Text>
  </Box>
);

/**
 * At the top of the dashboard, centred in a framed box: how workspaces,
 * spaces and pages fit together, the first step to take, and a link to the
 * guide. It is the first thing a new collaborator needs, so it comes before
 * the cards. Not a card: nothing to move, hide or close.
 */
export const HierarchyNote = () => {
  const { t } = useTranslation();
  const arrow = (
    <Icon
      iconName="arrow_forward"
      $size="16px"
      $variation="tertiary"
      className="--collaborators--hierarchy-arrow"
    />
  );
  return (
    <Box
      as="aside"
      role="note"
      $align="center"
      $gap="sm"
      $width="100%"
      $maxWidth="680px"
      $margin={{ horizontal: 'auto' }}
      // Collaborators: a little more air, the three parts read apart
      $padding={{ horizontal: 'md', top: 'md', bottom: 'xs' }}
      data-testid="hierarchy-note"
      // Framed like the dashboard's notes, without being a card: nothing
      // to move, hide or close
      $css={css`
        border: 1px solid var(--c--contextuals--border--surface--primary);
        border-radius: var(--c--globals--spacings--xs);
        background: var(
          --c--contextuals--background--semantic--contextual--primary
        );
        text-align: center;
      `}
    >
      <Text
        as="h2"
        $size="sm"
        $weight="600"
        $variation="secondary"
        $margin="none"
        $direction="row"
        $align="center"
        $gap="0.35em"
        $css="flex-wrap: wrap; justify-content: center;"
      >
        {t('The hierarchical structure in', {
          description: 'Title of the hierarchy note, before the logo',
        })}
        <Title as="span" $size="0.95rem" />
      </Text>
      <Box
        $direction="row"
        $align="center"
        $justify="center"
        $gap="2xs"
        // Collaborators: on a narrow phone, one level under the other
        $css={css`
          flex-wrap: wrap;
          @media (max-width: 499px) {
            flex-direction: column;
            gap: var(--c--globals--spacings--4xs);
            .--collaborators--hierarchy-arrow {
              transform: rotate(90deg);
            }
          }
        `}
      >
        <Level
          icon="workspaces"
          name={t('Workspace', { description: 'Level of the hierarchy' })}
        />
        {arrow}
        <Level
          icon="folder"
          name={t('Space', { description: 'Level of the hierarchy' })}
        />
        {arrow}
        <Level
          icon="description"
          name={t('Page', { description: 'Level of the hierarchy' })}
        />
      </Box>
      {/* One idea per row */}
      <Box $gap="2xs" $maxWidth="600px">
        <Text $size="sm" $variation="secondary">
          {t('A workspace holds spaces, and a space holds pages.', {
            description: 'Explanation of the hierarchy, first row',
          })}
        </Text>
        <Text $size="sm" $variation="secondary">
          {t(
            'A page can also sit directly in a workspace and/or space, or stay on its own.',
            { description: 'Explanation of the hierarchy, second row' },
          )}
        </Text>
        <Text $size="sm" $variation="secondary">
          {t('Similarly, a space can sit in a workspace, or stay on its own.', {
            description: 'Explanation of the hierarchy, third row',
          })}
        </Text>
      </Box>
      <Text $size="sm" $weight="600" data-testid="hierarchy-note-first-step">
        {t(
          'To start, press “New” in the left panel to create your first page.',
          {
            description: 'First step shown in the hierarchy note',
          },
        )}
      </Text>
      {/* Collaborators: the link on a row of its own, tall enough to tap */}
      <StyledLink
        href={GUIDE_PATH}
        $css={css`
          align-items: center;
          gap: 0.2rem;
          min-height: 32px;
          padding: 0 var(--c--globals--spacings--xs);
        `}
      >
        <Text as="span" $size="sm" $weight="600" $theme="brand">
          {t('Learn more', { description: 'Link to the guide' })}
        </Text>
        <Icon iconName="arrow_forward" $size="16px" $theme="brand" />
      </StyledLink>
    </Box>
  );
};
