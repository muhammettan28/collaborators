import { useQuery } from '@tanstack/react-query';
import { ReactNode, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { APIError, errorCauses, fetchAPI } from '@/api';
import { Box, StyledLink, Text } from '@/components';
import { UserAvatar } from '@/features/auth';
import { profileHref } from '@/features/profile/api';

/** What one may see of a person, see the backend's people/<id>/. */
export interface PersonCard {
  id: string;
  full_name: string;
  short_name: string;
  is_me: boolean;
  /** Works with the viewer: then email, workspaces and groups are given */
  known: boolean;
  email: string;
  workspaces: { id: string; name: string }[];
  groups: { id: string; name: string }[];
}

export const KEY_PERSON_CARD = 'person-card';

export const usePersonCard = (userId: string, enabled: boolean) =>
  useQuery<PersonCard, APIError>({
    queryKey: [KEY_PERSON_CARD, userId],
    queryFn: async () => {
      const response = await fetchAPI(`people/${userId}/`);
      if (!response.ok) {
        throw new APIError(
          'Failed to get the person',
          await errorCauses(response),
        );
      }
      return response.json() as Promise<PersonCard>;
    },
    enabled: enabled && !!userId,
    staleTime: 5 * 60_000,
    retry: false,
  });

const OPEN_DELAY = 350;
const CLOSE_DELAY = 150;
const CARD_WIDTH = 280;

const CardContent = ({
  userId,
  fallbackName,
}: {
  userId: string;
  fallbackName: string;
}) => {
  const { t } = useTranslation();
  const { data: card, isLoading, isError } = usePersonCard(userId, true);
  const name = card?.full_name || fallbackName;

  return (
    <Box $gap="xs">
      <Box $direction="row" $align="center" $gap="xs">
        <UserAvatar fullName={name} />
        <Box $css="min-width: 0;">
          <Text $weight="600" $ellipsis>
            {name}
            {card?.is_me &&
              ` ${t('(you)', { description: 'After one’s own name' })}`}
          </Text>
          {card?.email && (
            <Text $size="xs" $variation="secondary" $ellipsis>
              {card.email}
            </Text>
          )}
        </Box>
      </Box>
      {isLoading && (
        <Text $size="xs" $variation="secondary">
          {t('Loading…', { description: 'Shown while something loads' })}
        </Text>
      )}
      {card?.known && card.workspaces.length > 0 && (
        <Text $size="xs" $variation="secondary">
          {t('Workspaces: {{names}}', {
            description: 'The workspaces shared with a person',
            names: card.workspaces.map((ws) => ws.name).join(', '),
          })}
        </Text>
      )}
      {card?.known && card.groups.length > 0 && (
        <Text $size="xs" $variation="secondary">
          {t('User groups: {{names}}', {
            description: 'The groups a person is in',
            names: card.groups.map((group) => group.name).join(', '),
          })}
        </Text>
      )}
      {card && (
        <StyledLink href={profileHref(card.id)}>
          <Text $size="xs" $theme="brand">
            {t('View profile', { description: 'Link to a person’s profile' })}
          </Text>
        </StyledLink>
      )}
      {card && !card.known && (
        <Text $size="xs" $variation="secondary">
          {t('You don’t share a workspace or page with this person yet.', {
            description: 'Person card of someone one does not work with',
          })}
        </Text>
      )}
      {isError && (
        <Text $size="xs" $variation="secondary">
          {t('This person can’t be shown.', {
            description: 'Person card that could not load',
          })}
        </Text>
      )}
    </Box>
  );
};

/**
 * Wraps a mention: hovering it opens a card (`content`) below it, which
 * stays open while the pointer is on it.
 */
export const HoverCardAnchor = ({
  label,
  testId,
  content,
  children,
  dataAttributes,
}: {
  /** The card's accessible name */
  label: string;
  testId: string;
  /** Rendered only once the card opens */
  content: () => ReactNode;
  children: ReactNode;
  dataAttributes?: Record<string, string>;
}) => {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const [position, setPosition] = useState<{ top: number; left: number }>();

  useEffect(() => () => clearTimeout(timer.current), []);

  const open = () => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      const rect = anchorRef.current?.getBoundingClientRect();
      if (!rect) {
        return;
      }
      setPosition({
        top: rect.bottom + 6,
        left: Math.max(
          8,
          Math.min(rect.left, window.innerWidth - CARD_WIDTH - 8),
        ),
      });
    }, OPEN_DELAY);
  };
  const close = () => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setPosition(undefined), CLOSE_DELAY);
  };

  return (
    <span
      ref={anchorRef}
      onMouseEnter={open}
      onMouseLeave={close}
      {...dataAttributes}
    >
      {children}
      {position &&
        createPortal(
          <Box
            role="dialog"
            aria-label={label}
            data-testid={testId}
            onMouseEnter={() => clearTimeout(timer.current)}
            onMouseLeave={close}
            $padding="sm"
            $css={css`
              position: fixed;
              top: ${position.top}px;
              left: ${position.left}px;
              width: ${CARD_WIDTH}px;
              z-index: 2000;
              border-radius: var(--c--globals--spacings--xs);
              border: 1px solid var(--c--contextuals--border--surface--primary);
              background: var(--c--contextuals--background--surface--primary);
              box-shadow: 0 6px 24px rgba(0, 0, 0, 0.12);
              user-select: text;
            `}
          >
            {content()}
          </Box>,
          document.body,
        )}
    </span>
  );
};

/**
 * Wraps a mention of a person: hovering it shows their card (name, email,
 * the workspaces and groups shared with the viewer).
 */
export const PersonHoverCard = ({
  userId,
  name,
  children,
}: {
  userId: string;
  /** Shown until the card loads, and for people one doesn't work with */
  name: string;
  children: ReactNode;
}) => {
  if (!userId) {
    return <>{children}</>;
  }
  return (
    <HoverCardAnchor
      label={name}
      testId="person-hover-card"
      dataAttributes={{ 'data-person-id': userId }}
      content={() => <CardContent userId={userId} fallbackName={name} />}
    >
      {children}
    </HoverCardAnchor>
  );
};
