import { Button, Input, Modal, ModalSize } from '@gouvfr-lasuite/ui-components';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Box, BoxButton, Icon, Text } from '@/components';
import { Doc, Role } from '@/features/docs/doc-management';

import { useDocUserGroupMutations, useDocUserGroups } from '../api';
import { Group } from '../types';

import { ConfirmModal } from './ConfirmModal';
import {
  GroupMembers,
  IconButton,
  Row,
  useErrorToast,
} from './WorkspaceSettings';

/**
 * The user groups of a page or a space, from its menu: mentioned with "@" on
 * it and the pages below it, they notify their members who can see the page
 * and give no access. They stay attached to it wherever it moves. Its owners
 * and administrators create them; anyone can be in them.
 */
export const DocUserGroupsModal = ({
  doc,
  onClose,
}: {
  doc: Doc;
  onClose: () => void;
}) => {
  const { t } = useTranslation();
  const onError = useErrorToast();
  const { data: groups = [] } = useDocUserGroups(doc.id);
  const { create, remove } = useDocUserGroupMutations(doc.id);
  const [name, setName] = useState('');
  const [openGroupId, setOpenGroupId] = useState<string | null>(null);
  const [groupToDelete, setGroupToDelete] = useState<Group | null>(null);
  const isSpace = doc.kind === 'space';
  const canCreate =
    doc.user_role === Role.OWNER || doc.user_role === Role.ADMIN;
  const title = isSpace
    ? t('User groups of the space', {
        description: 'Title of the dialog of the user groups of a space',
      })
    : t('User groups of the page', {
        description: 'Title of the dialog of the user groups of a page',
      });

  return (
    <Modal
      isOpen
      closeOnClickOutside
      onClose={onClose}
      size={ModalSize.MEDIUM}
      aria-label={title}
      title={
        <Text as="h1" $margin="0" $size="h6" $align="flex-start">
          {title}
        </Text>
      }
      rightActions={
        <Button fullWidth onClick={onClose}>
          {t('Done', { description: 'Button closing a dialog' })}
        </Button>
      }
    >
      <Box $gap="sm" $padding={{ top: 'xs' }} data-testid="doc-user-groups">
        <Text $size="sm" $variation="secondary" $margin="none">
          {isSpace
            ? t(
                'Mention a user group with @ in this space to notify its members who can see the page. It gives no access, and stays with the space wherever it moves.',
                { description: 'Explanation of the user groups of a space' },
              )
            : t(
                'Mention a user group with @ on this page and the pages below it, to notify its members who can see the page. It gives no access, and stays with the page wherever it moves.',
                { description: 'Explanation of the user groups of a page' },
              )}
        </Text>
        {canCreate && (
          <Box $direction="row" $gap="sm" $align="flex-end">
            <Box $flex={1}>
              <Input
                fullWidth
                label={t('New user group name', {
                  description: 'Label of the group name field',
                })}
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </Box>
            <Button
              disabled={!name.trim()}
              onClick={() =>
                create.mutate(
                  { name: name.trim() },
                  { onError, onSuccess: () => setName('') },
                )
              }
            >
              {t('Create', { description: 'Button creating something' })}
            </Button>
          </Box>
        )}
        <Box>
          {groups.length === 0 && (
            <Text $size="sm" $variation="secondary">
              {t('No user group yet.', {
                description: 'Shown when there is no group',
              })}
            </Text>
          )}
          {groups.map((group) => (
            <Box key={group.id}>
              <Row>
                <BoxButton
                  onClick={() =>
                    setOpenGroupId(openGroupId === group.id ? null : group.id)
                  }
                  aria-expanded={openGroupId === group.id}
                  $direction="row"
                  $align="center"
                  $gap="xs"
                  $flex={1}
                >
                  <Icon iconName="groups" $size="20px" $variation="secondary" />
                  <Text $weight="500">{group.name}</Text>
                  <Text $size="xs" $variation="secondary">
                    {group.nb_members === 1
                      ? t('1 member', {
                          description: 'Number of members of a group',
                        })
                      : t('{{count}} members', {
                          description: 'Number of members of a group',
                          count: group.nb_members,
                        })}
                    {group.created_by &&
                      ` · ${t('created by {{name}}', {
                        description: 'Who created a group',
                        name: group.created_by.full_name,
                      })}`}
                  </Text>
                  <Icon
                    iconName={
                      openGroupId === group.id ? 'expand_less' : 'expand_more'
                    }
                    $size="20px"
                    $variation="secondary"
                  />
                </BoxButton>
                {group.abilities.destroy && (
                  <IconButton
                    icon="delete"
                    label={t('Delete {{name}}', {
                      description: 'Button deleting a group',
                      name: group.name,
                    })}
                    onClick={() => setGroupToDelete(group)}
                  />
                )}
              </Row>
              {openGroupId === group.id && (
                <GroupMembers
                  group={group}
                  otherGroups={groups.filter((other) => other.id !== group.id)}
                />
              )}
            </Box>
          ))}
        </Box>
      </Box>
      {groupToDelete && (
        <ConfirmModal
          title={t('Delete {{name}}', {
            description: 'Button deleting a group',
            name: groupToDelete.name,
          })}
          message={t(
            'Delete the user group "{{name}}"? Mentioning it will notify no one anymore.',
            {
              description:
                'Confirmation before deleting a user group of a page',
              name: groupToDelete.name,
            },
          )}
          confirmLabel={t('Delete', { description: 'Button deleting' })}
          onClose={() => setGroupToDelete(null)}
          onConfirm={() =>
            remove.mutate({ groupId: groupToDelete.id }, { onError })
          }
        />
      )}
    </Modal>
  );
};
