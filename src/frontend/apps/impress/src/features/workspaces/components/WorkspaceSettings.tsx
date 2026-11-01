import {
  Button,
  Checkbox,
  Input,
  Select,
  Switch,
  VariantType,
  useToastProvider,
} from '@gouvfr-lasuite/ui-components';
import { useRouter } from 'next/router';
import { PropsWithChildren, ReactNode, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import {
  Box,
  BoxButton,
  Icon,
  SCREEN_MAX_WIDTH,
  StyledLink,
  Text,
} from '@/components';
import { useAuth } from '@/features/auth';
import { Role } from '@/features/docs/doc-management';
import { createDocAccess } from '@/features/docs/doc-share/api/useCreateDocAccess';
import { createDocInvitation } from '@/features/docs/doc-share/api/useCreateDocInvitation';
import { SearchUserRow } from '@/features/docs/doc-share/components/SearchUserRow';
import { LogoPicker } from '@/features/invitations/LogoPicker';
import {
  useWorkspaceInvitationMutations,
  useWorkspaceInvitations,
} from '@/features/invitations/api';
import { LabelEditor } from '@/features/labels/LabelEditor';
import { PublishingSection } from '@/features/publishing/PublishingSection';

import {
  useDeleteWorkspace,
  useGroupMemberMutations,
  useGroupMembers,
  useGroupMutations,
  useGroups,
  useSpaceMutations,
  useSpaces,
  useUpdateWorkspace,
  useWorkspaceAccessMutations,
  useWorkspaceAccesses,
  useWorkspaceGrantMutations,
  useWorkspaceGrants,
  useWorkspaces,
} from '../api';
import { useWorkspaceStore } from '../stores/useWorkspaceStore';
import {
  Group,
  GroupKind,
  Space,
  Workspace,
  WorkspaceRole,
  WorkspaceVisibility,
} from '../types';

import { AlsoInSpaces, SpaceChoices, useShareableSpaces } from './AlsoInSpaces';
import { ConfirmModal } from './ConfirmModal';
import { JoiningSection } from './JoiningSection';
import { MoveMembersModal } from './MoveMembersModal';
import { UserPicker } from './UserPicker';

/** Turn an API error into a toast. */
const useErrorToast = () => {
  const { toast } = useToastProvider();
  const { t } = useTranslation();
  return (error?: { cause?: string[] }) =>
    toast(
      error?.cause?.[0] ??
        t('Something went wrong.', {
          description: 'Generic error toast of workspace settings',
        }),
      VariantType.ERROR,
    );
};

const Section = ({
  title,
  description,
  children,
}: PropsWithChildren<{ title: string; description?: ReactNode }>) => (
  <Box
    as="section"
    $gap="sm"
    $padding="md"
    $css={css`
      border: 1px solid var(--c--contextuals--border--surface--primary);
      border-radius: var(--c--globals--spacings--xs);
      background: var(--c--contextuals--background--surface--primary);
    `}
  >
    <Box $gap="4xs">
      <Text as="h2" $size="h6" $margin="none">
        {title}
      </Text>
      {description && (
        <Text $size="sm" $variation="secondary" $margin="none">
          {description}
        </Text>
      )}
    </Box>
    {children}
  </Box>
);

const Row = ({ children }: PropsWithChildren) => (
  <Box
    $direction="row"
    $align="center"
    $justify="space-between"
    $gap="sm"
    $padding={{ vertical: '3xs' }}
    $css={css`
      border-bottom: 1px solid var(--c--contextuals--border--surface--primary);
      &:last-child {
        border-bottom: none;
      }
    `}
  >
    {children}
  </Box>
);

const IconButton = ({
  icon,
  label,
  onClick,
}: {
  icon: string;
  label: string;
  onClick: () => void;
}) => (
  <BoxButton
    onClick={onClick}
    aria-label={label}
    title={label}
    $padding="3xs"
    $css="border-radius: 4px;"
  >
    <Icon iconName={icon} $size="20px" $variation="secondary" />
  </BoxButton>
);

// -- General

const GeneralSection = ({ workspace }: { workspace: Workspace }) => {
  const { t } = useTranslation();
  const router = useRouter();
  const onError = useErrorToast();
  const [name, setName] = useState(workspace.name);
  const { mutate: updateWorkspace } = useUpdateWorkspace();
  const { mutate: deleteWorkspace } = useDeleteWorkspace();
  const { setCurrentWorkspaceId } = useWorkspaceStore();
  const [isDeleting, setIsDeleting] = useState(false);

  return (
    <Section
      title={t('General', { description: 'Heading of workspace settings' })}
    >
      <Box $direction="row" $gap="sm" $align="flex-end">
        <Box $flex={1}>
          <Input
            fullWidth
            label={t('Workspace name', {
              description: 'Label of the workspace name field',
            })}
            value={name}
            disabled={!workspace.abilities.update}
            onChange={(event) => setName(event.target.value)}
          />
        </Box>
        {workspace.abilities.update && (
          <Button
            disabled={!name.trim() || name === workspace.name}
            onClick={() =>
              updateWorkspace({ id: workspace.id, name }, { onError })
            }
          >
            {t('Save', { description: 'Button saving a change' })}
          </Button>
        )}
      </Box>
      <Box $gap="3xs">
        <Text $size="sm" $weight="600">
          {t('Logo', { description: 'Heading of a workspace’s logo' })}
        </Text>
        <LogoPicker
          owner="workspaces"
          id={workspace.id}
          canEdit={workspace.abilities.update}
          fallbackIcon="workspaces"
        />
      </Box>
      <Box $gap="3xs">
        <Text $size="sm" $weight="600">
          {t('Labels', { description: 'Heading of a workspace’s labels' })}
        </Text>
        <LabelEditor path={`workspaces/${workspace.id}`} />
      </Box>
      <Box $gap="3xs">
        <Select
          fullWidth
          label={t('Who can find this workspace', {
            description: 'Label of the workspace visibility choice',
          })}
          clearable={false}
          disabled={!workspace.abilities.update}
          options={[
            {
              value: 'public',
              label: t('Public on the internet', {
                description: 'Visibility: anyone, even without an account',
              }),
            },
            {
              value: 'platform',
              label: t('Everyone on Collaborators', {
                description: 'Visibility: every signed-in collaborator',
              }),
            },
            {
              value: 'hidden',
              label: t('Only its members', {
                description: 'Visibility of a hidden workspace',
              }),
            },
          ]}
          value={workspace.visibility}
          onChange={(event) =>
            updateWorkspace(
              {
                id: workspace.id,
                visibility: event.target.value as WorkspaceVisibility,
              },
              { onError },
            )
          }
        />
        <Text $size="xs" $variation="secondary">
          {t(
            'Findable workspaces are listed in "Discover workspaces" with their name, description and public spaces; people can ask to join, and administrators approve. Public ones are listed even to people without an account.',
            { description: 'Explanation of the workspace visibility' },
          )}
        </Text>
      </Box>
      {workspace.abilities.destroy && (
        <Box $direction="row" $justify="flex-end">
          <Button
            color="error"
            variant="secondary"
            onClick={() => setIsDeleting(true)}
          >
            {t('Delete workspace', {
              description: 'Button deleting a workspace',
            })}
          </Button>
        </Box>
      )}
      {isDeleting && (
        <ConfirmModal
          title={t('Delete workspace', {
            description: 'Button deleting a workspace',
          })}
          message={t(
            'Delete the workspace "{{name}}"? Its spaces stay available to their members as independent spaces.',
            {
              description: 'Confirmation before deleting a workspace',
              name: workspace.name,
            },
          )}
          confirmLabel={t('Delete', { description: 'Button deleting' })}
          onClose={() => setIsDeleting(false)}
          onConfirm={() =>
            deleteWorkspace(
              { id: workspace.id },
              {
                onError,
                onSuccess: () => {
                  setCurrentWorkspaceId(null);
                  void router.push('/');
                },
              },
            )
          }
        />
      )}
    </Section>
  );
};

// -- Members

const MembersSection = ({ workspace }: { workspace: Workspace }) => {
  const { t } = useTranslation();
  const { user } = useAuth();
  const onError = useErrorToast();
  const { data: accesses = [] } = useWorkspaceAccesses(workspace.id);
  const { add, update, remove } = useWorkspaceAccessMutations(workspace.id);
  const canManage = workspace.abilities.manage_accesses;
  const { data: invitations = [] } = useWorkspaceInvitations(
    workspace.id,
    canManage,
  );
  const { invite, cancel } = useWorkspaceInvitationMutations(workspace.id);
  const { toast } = useToastProvider();
  const shareableSpaces = useShareableSpaces(workspace.id, canManage);
  const [alsoIn, setAlsoIn] = useState<SpaceChoices>({});

  // Once in the workspace: the spaces chosen too, a role for one picked by
  // name, an invitation for an email (sent with the workspace's, in one email)
  const addToSpaces = async (
    target: { userId: string } | { email: string },
  ) => {
    const chosen = Object.entries(alsoIn);
    setAlsoIn({});
    if (chosen.length === 0) {
      return;
    }
    const results = await Promise.allSettled(
      chosen.map(([docId, role]) =>
        'email' in target
          ? createDocInvitation({ email: target.email, role, docId })
          : createDocAccess({ memberId: target.userId, role, docId }),
      ),
    );
    const failed = chosen
      .filter((_, index) => results[index].status === 'rejected')
      .map(
        ([docId]) =>
          shareableSpaces.find((space) => space.id === docId)?.title ?? '…',
      );
    if (failed.length > 0) {
      toast(
        t('Added to the workspace, but not to: {{spaces}}', {
          description:
            'Toast when adding someone to some of the chosen spaces failed',
          spaces: failed.join(', '),
        }),
        VariantType.ERROR,
      );
    }
  };

  const roles = [
    {
      value: WorkspaceRole.MEMBER,
      label: t('Member', { description: 'Workspace role' }),
    },
    {
      value: WorkspaceRole.ADMIN,
      label: t('Administrator', { description: 'Workspace role' }),
    },
    {
      value: WorkspaceRole.OWNER,
      label: t('Owner', { description: 'Workspace role' }),
    },
  ];

  return (
    <Section
      title={t('Members', { description: 'Heading of workspace members' })}
      description={t(
        'Members can see the spaces opened to the workspace and create spaces. Administrators manage members, user groups and every space of the workspace.',
        { description: 'Explanation of workspace roles' },
      )}
    >
      {canManage && (
        <AlsoInSpaces
          spaces={shareableSpaces}
          value={alsoIn}
          onChange={setAlsoIn}
        />
      )}
      {canManage && (
        <UserPicker
          label={t('Add a collaborator by name or email', {
            description: 'Label of the search adding a workspace member',
          })}
          excludeIds={accesses.map((access) => access.user.id)}
          onPick={(picked) =>
            add.mutate(
              { userId: picked.id },
              {
                onError,
                onSuccess: () => void addToSpaces({ userId: picked.id }),
              },
            )
          }
          onInviteEmail={(email) =>
            invite.mutate(
              { email },
              { onError, onSuccess: () => void addToSpaces({ email }) },
            )
          }
        />
      )}
      {canManage && invitations.length > 0 && (
        <Box>
          {invitations.map((invitation) => (
            <Row key={invitation.id}>
              <Box $direction="row" $align="center" $gap="xs" $flex={1}>
                <Icon
                  iconName="forward_to_inbox"
                  $size="20px"
                  $variation="secondary"
                />
                <Box $css="min-width: 0;">
                  <Text $size="sm" $ellipsis>
                    {invitation.email}
                  </Text>
                  <Text $size="xs" $variation="secondary">
                    {invitation.is_expired
                      ? t('Invitation expired', {
                          description: 'State of an invitation by email',
                        })
                      : t('Invited by email, not joined yet', {
                          description: 'State of an invitation by email',
                        })}
                  </Text>
                </Box>
              </Box>
              <Button
                size="small"
                variant="tertiary"
                onClick={() =>
                  invite.mutate(
                    { email: invitation.email, role: invitation.role },
                    { onError },
                  )
                }
              >
                {t('Send again', {
                  description: 'Button sending an invitation again',
                })}
              </Button>
              <IconButton
                icon="close"
                label={t('Cancel the invitation of {{email}}', {
                  description: 'Button cancelling an invitation by email',
                  email: invitation.email,
                })}
                onClick={() => cancel.mutate(invitation.id, { onError })}
              />
            </Row>
          ))}
        </Box>
      )}
      <Box>
        {accesses.map((access) => (
          <Row key={access.id}>
            <Box $flex={1}>
              <SearchUserRow user={access.user} />
            </Box>
            <Box $width="190px">
              <Select
                fullWidth
                label={t('Role', { description: 'Label of a role selector' })}
                hideLabel
                clearable={false}
                disabled={!canManage}
                options={roles}
                value={access.role}
                onChange={(event) =>
                  update.mutate(
                    {
                      accessId: access.id,
                      role: event.target.value as WorkspaceRole,
                    },
                    { onError },
                  )
                }
              />
            </Box>
            {(canManage || access.user.id === user?.id) && (
              <IconButton
                icon={access.user.id === user?.id ? 'logout' : 'close'}
                label={
                  access.user.id === user?.id
                    ? t('Leave the workspace', {
                        description: 'Button leaving a workspace',
                      })
                    : t('Remove {{name}}', {
                        description: 'Button removing a workspace member',
                        name: access.user.full_name || access.user.email,
                      })
                }
                onClick={() =>
                  remove.mutate({ accessId: access.id }, { onError })
                }
              />
            )}
          </Row>
        ))}
      </Box>
    </Section>
  );
};

// -- Groups

const GroupMembers = ({
  group,
  otherGroups,
  workspaceMemberIds,
}: {
  group: Group;
  /** The workspace's other groups, to move or copy people into */
  otherGroups: Group[];
  workspaceMemberIds: string[];
}) => {
  const { t } = useTranslation();
  const onError = useErrorToast();
  const { data: members = [] } = useGroupMembers(group.id);
  const { add, remove, update } = useGroupMemberMutations(group.id);
  const canManage = group.abilities.manage_members;
  const targets = otherGroups.filter((other) => other.abilities.manage_members);
  const canTransfer = canManage && targets.length > 0;
  const [selected, setSelected] = useState<string[]>([]);
  const [isMoving, setIsMoving] = useState(false);

  return (
    <Box
      $gap="xs"
      $padding={{ left: 'md', bottom: 'xs' }}
      className="--collaborators--group-members"
    >
      {canManage && (
        <UserPicker
          label={t('Add a workspace member to {{name}}', {
            description: 'Label of the search adding a group member',
            name: group.name,
          })}
          excludeIds={[
            ...members.map((member) => member.user.id),
            // Only workspace members can join its groups
          ]}
          onPick={(picked) => {
            if (!workspaceMemberIds.includes(picked.id)) {
              onError({
                cause: [
                  t('Add {{name}} to the workspace first.', {
                    description: 'Error adding a non-member to a group',
                    name: picked.full_name || picked.email,
                  }),
                ],
              });
              return;
            }
            add.mutate({ userId: picked.id }, { onError });
          }}
        />
      )}
      {members.length === 0 && (
        <Text $size="sm" $variation="secondary">
          {t('No member yet.', { description: 'Shown for an empty group' })}
        </Text>
      )}
      {canTransfer && members.length > 0 && (
        <Box $direction="row" $align="center" $gap="xs">
          <Button
            size="small"
            variant="secondary"
            disabled={!selected.length}
            icon={
              <Icon iconName="drive_file_move" $size="18px" $color="inherit" />
            }
            onClick={() => setIsMoving(true)}
          >
            {t('Move or copy ({{count}})', {
              description: 'Button moving chosen members to another group',
              count: selected.length,
            })}
          </Button>
          {!selected.length && (
            <Text $size="xs" $variation="secondary">
              {t('Tick people to move or copy them to another user group.', {
                description: 'Hint for moving members between groups',
              })}
            </Text>
          )}
        </Box>
      )}
      {members.map((member) => (
        <Row key={member.id}>
          {canTransfer && (
            <Checkbox
              aria-label={t('Choose {{name}}', {
                description: 'Checkbox choosing a group member',
                name: member.user.full_name || member.user.email,
              })}
              checked={selected.includes(member.user.id)}
              onChange={(event) =>
                setSelected((current) =>
                  event.target.checked
                    ? [...current, member.user.id]
                    : current.filter((id) => id !== member.user.id),
                )
              }
            />
          )}
          <Box $flex={1}>
            <SearchUserRow user={member.user} />
          </Box>
          {group.abilities.manage_managers ? (
            <Switch
              label={t('Manager', { description: 'Group manager badge' })}
              checked={member.is_manager}
              onChange={() =>
                update.mutate(
                  { membershipId: member.id, isManager: !member.is_manager },
                  { onError },
                )
              }
            />
          ) : (
            member.is_manager && (
              <Text $size="xs" $variation="secondary">
                {t('Manager', { description: 'Group manager badge' })}
              </Text>
            )
          )}
          {canManage && (
            <IconButton
              icon="close"
              label={t('Remove {{name}}', {
                description: 'Button removing a group member',
                name: member.user.full_name || member.user.email,
              })}
              onClick={() =>
                remove.mutate({ membershipId: member.id }, { onError })
              }
            />
          )}
        </Row>
      ))}
      {isMoving && (
        <MoveMembersModal
          group={group}
          targets={targets}
          userIds={selected}
          onDone={() => setSelected([])}
          onClose={() => setIsMoving(false)}
        />
      )}
    </Box>
  );
};

const GroupsSection = ({ workspace }: { workspace: Workspace }) => {
  const { t } = useTranslation();
  const onError = useErrorToast();
  const { data: groups = [] } = useGroups(workspace.id);
  const { data: accesses = [] } = useWorkspaceAccesses(workspace.id);
  const { create, remove } = useGroupMutations(workspace.id);
  const [name, setName] = useState('');
  const [kind, setKind] = useState<GroupKind>(GroupKind.TEAM);
  const [openGroupId, setOpenGroupId] = useState<string | null>(null);
  const [groupToDelete, setGroupToDelete] = useState<Group | null>(null);
  const canCreate = workspace.abilities.create_groups;
  const isAdmin = workspace.abilities.manage_groups;

  const kinds = [
    {
      value: GroupKind.TEAM,
      label: t('Team', { description: 'Group kind: people on a task' }),
    },
    {
      value: GroupKind.ORGANIZATION,
      label: t('Organization', {
        description: 'Group kind: a company or institution',
      }),
    },
  ];

  return (
    <Section
      title={t('User groups', { description: 'Heading of a list of groups' })}
      description={t(
        'Teams gather people working on a task; organizations gather the people of a company or institution. User groups can be given access to spaces and pages, and mentioned. Any member can create a team and manage it; administrators manage every user group.',
        { description: 'Explanation of workspace groups' },
      )}
    >
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
          {isAdmin && (
            <Box $width="190px">
              <Select
                fullWidth
                label={t('Kind', { description: 'Label of the group kind' })}
                clearable={false}
                options={kinds}
                value={kind}
                onChange={(event) => setKind(event.target.value as GroupKind)}
              />
            </Box>
          )}
          <Button
            disabled={!name.trim()}
            onClick={() =>
              create.mutate(
                { name: name.trim(), kind: isAdmin ? kind : GroupKind.TEAM },
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
                <Icon
                  iconName={
                    group.kind === GroupKind.ORGANIZATION ? 'domain' : 'groups'
                  }
                  $size="20px"
                  $variation="secondary"
                />
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
                workspaceMemberIds={accesses.map((access) => access.user.id)}
              />
            )}
          </Box>
        ))}
      </Box>
      {groupToDelete && (
        <ConfirmModal
          title={t('Delete {{name}}', {
            description: 'Button deleting a group',
            name: groupToDelete.name,
          })}
          message={t(
            'Delete the user group "{{name}}"? The access it gives to spaces and pages goes with it.',
            {
              description: 'Confirmation before deleting a group',
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
    </Section>
  );
};

// -- Spaces

/** A space shared into this workspace: its administrators grant their groups. */
const SharedSpaceGrants = ({
  space,
  workspace,
}: {
  space: Space;
  workspace: Workspace;
}) => {
  const { t } = useTranslation();
  const onError = useErrorToast();
  const { data: groups = [] } = useGroups(workspace.id);
  const { data: grants = [] } = useWorkspaceGrants(space.id);
  const { grant, revoke } = useWorkspaceGrantMutations(space.id);
  const [team, setTeam] = useState<string>('');
  const [role, setRole] = useState<string>(Role.READER);

  const teams = [
    {
      value: `workspace:${workspace.id}`,
      label: t('All members of {{name}}', {
        description: 'A grant to every member of a workspace',
        name: workspace.name,
      }),
    },
    ...groups.map((group) => ({ value: group.team, label: group.name })),
  ];
  const roles = [
    { value: Role.READER, label: t('Reader', { description: 'Role' }) },
    { value: 'commenter', label: t('Commenter', { description: 'Role' }) },
    { value: Role.EDITOR, label: t('Editor', { description: 'Role' }) },
  ];

  return (
    <Box $gap="xs" $padding={{ left: 'md', bottom: 'xs' }}>
      {grants.map((item) => (
        <Row key={item.team}>
          <Text $size="sm">{item.label}</Text>
          <Text $size="xs" $variation="secondary">
            {item.role}
          </Text>
          <IconButton
            icon="close"
            label={t('Revoke', { description: 'Button revoking a grant' })}
            onClick={() => revoke.mutate({ team: item.team }, { onError })}
          />
        </Row>
      ))}
      <Box $direction="row" $gap="sm" $align="flex-end">
        <Box $flex={1}>
          <Select
            fullWidth
            label={t('Give access to', {
              description: 'Label choosing a group to grant a space to',
            })}
            clearable={false}
            options={teams}
            value={team}
            onChange={(event) => setTeam(event.target.value as string)}
          />
        </Box>
        <Box $width="160px">
          <Select
            fullWidth
            label={t('Role', { description: 'Label of a role selector' })}
            clearable={false}
            options={roles}
            value={role}
            onChange={(event) => setRole(event.target.value as string)}
          />
        </Box>
        <Button
          disabled={!team}
          onClick={() => grant.mutate({ team, role }, { onError })}
        >
          {t('Grant', { description: 'Button granting access' })}
        </Button>
      </Box>
    </Box>
  );
};

/** A space this workspace owns: share it with another of my workspaces. */
const SpaceLinks = ({
  space,
  workspace,
}: {
  space: Space;
  workspace: Workspace;
}) => {
  const { t } = useTranslation();
  const onError = useErrorToast();
  const { data: workspaces = [] } = useWorkspaces();
  const { link, unlink } = useSpaceMutations(space.id);
  const [target, setTarget] = useState('');
  const linkedIds = space.linked_workspaces.map((item) => item.id);
  const candidates = workspaces
    .filter((item) => item.id !== workspace.id && !linkedIds.includes(item.id))
    .map((item) => ({ value: item.id, label: item.name }));

  return (
    <Box $gap="xs" $padding={{ left: 'md', bottom: 'xs' }}>
      {space.linked_workspaces
        .filter((item) => !item.is_home)
        .map((item) => (
          <Row key={item.id}>
            <Text $size="sm">
              {t('Shared with {{name}}', {
                description: 'A workspace a space is shared with',
                name: item.name,
              })}
            </Text>
            <IconButton
              icon="link_off"
              label={t('Stop sharing with {{name}}', {
                description: 'Button unlinking a space from a workspace',
                name: item.name,
              })}
              onClick={() =>
                unlink.mutate({ workspaceId: item.id }, { onError })
              }
            />
          </Row>
        ))}
      {candidates.length > 0 ? (
        <Box $direction="row" $gap="sm" $align="flex-end">
          <Box $flex={1}>
            <Select
              fullWidth
              label={t('Share with another workspace', {
                description: 'Label choosing a workspace to share a space with',
              })}
              clearable={false}
              options={candidates}
              value={target}
              onChange={(event) => setTarget(event.target.value as string)}
            />
          </Box>
          <Button
            disabled={!target}
            onClick={() =>
              link.mutate(
                { workspaceId: target },
                { onError, onSuccess: () => setTarget('') },
              )
            }
          >
            {t('Share', { description: 'Button sharing a space' })}
          </Button>
        </Box>
      ) : (
        <Text $size="xs" $variation="secondary">
          {t(
            'To share this space with another workspace, you need to be a member of it.',
            { description: 'Shown when no other workspace is available' },
          )}
        </Text>
      )}
    </Box>
  );
};

const SpacesSection = ({ workspace }: { workspace: Workspace }) => {
  const { t } = useTranslation();
  const { data: spaces = [] } = useSpaces({ workspaceId: workspace.id });
  const [openSpaceId, setOpenSpaceId] = useState<string | null>(null);
  const isAdmin = workspace.abilities.manage_groups;

  return (
    <Section
      title={t('Spaces', { description: 'Heading of the list of spaces' })}
      description={t(
        'Spaces owned by this workspace can be shared with other workspaces; their administrators then decide which of their user groups get access.',
        { description: 'Explanation of shared spaces' },
      )}
    >
      {spaces.length === 0 && (
        <Text $size="sm" $variation="secondary">
          {t('No space here yet. Create the first one with +.', {
            description: 'Shown when a workspace has no space',
          })}
        </Text>
      )}
      {spaces.map((space) => {
        const isHome = space.home_workspace?.id === workspace.id;
        return (
          <Box key={space.id}>
            <Row>
              <Box $direction="row" $align="center" $gap="xs" $flex={1}>
                <Icon iconName="folder" $size="20px" $variation="secondary" />
                <StyledLink href={`/space/${space.id}/`}>
                  <Text $weight="500">
                    {space.title ||
                      t('Untitled space', {
                        description: 'Name of a space without title',
                      })}
                  </Text>
                </StyledLink>
                {!isHome && (
                  <Text $size="xs" $variation="secondary">
                    {t('Shared from {{name}}', {
                      description:
                        'Shown under a space shared by another workspace',
                      name: space.home_workspace?.name,
                    })}
                  </Text>
                )}
              </Box>
              {isAdmin && (
                <IconButton
                  icon={openSpaceId === space.id ? 'expand_less' : 'tune'}
                  label={t('Sharing of {{name}}', {
                    description: 'Button showing the sharing of a space',
                    name: space.title,
                  })}
                  onClick={() =>
                    setOpenSpaceId(openSpaceId === space.id ? null : space.id)
                  }
                />
              )}
            </Row>
            {openSpaceId === space.id &&
              (isHome ? (
                <SpaceLinks space={space} workspace={workspace} />
              ) : (
                <SharedSpaceGrants space={space} workspace={workspace} />
              ))}
          </Box>
        );
      })}
    </Section>
  );
};

export const WorkspaceSettings = ({ workspaceId }: { workspaceId: string }) => {
  const { t } = useTranslation();
  const { data: workspaces, isFetched } = useWorkspaces();
  const workspace = workspaces?.find((item) => item.id === workspaceId);

  if (!isFetched) {
    return null;
  }

  if (!workspace) {
    return (
      <Text $padding="lg">
        {t('This workspace does not exist or you are not one of its members.', {
          description: 'Shown when a workspace settings page is not reachable',
        })}
      </Text>
    );
  }

  return (
    <Box
      $width="100%"
      $maxWidth={SCREEN_MAX_WIDTH}
      $margin={{ horizontal: 'auto' }}
      $padding={{ horizontal: 'md', vertical: 'lg' }}
      $gap="md"
      className="--collaborators--workspace-settings"
    >
      <Box $direction="row" $align="center" $gap="xs">
        <Icon iconName="workspaces" $size="28px" $variation="secondary" />
        <Text as="h1" $size="h4" $margin="none">
          {workspace.name}
        </Text>
      </Box>
      <GeneralSection workspace={workspace} />
      <MembersSection workspace={workspace} />
      <GroupsSection workspace={workspace} />
      <SpacesSection workspace={workspace} />
      <JoiningSection workspace={workspace} Section={Section} />
      <PublishingSection workspace={workspace} Section={Section} />
    </Box>
  );
};
