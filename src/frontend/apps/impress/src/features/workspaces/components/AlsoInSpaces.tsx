import { Checkbox, Select } from '@gouvfr-lasuite/ui-components';
import { useTranslation } from 'react-i18next';

import { Box, Text } from '@/components';
import { Role, RoleImportance, useTrans } from '@/features/docs/doc-management';

import { useSpaces } from '../api';
import { Space } from '../types';

/** The spaces chosen for someone joining the workspace, with their role. */
export type SpaceChoices = Record<string, Role>;

const OFFERED = [Role.READER, Role.EDITOR, Role.ADMIN];

/**
 * The roles worth giving on a space: above what every member of the
 * workspace already has on it (a commenter counts as a reader).
 */
export const rolesAbove = (space: Space) => {
  const members = space.members_role
    ? (RoleImportance[space.members_role as Role] ??
      RoleImportance[Role.READER])
    : 0;
  return OFFERED.filter((role) => RoleImportance[role] > members);
};

/** The spaces of a workspace the user may share. */
export const useShareableSpaces = (workspaceId: string, enabled = true) => {
  const { data: spaces = [] } = useSpaces({ workspaceId }, enabled);
  return spaces.filter((space) => space.abilities.accesses_manage);
};

interface AlsoInSpacesProps {
  spaces: Space[];
  value: SpaceChoices;
  onChange: (value: SpaceChoices) => void;
}

/**
 * "Also add them to these spaces", above the search adding someone to a
 * workspace (which adds them as soon as they are picked): each space one
 * may share, with the role to give. A space all members already get at
 * the highest role offered is shown, not offered.
 */
export const AlsoInSpaces = ({
  spaces,
  value,
  onChange,
}: AlsoInSpacesProps) => {
  const { t } = useTranslation();
  const { translatedRoles } = useTrans();

  if (spaces.length === 0) {
    return null;
  }

  return (
    <Box $gap="2xs" data-testid="also-in-spaces">
      <Text $size="sm" $weight="600">
        {t('Also add them to these spaces', {
          description: 'Heading of the spaces offered when adding a member',
        })}
      </Text>
      <Text $size="xs" $variation="secondary">
        {t('Check them before adding someone below.', {
          description: 'Hint under the spaces offered when adding a member',
        })}
      </Text>
      {spaces.map((space) => {
        const roles = rolesAbove(space);
        const chosen = value[space.id];
        const title =
          space.title ||
          t('Untitled space', { description: 'Name of a space without title' });
        return (
          <Box
            key={space.id}
            $direction="row"
            $align="center"
            $gap="sm"
            $css="flex-wrap: wrap;"
          >
            <Box $flex={1} $css="min-width: 180px;">
              <Checkbox
                label={title}
                checked={!!chosen}
                disabled={roles.length === 0}
                onChange={(event) => {
                  const next = { ...value };
                  if (event.target.checked) {
                    next[space.id] = roles[0];
                  } else {
                    delete next[space.id];
                  }
                  onChange(next);
                }}
              />
              {space.members_role && (
                <Text $size="xs" $variation="secondary">
                  {t('Members already get it as {{role}}', {
                    description:
                      'A space every workspace member has a role on, when adding a member',
                    role: (
                      translatedRoles[space.members_role as Role] ??
                      space.members_role
                    ).toLowerCase(),
                  })}
                </Text>
              )}
            </Box>
            {chosen && (
              <Box $width="170px">
                <Select
                  fullWidth
                  label={t('Role in {{space}}', {
                    description: 'Label of the role given on a space',
                    space: title,
                  })}
                  hideLabel
                  clearable={false}
                  options={roles.map((role) => ({
                    value: role,
                    label: translatedRoles[role],
                  }))}
                  value={chosen}
                  onChange={(event) =>
                    onChange({
                      ...value,
                      [space.id]: event.target.value as Role,
                    })
                  }
                />
              </Box>
            )}
          </Box>
        );
      })}
    </Box>
  );
};
