import { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { Box, Icon, StyledLink, Text } from '@/components';

/**
 * The inner alignment of the dashboard's notes, for the cards: a column of
 * 22px icons, then the text at the same gap. A card's body is pulled back by
 * its rows' padding (xs); text without an icon starts under the title.
 */
export const CARD_ICON_SIZE = '22px';
export const CARD_ICON_GAP = 'var(--c--globals--spacings--sm)';
export const TEXT_INDENT = `calc(var(--c--globals--spacings--xs) + ${CARD_ICON_SIZE} + ${CARD_ICON_GAP})`;

const rowCss = css`
  display: flex;
  align-items: center;
  gap: ${CARD_ICON_GAP};
  padding: var(--c--globals--spacings--2xs) var(--c--globals--spacings--xs);
  border-radius: var(--c--globals--spacings--3xs);
  color: inherit;
  text-decoration: none;
  width: 100%;
  &:hover {
    background-color: var(
      --c--contextuals--background--semantic--contextual--primary
    );
  }
`;

/** A line of a card: an icon, a title and a detail under it. */
export const Row = ({
  href,
  icon,
  title,
  detail,
  onClick,
}: {
  href: string;
  icon: string;
  title: string;
  detail?: string;
  onClick?: () => void;
}) => (
  <StyledLink href={href} $css={rowCss} onClick={onClick}>
    <Icon iconName={icon} $size={CARD_ICON_SIZE} $variation="secondary" />
    <Box $flex={1} $css="min-width: 0;">
      {/* Collaborators: block, as a flex box cuts a long title without "…" */}
      <Text $size="sm" $weight="500" $display="block" $ellipsis>
        {title}
      </Text>
      {detail && (
        <Text $size="xs" $variation="secondary" $display="block" $ellipsis>
          {detail}
        </Text>
      )}
    </Box>
  </StyledLink>
);

/** What a card says when it has nothing to show, under its title. */
export const Empty = ({ children }: { children: ReactNode }) => (
  <Text
    $size="sm"
    $variation="secondary"
    $css={css`
      padding-inline: ${TEXT_INDENT} var(--c--globals--spacings--xs);
    `}
  >
    {children}
  </Text>
);

/** The link from a summary to its full screen. */
export const SeeAll = ({
  href,
  onClick,
}: {
  href: string;
  onClick?: () => void;
}) => {
  const { t } = useTranslation();
  return (
    <Box $direction="row" $justify="flex-end" $padding={{ horizontal: 'xs' }}>
      <StyledLink href={href} onClick={onClick}>
        <Text $size="sm" $theme="brand">
          {t('See all', { description: 'Link from a card to its full list' })}
        </Text>
      </StyledLink>
    </Box>
  );
};
