import { VariantType } from '@gouvfr-lasuite/ui-components';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import { Box } from '@/components';
import { QuickSearchData } from '@/components/quick-search';
import { QuickSearchGroup } from '@/components/quick-search/QuickSearchGroup';
import { useCunninghamTheme } from '@/cunningham';
import { Access, Doc, Role } from '@/docs/doc-management/';
import { User } from '@/features/auth';
import { useToast } from '@/hooks';

import { useDocAccesses, useUpdateDocAccess } from '../api';
import { useWhoAmI } from '../hooks/';

import { DocRoleDropdown } from './DocRoleDropdown';
import { SearchUserRow } from './SearchUserRow';

type Props = {
  doc?: Doc;
  access: Access;
  isInherited?: boolean;
};
export const DocShareMemberItem = ({
  doc,
  access,
  isInherited = false,
}: Props) => {
  const { t } = useTranslation();
  const { isLastOwner } = useWhoAmI(access);
  const { toast } = useToast();
  const { spacingsTokens } = useCunninghamTheme();

  const message = isLastOwner
    ? t(
        'You are the sole owner of this group, make another member the group owner before you can change your own role or be removed from your page.',
        {
          description:
            'Tooltip shown when the last owner cannot change their role',
        },
      )
    : undefined;

  const { mutate: updateDocAccess } = useUpdateDocAccess({
    onError: () => {
      toast(
        t('Error while updating the member role.', {
          description: 'Toast shown when changing a member role failed',
        }),
        VariantType.ERROR,
        {
          duration: 4000,
        },
      );
    },
  });

  const onUpdate = (newRole: Role) => {
    if (!doc) {
      return;
    }
    updateDocAccess({
      docId: doc.id,
      role: newRole,
      accessId: access.id,
    });
  };

  const canUpdate = isInherited ? false : !!doc?.abilities.accesses_manage;

  // A team access (a group, or all members of a workspace) is shown like a
  // member, named after the team, with "Group" in place of an email.
  const member: User = access.user ?? {
    id: access.team,
    email: t('User group', { description: 'Shown under the name of a group' }),
    full_name: access.team_label || access.team,
    short_name: access.team_label || access.team,
    is_first_connection: false,
  };

  return (
    <Box
      $width="100%"
      data-testid={`doc-share-member-row-${access.user?.email ?? access.team}`}
      className="--docs--doc-share-member-item"
    >
      <SearchUserRow
        alwaysShowRight={true}
        user={member}
        right={
          <Box $direction="row" $align="center" $gap={spacingsTokens['2xs']}>
            <DocRoleDropdown
              currentRole={isInherited ? access.max_role : access.role}
              onSelectRole={onUpdate}
              isLastOwner={isLastOwner}
              canUpdate={canUpdate}
              message={message}
              rolesAllowed={access.abilities.set_role_to}
              access={access}
              doc={doc}
              ariaLabel={t('Change role for {{name}}', {
                description: 'Accessible name of the role dropdown of a member',
                name: member.full_name || member.email,
              })}
            />
          </Box>
        }
      />
    </Box>
  );
};

interface QuickSearchGroupMemberProps {
  doc: Doc;
}

export const QuickSearchGroupMember = ({
  doc,
}: QuickSearchGroupMemberProps) => {
  const { t } = useTranslation();
  const membersQuery = useDocAccesses({
    docId: doc.id,
  });

  const membersData: QuickSearchData<Access> = useMemo(() => {
    const members = membersQuery.data || [];

    const count = members.length;

    return {
      groupName:
        count === 1
          ? t('Page owner', {
              description: 'Label of the single owner of a document',
            })
          : t('Share with {{count}} users', {
              description:
                'Number of people a document is shared with, plural form',
              count: count,
            }),
      elements: members,
      endActions: undefined,
    };
  }, [membersQuery.data, t]);

  return (
    <Box
      aria-label={t('List members card', {
        description: 'Accessible name of the list of members',
      })}
      $padding={{ horizontal: 'base', bottom: '3xs' }}
    >
      <QuickSearchGroup
        group={membersData}
        renderElement={(access) => (
          <DocShareMemberItem doc={doc} access={access} />
        )}
      />
    </Box>
  );
};
