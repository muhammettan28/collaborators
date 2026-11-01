import {
  Button,
  Input,
  Modal,
  ModalSize,
  VariantType,
  useToastProvider,
} from '@gouvfr-lasuite/ui-components';
import { useRouter } from 'next/router';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { fetchAPI } from '@/api';
import { Box, BoxButton, Icon, Text } from '@/components';
import { User } from '@/features/auth';
import { inviteToWorkspace } from '@/features/invitations/api';

import { useCreateWorkspace } from '../api';
import { useWorkspaceStore } from '../stores/useWorkspaceStore';

import { UserPicker } from './UserPicker';

/** A person or an email chosen to join, shown as a chip to take back. */
const Chip = ({
  label,
  icon,
  onRemove,
  removeLabel,
}: {
  label: string;
  icon: string;
  onRemove: () => void;
  removeLabel: string;
}) => (
  <BoxButton
    onClick={onRemove}
    aria-label={removeLabel}
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
    <Icon iconName={icon} $size="14px" />
    <Text $size="sm">{label}</Text>
    <Icon iconName="close" $size="14px" />
  </BoxButton>
);

interface CreateWorkspaceModalProps {
  onClose: () => void;
}

export const CreateWorkspaceModal = ({
  onClose,
}: CreateWorkspaceModalProps) => {
  const { t } = useTranslation();
  const { toast } = useToastProvider();
  const [name, setName] = useState('');
  // Collaborators: members from the start, found by name or invited by email
  const [members, setMembers] = useState<User[]>([]);
  const [emails, setEmails] = useState<string[]>([]);
  const { setCurrentWorkspaceId } = useWorkspaceStore();
  const router = useRouter();
  const { mutate: createWorkspace, isPending } = useCreateWorkspace();

  const onCreate = () => {
    createWorkspace(
      { name: name.trim() },
      {
        onSuccess: (workspace) => {
          void Promise.allSettled([
            ...members.map((member) =>
              fetchAPI(`workspaces/${workspace.id}/accesses/`, {
                method: 'POST',
                body: JSON.stringify({ user_id: member.id, role: 'member' }),
              }),
            ),
            ...emails.map((email) => inviteToWorkspace(workspace.id, email)),
          ]);
          setCurrentWorkspaceId(workspace.id);
          onClose();
          void router.push(`/workspace/${workspace.id}/`);
        },
        onError: () => {
          toast(
            t('The workspace could not be created.', {
              description: 'Toast shown when creating a workspace failed',
            }),
            VariantType.ERROR,
          );
        },
      },
    );
  };

  const title = t('Create a workspace', {
    description: 'Title of the dialog creating a workspace',
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
            disabled={!name.trim() || isPending}
            onClick={onCreate}
          >
            {t('Create', { description: 'Button creating something' })}
          </Button>
        </>
      }
    >
      <Box $gap="sm" $padding={{ top: 'xs' }}>
        <Text $variation="secondary" as="p" $margin="none">
          {t(
            'A workspace gathers the spaces, members and user groups of an organisation, a company or a community. You will be its owner.',
            { description: 'Explanation in the dialog creating a workspace' },
          )}
        </Text>
        <Input
          fullWidth
          label={t('Workspace name', {
            description: 'Label of the workspace name field',
          })}
          value={name}
          autoFocus
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && name.trim()) {
              onCreate();
            }
          }}
        />
        <Box $gap="2xs">
          <Text as="h2" $size="sm" $weight="600" $margin="none">
            {t('Who joins it? (optional)', {
              description: 'Heading of the members chosen with a new workspace',
            })}
          </Text>
          <Text $size="xs" $variation="secondary" $margin="none">
            {t(
              'Add people you work with by name, or invite anyone by email: they receive a link to sign up and join.',
              { description: 'Help text of the members of a new workspace' },
            )}
          </Text>
          <UserPicker
            label={t('Add a person by name or email', {
              description: 'Label of the search adding a workspace member',
            })}
            excludeIds={members.map((member) => member.id)}
            onPick={(user) => setMembers((current) => [...current, user])}
            onInviteEmail={(email) =>
              setEmails((current) =>
                current.includes(email) ? current : [...current, email],
              )
            }
          />
          {(members.length > 0 || emails.length > 0) && (
            <Box $direction="row" $gap="2xs" $css="flex-wrap: wrap;">
              {members.map((member) => (
                <Chip
                  key={member.id}
                  icon="person"
                  label={member.full_name || member.email}
                  removeLabel={t('Remove {{name}}', {
                    description:
                      'Accessible name of a button removing a person',
                    name: member.full_name || member.email,
                  })}
                  onRemove={() =>
                    setMembers((current) =>
                      current.filter((item) => item.id !== member.id),
                    )
                  }
                />
              ))}
              {emails.map((email) => (
                <Chip
                  key={email}
                  icon="forward_to_inbox"
                  label={email}
                  removeLabel={t('Remove {{name}}', {
                    description:
                      'Accessible name of a button removing a person',
                    name: email,
                  })}
                  onRemove={() =>
                    setEmails((current) =>
                      current.filter((item) => item !== email),
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
