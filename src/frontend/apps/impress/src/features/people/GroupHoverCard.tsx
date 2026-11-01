import { useQuery } from '@tanstack/react-query';
import { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { APIError, errorCauses, fetchAPI } from '@/api';
import { Box, Icon, StyledLink, Text } from '@/components';
import { UserAvatar } from '@/features/auth';
import { profileHref } from '@/features/profile/api';

import { HoverCardAnchor } from './PersonHoverCard';

/** What one may see of a mentioned group, see the backend's teams/<team>/. */
export interface TeamCard {
  team: string;
  kind: 'team' | 'organization' | 'workspace' | 'workspace-admins';
  name: string;
  /** In the group's workspace: then its workspace and members are given */
  known: boolean;
  workspace: { id: string; name: string } | null;
  member_count: number;
  members: {
    id: string;
    full_name: string;
    short_name: string;
    is_me: boolean;
    is_manager: boolean;
  }[];
}

export const KEY_TEAM_CARD = 'team-card';

export const useTeamCard = (team: string, enabled: boolean) =>
  useQuery<TeamCard, APIError>({
    queryKey: [KEY_TEAM_CARD, team],
    queryFn: async () => {
      const response = await fetchAPI(`teams/${encodeURIComponent(team)}/`);
      if (!response.ok) {
        throw new APIError(
          'Failed to get the group',
          await errorCauses(response),
        );
      }
      return response.json() as Promise<TeamCard>;
    },
    enabled: enabled && !!team,
    staleTime: 5 * 60_000,
    retry: false,
  });

const CardContent = ({
  team,
  fallbackName,
}: {
  team: string;
  fallbackName: string;
}) => {
  const { t } = useTranslation();
  const { data: card, isLoading, isError } = useTeamCard(team, true);
  const name = card?.name || fallbackName;
  const kinds: Record<TeamCard['kind'], string> = {
    team: t('Team', { description: 'Kind of group' }),
    organization: t('Organization', { description: 'Kind of group' }),
    workspace: t('Everyone in the workspace', {
      description: 'Kind of group: all the members of a workspace',
    }),
    'workspace-admins': t('Workspace administrators', {
      description: 'Kind of group: the administrators of a workspace',
    }),
  };
  const hiddenCount = card ? card.member_count - card.members.length : 0;

  return (
    <Box $gap="xs">
      <Box $direction="row" $align="center" $gap="xs">
        <Box
          $align="center"
          $justify="center"
          $css={css`
            flex: 0 0 auto;
            width: 32px;
            height: 32px;
            border-radius: 50%;
            background: var(
              --c--contextuals--background--semantic--brand--tertiary,
              #ece6fb
            );
            color: var(--c--globals--colors--brand-700, #4f3497);
          `}
        >
          <Icon iconName="groups" $size="18px" $color="inherit" />
        </Box>
        <Box $css="min-width: 0;">
          <Text $weight="600" $ellipsis>
            {name}
          </Text>
          {card && (
            <Text $size="xs" $variation="secondary" $ellipsis>
              {card.workspace
                ? `${kinds[card.kind]} · ${card.workspace.name}`
                : kinds[card.kind]}
            </Text>
          )}
        </Box>
      </Box>
      {isLoading && (
        <Text $size="xs" $variation="secondary">
          {t('Loading…', { description: 'Shown while something loads' })}
        </Text>
      )}
      {card?.known && (
        <>
          <Text $size="xs" $weight="600" $variation="secondary">
            {card.member_count === 1
              ? t('1 member', { description: 'Number of people in a group' })
              : t('{{count}} members', {
                  description: 'Number of people in a group',
                  count: card.member_count,
                })}
          </Text>
          <Box
            as="ul"
            $gap="4xs"
            $margin="none"
            $padding="none"
            data-testid="group-hover-card-members"
            $css={css`
              list-style: none;
              max-height: 220px;
              overflow-y: auto;
            `}
          >
            {card.members.map((member) => (
              <Box as="li" key={member.id}>
                <StyledLink
                  href={profileHref(member.id)}
                  $css={css`
                    display: flex;
                    align-items: center;
                    gap: var(--c--globals--spacings--2xs);
                    padding: 2px 0;
                    &:hover .member-name {
                      text-decoration: underline;
                    }
                  `}
                >
                  <Box $css="flex: 0 0 auto; zoom: 0.75;">
                    <UserAvatar fullName={member.full_name} />
                  </Box>
                  <Text $size="sm" $ellipsis className="member-name">
                    {member.full_name}
                    {member.is_me &&
                      ` ${t('(you)', { description: 'After one’s own name' })}`}
                  </Text>
                  {member.is_manager && (
                    <Text
                      $size="xs"
                      $variation="secondary"
                      $css="margin-left: auto; flex: 0 0 auto;"
                    >
                      {card.kind === 'team' || card.kind === 'organization'
                        ? t('Manager', {
                            description: 'Role of a person in a group',
                          })
                        : t('Admin', {
                            description: 'Role of a person in a workspace',
                          })}
                    </Text>
                  )}
                </StyledLink>
              </Box>
            ))}
          </Box>
          {hiddenCount > 0 && (
            <Text $size="xs" $variation="secondary">
              {t('and {{count}} more', {
                description: 'After the first members listed of a group',
                count: hiddenCount,
              })}
            </Text>
          )}
          {card.member_count === 0 && (
            <Text $size="xs" $variation="secondary">
              {t('Nobody is in this user group yet.', {
                description: 'Card of a group without members',
              })}
            </Text>
          )}
        </>
      )}
      {card && !card.known && (
        <Text $size="xs" $variation="secondary">
          {t('Only people of this user group’s workspace see who is in it.', {
            description: 'Card of a group from a workspace one is not in',
          })}
        </Text>
      )}
      {isError && (
        <Text $size="xs" $variation="secondary">
          {t('This user group can’t be shown.', {
            description: 'Group card that could not load',
          })}
        </Text>
      )}
    </Box>
  );
};

/**
 * Wraps a mention of a group ("group:<id>", or a whole workspace): hovering
 * it shows who is in it, for the people of its workspace.
 */
export const GroupHoverCard = ({
  team,
  name,
  children,
}: {
  /** The team string, e.g. "group:<id>" or "workspace:<id>" */
  team: string;
  /** Shown until the card loads */
  name: string;
  children: ReactNode;
}) => {
  if (!team) {
    return <>{children}</>;
  }
  return (
    <HoverCardAnchor
      label={name}
      testId="group-hover-card"
      dataAttributes={{ 'data-team': team }}
      content={() => <CardContent team={team} fallbackName={name} />}
    >
      {children}
    </HoverCardAnchor>
  );
};
