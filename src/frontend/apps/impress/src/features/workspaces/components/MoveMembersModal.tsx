import {
  Button,
  Modal,
  ModalSize,
  Radio,
  RadioGroup,
  Select,
} from '@gouvfr-lasuite/ui-components';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Box, Text } from '@/components';

import { useGroupMemberMutations } from '../api';
import { Group } from '../types';

interface MoveMembersModalProps {
  group: Group;
  /** The other groups whose members the user can manage */
  targets: Group[];
  userIds: string[];
  onDone: () => void;
  onClose: () => void;
}

/** Move or copy chosen members of a group into another group. */
export const MoveMembersModal = ({
  group,
  targets,
  userIds,
  onDone,
  onClose,
}: MoveMembersModalProps) => {
  const { t } = useTranslation();
  const { transfer } = useGroupMemberMutations(group.id);
  const [targetId, setTargetId] = useState('');
  const [mode, setMode] = useState<'move' | 'copy'>('move');
  const title =
    userIds.length === 1
      ? t('Move or copy 1 person', {
          description: 'Title of the dialog moving members between groups',
        })
      : t('Move or copy {{count}} people', {
          description: 'Title of the dialog moving members between groups',
          count: userIds.length,
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
        <>
          <Button variant="secondary" fullWidth onClick={onClose}>
            {t('Cancel', {
              description: 'Button to dismiss a dialog without confirming',
            })}
          </Button>
          <Button
            fullWidth
            disabled={!targetId || transfer.isPending}
            onClick={() =>
              transfer.mutate(
                { userIds, toGroupId: targetId, mode },
                {
                  onSuccess: () => {
                    onDone();
                    onClose();
                  },
                },
              )
            }
          >
            {mode === 'move'
              ? t('Move', { description: 'Button moving something' })
              : t('Copy', { description: 'Button copying people to a group' })}
          </Button>
        </>
      }
    >
      <Box $gap="sm" $padding={{ top: 'xs' }}>
        <Select
          fullWidth
          label={t('To the user group', {
            description: 'Label choosing the group people go to',
          })}
          clearable={false}
          options={targets.map((target) => ({
            value: target.id,
            label: target.name,
          }))}
          value={targetId}
          onChange={(event) => setTargetId(event.target.value as string)}
        />
        <RadioGroup>
          <Radio
            name="move-members-mode"
            value="move"
            checked={mode === 'move'}
            onChange={() => setMode('move')}
            label={t('Move: they leave {{name}}', {
              description: 'Moving people out of a group into another',
              name: group.name,
            })}
          />
          <Radio
            name="move-members-mode"
            value="copy"
            checked={mode === 'copy'}
            onChange={() => setMode('copy')}
            label={t('Copy: they stay in {{name}} too', {
              description: 'Adding people to another group as well',
              name: group.name,
            })}
          />
        </RadioGroup>
        {transfer.isError && (
          <Text $size="sm" $theme="error" role="alert">
            {transfer.error.cause?.[0] ??
              t('Something went wrong.', {
                description: 'Generic error message',
              })}
          </Text>
        )}
      </Box>
    </Modal>
  );
};
