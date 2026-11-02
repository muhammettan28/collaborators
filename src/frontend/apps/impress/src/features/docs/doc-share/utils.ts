import { User } from '@/features/auth';
import { GrantableTeam } from '@/features/workspaces/types';

/**
 * Groups are picked in the share dialog like people: as a User whose id is
 * the team string behind this prefix, so the invite list handles both.
 */
export const TEAM_MEMBER_PREFIX = 'team::';

export const teamFromMemberId = (memberId: string): string | null =>
  memberId.startsWith(TEAM_MEMBER_PREFIX)
    ? memberId.slice(TEAM_MEMBER_PREFIX.length)
    : null;

export const teamAsUser = (team: GrantableTeam): User => ({
  id: `${TEAM_MEMBER_PREFIX}${team.team}`,
  full_name: team.label,
  short_name: team.label,
  email: team.place.name,
  is_first_connection: false,
});
