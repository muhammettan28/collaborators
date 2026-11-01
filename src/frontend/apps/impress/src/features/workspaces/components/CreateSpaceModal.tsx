import {
  Button,
  Checkbox,
  Input,
  Modal,
  ModalSize,
  Radio,
  RadioGroup,
  VariantType,
  useToastProvider,
} from '@gouvfr-lasuite/ui-components';
import { useRouter } from 'next/router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { Box, BoxButton, Icon, Text } from '@/components';
import { User } from '@/features/auth';
import { Role } from '@/features/docs/doc-management';
import { createDocInvitation } from '@/features/docs/doc-share/api/useCreateDocInvitation';

import { useCreateSpace, useGroups } from '../api';
import { SpaceVisibility, Workspace } from '../types';

import { UserPicker } from './UserPicker';

interface CreateSpaceModalProps {
  /** The workspace to create the space in; none for an independent space. */
  workspace?: Workspace;
  onClose: () => void;
}

export const CreateSpaceModal = ({
  workspace,
  onClose,
}: CreateSpaceModalProps) => {
  const { t } = useTranslation();
  const { toast } = useToastProvider();
  const router = useRouter();
  const [title, setTitle] = useState('');
  const [visibility, setVisibility] = useState<SpaceVisibility>(
    workspace ? SpaceVisibility.WORKSPACE : SpaceVisibility.INVITED,
  );
  const [editors, setEditors] = useState<User[]>([]);
  // Collaborators: people invited by email, editors once they accept
  const [invitedEmails, setInvitedEmails] = useState<string[]>([]);
  const [editorGroupIds, setEditorGroupIds] = useState<string[]>([]);
  const { data: groups = [] } = useGroups(workspace?.id ?? '');
  const { mutate: createSpace, isPending } = useCreateSpace();

  const onCreate = () => {
    createSpace(
      {
        title: title.trim(),
        workspaceId: workspace?.id,
        visibility,
        editorUserIds: editors.map((user) => user.id),
        editorGroupIds,
      },
      {
        onSuccess: (space) => {
          void Promise.allSettled(
            invitedEmails.map((email) =>
              createDocInvitation({
                email,
                role: Role.EDITOR,
                docId: space.id,
              }),
            ),
          );
          onClose();
          void router.push(`/space/${space.id}/`);
        },
        onError: () => {
          toast(
            t('The space could not be created.', {
              description: 'Toast shown when creating a space failed',
            }),
            VariantType.ERROR,
          );
        },
      },
    );
  };

  const visibilities = [
    {
      value: SpaceVisibility.PUBLIC,
      icon: 'public',
      label: t('Public', { description: 'Space visibility option' }),
      help: t(
        'Anyone can read it, even without signing in. No one can edit it through this.',
        {
          description: 'Help text of the public space visibility',
        },
      ),
    },
    ...(workspace
      ? [
          {
            value: SpaceVisibility.WORKSPACE,
            icon: 'groups',
            label: t('All workspace members', {
              description: 'Space visibility option',
            }),
            help: t('Every member of {{name}} can read it.', {
              description: 'Help text of the workspace space visibility',
              name: workspace.name,
            }),
          },
        ]
      : []),
    {
      value: SpaceVisibility.INVITED,
      icon: 'lock',
      label: t('Only invited people', {
        description: 'Space visibility option',
      }),
      help: t('Only you and the people you add can open it.', {
        description: 'Help text of the invite-only space visibility',
      }),
    },
  ];

  const heading = workspace
    ? t('New space in {{name}}', {
        description: 'Title of the dialog creating a space in a workspace',
        name: workspace.name,
      })
    : t('New independent space', {
        description: 'Title of the dialog creating a space outside workspaces',
      });

  return (
    <Modal
      isOpen
      closeOnClickOutside
      onClose={onClose}
      size={ModalSize.MEDIUM}
      aria-label={heading}
      title={
        <Text as="h1" $margin="0" $size="h6" $align="flex-start">
          {heading}
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
            disabled={!title.trim() || isPending}
            onClick={onCreate}
          >
            {t('Create space', { description: 'Button creating a space' })}
          </Button>
        </>
      }
    >
      <Box $gap="md" $padding={{ top: 'xs' }}>
        <Input
          fullWidth
          label={t('Space name', { description: 'Label of the space name' })}
          value={title}
          autoFocus
          onChange={(event) => setTitle(event.target.value)}
        />

        <Box $gap="2xs">
          <Text as="h2" $size="sm" $weight="600" $margin="none">
            {t('Who can see this space?', {
              description: 'Heading of the space visibility choice',
            })}
          </Text>
          <RadioGroup>
            {visibilities.map((option) => (
              <Box key={option.value} $gap="4xs">
                <Radio
                  name="space-visibility"
                  value={option.value}
                  checked={visibility === option.value}
                  onChange={() => setVisibility(option.value)}
                  label={option.label}
                />
                <Box
                  $direction="row"
                  $align="center"
                  $gap="4xs"
                  $margin={{ left: '1.6rem' }}
                >
                  <Icon
                    iconName={option.icon}
                    $size="14px"
                    $variation="secondary"
                  />
                  <Text $size="xs" $variation="secondary">
                    {option.help}
                  </Text>
                </Box>
              </Box>
            ))}
          </RadioGroup>
        </Box>

        <Box $gap="2xs">
          <Text as="h2" $size="sm" $weight="600" $margin="none">
            {t('Who can edit it?', {
              description: 'Heading of the space editors choice',
            })}
          </Text>
          <Text $size="xs" $variation="secondary" $margin="none">
            {t(
              'You own the space. Add people or user groups who can edit it too.',
              {
                description: 'Help text of the space editors choice',
              },
            )}
          </Text>
          <UserPicker
            label={t('Add a person by name or email', {
              description: 'Label of the search adding a space editor',
            })}
            excludeIds={editors.map((user) => user.id)}
            onPick={(user) => setEditors((current) => [...current, user])}
            onInviteEmail={(email) =>
              setInvitedEmails((current) =>
                current.includes(email) ? current : [...current, email],
              )
            }
          />
          {invitedEmails.length > 0 && (
            <Box $direction="row" $gap="2xs" $css="flex-wrap: wrap;">
              {invitedEmails.map((email) => (
                <BoxButton
                  key={email}
                  onClick={() =>
                    setInvitedEmails((current) =>
                      current.filter((item) => item !== email),
                    )
                  }
                  aria-label={t('Remove {{name}}', {
                    description:
                      'Accessible name of a button removing a person',
                    name: email,
                  })}
                  title={t('Invited by email', {
                    description: 'Tooltip of an email to invite',
                  })}
                  $direction="row"
                  $align="center"
                  $gap="4xs"
                  $padding={{ horizontal: 'xs', vertical: '4xs' }}
                  $css={css`
                    border-radius: 999px;
                    background: var(
                      --c--contextuals--background--semantic--brand--tertiary
                    );
                  `}
                >
                  <Icon iconName="forward_to_inbox" $size="14px" />
                  <Text $size="sm">{email}</Text>
                  <Icon iconName="close" $size="14px" />
                </BoxButton>
              ))}
            </Box>
          )}
          {editors.length > 0 && (
            <Box $direction="row" $gap="2xs" $css="flex-wrap: wrap;">
              {editors.map((user) => (
                <BoxButton
                  key={user.id}
                  onClick={() =>
                    setEditors((current) =>
                      current.filter((item) => item.id !== user.id),
                    )
                  }
                  aria-label={t('Remove {{name}}', {
                    description:
                      'Accessible name of a button removing a person',
                    name: user.full_name || user.email,
                  })}
                  $direction="row"
                  $align="center"
                  $gap="4xs"
                  $padding={{ horizontal: 'xs', vertical: '4xs' }}
                  $css={css`
                    border-radius: 999px;
                    background: var(
                      --c--contextuals--background--semantic--contextual--primary
                    );
                  `}
                >
                  <Text $size="sm">{user.full_name || user.email}</Text>
                  <Icon iconName="close" $size="14px" />
                </BoxButton>
              ))}
            </Box>
          )}
          {groups.length > 0 && (
            <Box $gap="3xs" $margin={{ top: 'xs' }}>
              <Text $size="xs" $weight="600" $margin="none">
                {t('User groups', {
                  description: 'Heading of a list of groups',
                })}
              </Text>
              {groups.map((group) => (
                <Checkbox
                  key={group.id}
                  label={`${group.name} · ${t('{{count}} members', {
                    description: 'Number of members of a group',
                    count: group.nb_members,
                  })}`}
                  checked={editorGroupIds.includes(group.id)}
                  onChange={(event) =>
                    setEditorGroupIds((current) =>
                      event.target.checked
                        ? [...current, group.id]
                        : current.filter((id) => id !== group.id),
                    )
                  }
                />
              ))}
            </Box>
          )}
        </Box>
      </Box>
    </Modal>
  );
};
