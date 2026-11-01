import {
  Button,
  Input,
  Select,
  Switch,
  VariantType,
  useToastProvider,
} from '@gouvfr-lasuite/ui-components';
import { ReactNode, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { Box, BoxButton, Icon, Text } from '@/components';
import { useClipboard } from '@/hooks';

import {
  useAnswerJoinRequest,
  useGroups,
  useJoinLinkMutations,
  useJoinRequests,
  useUpdateWorkspace,
} from '../api';
import { Organization, Workspace } from '../types';

type SectionProps = {
  title: string;
  description?: ReactNode;
  children: ReactNode;
};

const SubHeading = ({ children }: { children: ReactNode }) => (
  <Text as="h3" $size="sm" $weight="700" $margin="none">
    {children}
  </Text>
);

/** A removable pill, for a join domain or organisation. */
const Chip = ({
  label,
  removeLabel,
  onRemove,
}: {
  label: string;
  removeLabel: string;
  onRemove: () => void;
}) => (
  <Box
    $direction="row"
    $align="center"
    $gap="3xs"
    $padding={{ left: 'xs', right: '3xs', vertical: '4xs' }}
    $css={css`
      border-radius: 999px;
      border: 1px solid var(--c--contextuals--border--surface--primary);
    `}
  >
    <Text $size="sm">{label}</Text>
    <BoxButton aria-label={removeLabel} $padding="4xs" onClick={onRemove}>
      <Icon iconName="close" $size="16px" $variation="secondary" />
    </BoxButton>
  </Box>
);

/**
 * Workspace settings: joining without an invitation, by a join link, by the
 * domain of a verified email address or by an organisation (Google
 * Workspace, Microsoft tenant), into an organisation group; and, when the
 * admins approve who joins, the people waiting for their answer.
 */
export const JoiningSection = ({
  workspace,
  Section,
}: {
  workspace: Workspace;
  Section: (props: SectionProps) => ReactNode;
}) => {
  const { t } = useTranslation();
  const { toast } = useToastProvider();
  const copyToClipboard = useClipboard();
  const [domain, setDomain] = useState('');
  const { mutate: updateWorkspace, isPending } = useUpdateWorkspace();
  const { renew, remove } = useJoinLinkMutations(workspace.id);
  const { data: groups = [] } = useGroups(workspace.id);
  const isAdmin = workspace.abilities.update;
  const { data: requests = [] } = useJoinRequests(
    workspace.id,
    isAdmin && workspace.join_approval,
  );
  const answer = useAnswerJoinRequest(workspace.id);

  if (!isAdmin) {
    return null;
  }

  const onError = (error?: { cause?: string[] }) =>
    toast(
      error?.cause?.[0] ??
        t('Something went wrong.', { description: 'Generic error message' }),
      VariantType.ERROR,
    );
  const link = workspace.join_token
    ? `${window.location.origin}/join/${workspace.join_token}/`
    : null;
  const organizationLabel = (organization: Organization) =>
    organization.id.startsWith('google:')
      ? t('Google Workspace {{name}}', {
          description: 'A Google Workspace organisation, by its domain',
          name: organization.name,
        })
      : t('Microsoft organisation {{name}}', {
          description: 'A Microsoft (Entra ID) organisation, by its domain',
          name: organization.name,
        });
  const setOrganizations = (ids: string[]) =>
    updateWorkspace({ id: workspace.id, join_organizations: ids }, { onError });
  const addableOrganizations = workspace.join_organization_choices.filter(
    (choice) =>
      !workspace.join_organizations.some((item) => item.id === choice.id),
  );
  const setDomains = (domains: string[]) =>
    updateWorkspace(
      { id: workspace.id, join_domains: domains },
      { onError, onSuccess: () => setDomain('') },
    );

  return (
    <Section
      title={t('Joining', {
        description: 'Heading of how people join a workspace',
      })}
      description={t(
        'People join by signing in: with a link you give them, or automatically when their verified email is at your organisation’s domain or they sign in with your organisation’s Google or Microsoft account.',
        { description: 'Explanation of joining a workspace' },
      )}
    >
      <Box $gap="xs">
        <Switch
          labelSide="right"
          label={t('Admins approve each person who joins', {
            description: 'Switch making joiners wait for an admin',
          })}
          checked={workspace.join_approval}
          disabled={isPending}
          onChange={() =>
            updateWorkspace(
              { id: workspace.id, join_approval: !workspace.join_approval },
              { onError },
            )
          }
        />
        <Text $size="xs" $variation="secondary">
          {t(
            'Joining by link, domain or organisation then sends you a request to approve.',
            { description: 'Explanation of approving who joins' },
          )}
        </Text>
        {workspace.join_approval && requests.length > 0 && (
          <Box
            as="ul"
            data-testid="join-requests"
            $css={css`
              list-style: none;
              margin: 0;
              padding: 0;
              border: 1px solid var(--c--contextuals--border--surface--primary);
              border-radius: var(--c--globals--spacings--xs);
              & > li + li {
                border-top: 1px solid
                  var(--c--contextuals--border--surface--primary);
              }
            `}
          >
            {requests.map((item) => (
              <Box
                as="li"
                key={item.id}
                $direction="row"
                $align="center"
                $justify="space-between"
                $gap="sm"
                $padding={{ horizontal: 'sm', vertical: 'xs' }}
                $css="flex-wrap: wrap;"
              >
                <Box $css="min-width: 0; flex: 1 1 10rem;">
                  <Text $weight="600" $ellipsis>
                    {item.user.full_name || item.user.email}
                  </Text>
                  <Text $size="xs" $variation="secondary" $ellipsis>
                    {item.user.email}
                    {' · '}
                    {item.via === 'link'
                      ? t('by the join link', {
                          description: 'How a request to join was made',
                        })
                      : item.via === 'domain'
                        ? t('by email domain', {
                            description: 'How a request to join was made',
                          })
                        : item.via === 'directory'
                          ? t('from Discover workspaces', {
                              description: 'How a request to join was made',
                            })
                          : t('by organisation', {
                              description: 'How a request to join was made',
                            })}
                  </Text>
                </Box>
                <Box $direction="row" $gap="xs">
                  <Button
                    size="small"
                    disabled={answer.isPending}
                    onClick={() =>
                      answer.mutate(
                        { id: item.id, decision: 'approve' },
                        { onError },
                      )
                    }
                  >
                    {t('Approve', {
                      description: 'Button letting someone join a workspace',
                    })}
                  </Button>
                  <Button
                    size="small"
                    variant="secondary"
                    disabled={answer.isPending}
                    onClick={() =>
                      answer.mutate(
                        { id: item.id, decision: 'decline' },
                        { onError },
                      )
                    }
                  >
                    {t('Decline', {
                      description: 'Button declining a request to join',
                    })}
                  </Button>
                </Box>
              </Box>
            ))}
          </Box>
        )}
      </Box>

      <Box $gap="xs">
        <SubHeading>
          {t('Join link', { description: 'Workspace join link' })}
        </SubHeading>
        {link ? (
          <>
            <Box
              $direction="row"
              $align="center"
              $gap="xs"
              $padding={{ horizontal: 'xs', vertical: '3xs' }}
              $css={css`
                border-radius: var(--c--globals--spacings--3xs);
                background: var(
                  --c--contextuals--background--semantic--contextual--primary
                );
              `}
            >
              <Icon iconName="link" $size="18px" $variation="secondary" />
              <Text $size="sm" $ellipsis $css="flex: 1; min-width: 0;">
                {link}
              </Text>
              <BoxButton
                aria-label={t('Copy the join link', {
                  description: 'Button copying the join link',
                })}
                title={t('Copy the join link', {
                  description: 'Button copying the join link',
                })}
                $padding="3xs"
                onClick={() =>
                  copyToClipboard(
                    link,
                    t('Link Copied !', {
                      description:
                        'Toast confirming a link was copied to the clipboard',
                    }),
                    t('Failed to copy link', {
                      description: 'Toast shown when copying a link failed',
                    }),
                  )
                }
              >
                <Icon
                  iconName="content_copy"
                  $size="18px"
                  $variation="secondary"
                />
              </BoxButton>
            </Box>
            <Text $size="xs" $variation="secondary">
              {t('Anyone with this link can join as a member once signed in.', {
                description: 'Explanation of the join link',
              })}
            </Text>
            <Box $direction="row" $gap="xs">
              <Button
                size="small"
                variant="secondary"
                onClick={() => renew.mutate(undefined, { onError })}
              >
                {t('New link', {
                  description: 'Button replacing the join link',
                })}
              </Button>
              <Button
                size="small"
                variant="secondary"
                color="error"
                onClick={() => remove.mutate(undefined, { onError })}
              >
                {t('Turn off', { description: 'Button turning a link off' })}
              </Button>
            </Box>
          </>
        ) : (
          <Box $direction="row">
            <Button
              size="small"
              variant="secondary"
              icon={<Icon iconName="add_link" $size="18px" $color="inherit" />}
              onClick={() => renew.mutate(undefined, { onError })}
            >
              {t('Create a join link', {
                description: 'Button creating a workspace join link',
              })}
            </Button>
          </Box>
        )}
      </Box>

      <Box $gap="xs">
        <SubHeading>
          {t('Joining by email domain', {
            description: 'Workspace joining by domain',
          })}
        </SubHeading>
        <Text $size="xs" $variation="secondary">
          {t(
            'Use the domain of your own verified email. Addresses anyone can get (Gmail, Outlook…) can’t be used.',
            { description: 'Rules of joining by domain' },
          )}
        </Text>
        {workspace.join_domains.length > 0 && (
          <Box $direction="row" $gap="2xs" $css="flex-wrap: wrap;">
            {workspace.join_domains.map((item) => (
              <Chip
                key={item}
                label={`@${item}`}
                removeLabel={t('Remove {{domain}}', {
                  description: 'Button removing a join domain',
                  domain: item,
                })}
                onRemove={() =>
                  setDomains(
                    workspace.join_domains.filter((other) => other !== item),
                  )
                }
              />
            ))}
          </Box>
        )}
        <Box $direction="row" $gap="sm" $align="flex-end">
          <Box $flex={1}>
            <Input
              fullWidth
              label={t('Domain, e.g. acme.org', {
                description: 'Label of the join domain field',
              })}
              value={domain}
              onChange={(event) => setDomain(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && domain.trim()) {
                  setDomains([...workspace.join_domains, domain.trim()]);
                }
              }}
            />
          </Box>
          <Button
            disabled={!domain.trim() || isPending}
            onClick={() =>
              setDomains([...workspace.join_domains, domain.trim()])
            }
          >
            {t('Add', { description: 'Button adding a join domain' })}
          </Button>
        </Box>
      </Box>

      <Box $gap="xs">
        <SubHeading>
          {t('Joining by organisation', {
            description: 'Workspace joining by Google Workspace or Microsoft',
          })}
        </SubHeading>
        <Text $size="xs" $variation="secondary">
          {t(
            'Everyone who signs in with an account of your Google Workspace or Microsoft organisation joins. You can add the organisations you signed in with yourself.',
            { description: 'Rules of joining by organisation' },
          )}
        </Text>
        {workspace.join_organizations.length > 0 && (
          <Box $direction="row" $gap="2xs" $css="flex-wrap: wrap;">
            {workspace.join_organizations.map((item) => (
              <Chip
                key={item.id}
                label={organizationLabel(item)}
                removeLabel={t('Remove {{name}}', {
                  description: 'Button removing a join organisation',
                  name: organizationLabel(item),
                })}
                onRemove={() =>
                  setOrganizations(
                    workspace.join_organizations
                      .filter((other) => other.id !== item.id)
                      .map((other) => other.id),
                  )
                }
              />
            ))}
          </Box>
        )}
        {addableOrganizations.length > 0 ? (
          <Box $direction="row" $gap="xs" $css="flex-wrap: wrap;">
            {addableOrganizations.map((item) => (
              <Button
                key={item.id}
                size="small"
                variant="secondary"
                disabled={isPending}
                icon={<Icon iconName="add" $size="18px" $color="inherit" />}
                onClick={() =>
                  setOrganizations([
                    ...workspace.join_organizations.map((other) => other.id),
                    item.id,
                  ])
                }
              >
                {organizationLabel(item)}
              </Button>
            ))}
          </Box>
        ) : (
          workspace.join_organizations.length === 0 && (
            <Text $size="xs" $variation="secondary">
              {t(
                'Sign in with a Google Workspace or Microsoft work account to offer your organisation here.',
                { description: 'No organisation to offer for joining' },
              )}
            </Text>
          )
        )}
      </Box>

      <Box $gap="xs">
        <Select
          fullWidth
          label={t('Also add them to the user group', {
            description: 'Label of the organisation group of joiners',
          })}
          clearable={false}
          options={[
            {
              label: t('No user group', {
                description: 'No organisation group',
              }),
              value: '',
            },
            ...groups.map((group) => ({ label: group.name, value: group.id })),
          ]}
          value={workspace.join_group ?? ''}
          onChange={(event) =>
            updateWorkspace(
              {
                id: workspace.id,
                join_group: (event.target.value as string) || null,
              },
              { onError },
            )
          }
        />
      </Box>
    </Section>
  );
};
