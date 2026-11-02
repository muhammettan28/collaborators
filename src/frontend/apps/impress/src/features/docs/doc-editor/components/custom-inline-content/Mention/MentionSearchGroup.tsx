import { useTranslation } from 'react-i18next';
import { useDebounce } from 'use-debounce';

import {
  Box,
  Icon,
  QuickSearchGroup,
  QuickSearchItemContent,
  Text,
} from '@/components';
import { usePeopleToMention } from '@/features/docs/doc-share/api/usePeopleToMention';
import { useGrantableTeams } from '@/features/workspaces/api';

export interface MentionCandidate {
  kind: 'user' | 'group';
  id: string;
  label: string;
  detail: string;
  memberCount?: number;
}

/** Beyond this, the row warns how many people a group mention notifies. */
export const LARGE_GROUP = 20;

interface MentionSearchGroupProps {
  docId: string;
  search: string;
  onSelect: (candidate: MentionCandidate) => void;
}

/**
 * Everyone and every group that "@" can mention, above the pages to link,
 * listed before anything is typed; typing narrows them.
 */
export const MentionSearchGroup = ({
  docId,
  search,
  onSelect,
}: MentionSearchGroupProps) => {
  const { t } = useTranslation();
  const [query] = useDebounce(search, 250);
  // From the first letter, or none: the people one works with first
  const users = usePeopleToMention(query);
  const { data: teams = [] } = useGrantableTeams(docId, query, true);

  const candidates: MentionCandidate[] = [
    ...teams.map((team) => ({
      kind: 'group' as const,
      id: team.team,
      label: team.label,
      detail: team.place.name,
      memberCount: team.member_count,
    })),
    ...users.map((user) => ({
      kind: 'user' as const,
      id: user.id,
      label: user.full_name || user.email,
      detail: user.full_name ? user.email : '',
    })),
  ];

  if (!candidates.length) {
    return null;
  }

  return (
    <QuickSearchGroup
      group={{
        groupName: t('Mention someone', {
          description: 'Heading of people and groups in the @ menu',
        }),
        groupKey: 'mention',
        elements: candidates,
      }}
      onSelect={onSelect}
      renderElement={(candidate) => (
        <QuickSearchItemContent
          left={
            <Box
              $direction="row"
              $gap="0.5rem"
              $align="center"
              $padding={{ vertical: '0.4rem', horizontal: '0.2rem' }}
            >
              <Icon
                iconName={candidate.kind === 'group' ? 'groups' : 'person'}
                $size="20px"
              />
              <Text $size="sm" $weight="500">
                {candidate.label}
              </Text>
              <Text $size="xs" $variation="secondary">
                {candidate.memberCount !== undefined &&
                candidate.memberCount > LARGE_GROUP
                  ? t('notifies {{count}} people', {
                      description: 'Warning on a large group in the @ menu',
                      count: candidate.memberCount,
                    })
                  : candidate.detail}
              </Text>
            </Box>
          }
        />
      )}
    />
  );
};
