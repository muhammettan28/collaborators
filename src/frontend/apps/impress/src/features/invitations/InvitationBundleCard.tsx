import { Button } from '@gouvfr-lasuite/ui-components';
import { useRouter } from 'next/router';
import { ReactNode, useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { Box, Icon, Text } from '@/components';
import { useWorkspaceStore } from '@/features/workspaces/stores/useWorkspaceStore';

import {
  BundledInvitation,
  InvitationBundleInfo,
  InvitationInfo,
  invitationLogoUrl,
} from './api';

export const KIND_ICONS: Record<InvitationInfo['kind'], string> = {
  workspace: 'workspaces',
  space: 'folder',
  page: 'description',
};

const cardStyle = css`
  border: 1px solid var(--c--contextuals--border--surface--primary);
  border-radius: var(--c--globals--spacings--sm);
  background: var(--c--contextuals--background--surface--primary);
`;

const BundledLogo = ({ invitation }: { invitation: BundledInvitation }) => {
  const [failed, setFailed] = useState(false);
  return (
    <Box
      $width="40px"
      $height="40px"
      $align="center"
      $justify="center"
      $css={css`
        flex-shrink: 0;
        overflow: hidden;
        border-radius: var(--c--globals--spacings--3xs);
        background: var(
          --c--contextuals--background--semantic--brand--tertiary
        );
      `}
    >
      {invitation.has_logo && invitation.token && !failed ? (
        <img
          src={invitationLogoUrl(invitation.token)}
          alt=""
          width={40}
          height={40}
          style={{ objectFit: 'contain' }}
          onError={() => setFailed(true)}
        />
      ) : (
        <Icon
          iconName={KIND_ICONS[invitation.kind]}
          $size="22px"
          $theme="brand"
        />
      )}
    </Box>
  );
};

interface InvitationBundleCardProps {
  bundle: InvitationBundleInfo;
  authenticated: boolean;
  userEmail?: string;
  isPending: boolean;
  /** Accepts one invitation (its token), or all (the bundle's token) */
  onAccept: (token?: string) => void;
  /** The ways to sign up or sign in, when signed out */
  signIn: ReactNode;
  /** Who is signed in, with "Not you?" */
  signedInAs: ReactNode;
}

/**
 * The invitations someone sent the same person within a few minutes, as
 * their one email links to them: each with its logo and role, to accept
 * one by one or all at once; those accepted open what they were to.
 */
export const InvitationBundleCard = ({
  bundle,
  authenticated,
  userEmail,
  isPending,
  onAccept,
  signIn,
  signedInAs,
}: InvitationBundleCardProps) => {
  const { t } = useTranslation();
  const router = useRouter();
  const { setCurrentWorkspaceId } = useWorkspaceStore();
  const waiting = bundle.invitations.filter(
    (invitation) => !invitation.is_accepted && !invitation.is_expired,
  );
  const kindLabels: Record<InvitationInfo['kind'], string> = {
    workspace: t('Workspace', { description: 'Kind of an invitation' }),
    space: t('Space', { description: 'Kind of an invitation' }),
    page: t('Page', { description: 'Kind of an invitation' }),
  };

  const open = (invitation: BundledInvitation) => {
    if (!invitation.id) {
      return;
    }
    if (invitation.kind === 'workspace') {
      setCurrentWorkspaceId(invitation.id);
      void router.push(`/workspace/${invitation.id}/`);
    } else {
      void router.push(`/${invitation.kind}/${invitation.id}/`);
    }
  };

  return (
    <Box
      $gap="md"
      $width="100%"
      $maxWidth="480px"
      $padding="lg"
      data-testid="invitation-bundle"
      $css={cardStyle}
    >
      <Text as="h1" $size="h5" $weight="700" $margin="none" $textAlign="center">
        {bundle.issuer
          ? t('{{name}} invited you to join', {
              description: 'Heading of the page of invitations sent together',
              name: bundle.issuer,
            })
          : t('You are invited to join', {
              description:
                'Heading of the page of invitations sent together, without an inviter',
            })}
      </Text>

      <Box as="ul" $gap="xs" $margin="none" $padding="none" role="list">
        {bundle.invitations.map((invitation, index) => (
          <Box
            as="li"
            key={invitation.token ?? invitation.id ?? index}
            $direction="row"
            $align="center"
            $gap="sm"
            data-testid="bundled-invitation"
            $css={css`
              list-style: none;
            `}
          >
            <BundledLogo invitation={invitation} />
            <Box $flex={1} $css="min-width: 0;">
              <Text $weight="600" $css="overflow-wrap: anywhere;">
                {invitation.name ||
                  t('Untitled page', {
                    description: 'Name of a page without title',
                  })}
              </Text>
              <Text $size="xs" $variation="secondary">
                {invitation.role
                  ? t('{{kind}} · as {{role}}', {
                      description:
                        'Kind and role of one of the invitations sent together',
                      kind: kindLabels[invitation.kind],
                      role: invitation.role,
                    })
                  : kindLabels[invitation.kind]}
              </Text>
            </Box>
            {invitation.is_accepted ? (
              <Button
                size="small"
                variant="tertiary"
                onClick={() => open(invitation)}
              >
                {t('Open', {
                  description: 'Button opening an accepted invitation',
                })}
              </Button>
            ) : invitation.is_expired ? (
              <Text $size="xs" $variation="secondary">
                {t('Expired', {
                  description: 'One of the invitations sent together expired',
                })}
              </Text>
            ) : (
              authenticated &&
              waiting.length > 1 && (
                <Button
                  size="small"
                  variant="secondary"
                  disabled={isPending}
                  onClick={() => onAccept(invitation.token)}
                >
                  {t('Accept', {
                    description: 'Button accepting one of the invitations',
                  })}
                </Button>
              )
            )}
          </Box>
        ))}
      </Box>

      {waiting.length === 0 ? (
        <Text $size="sm" $variation="secondary" $textAlign="center">
          {bundle.invitations.some((invitation) => invitation.is_accepted)
            ? t('You are in: open each of them above.', {
                description: 'Every invitation sent together was accepted',
              })
            : t('These invitations have expired: ask {{name}} for new ones.', {
                description: 'Every invitation sent together expired',
                name: bundle.issuer || '…',
              })}
        </Text>
      ) : authenticated ? (
        <Box $gap="xs" $width="100%" $align="center">
          {!!bundle.email &&
            !!userEmail &&
            bundle.email.toLowerCase() !== userEmail.toLowerCase() && (
              <Text
                $size="sm"
                $textAlign="center"
                data-testid="invitation-other-email"
              >
                <Trans
                  i18nKey="These invitations were sent to <strong>{{invited}}</strong>. To accept them with that address, use “Not you?” below, then sign in with it."
                  values={{ invited: bundle.email }}
                  tOptions={{
                    description:
                      'Page of invitations sent together, signed in with another email than the invited one',
                  }}
                  components={{ strong: <strong /> }}
                />
              </Text>
            )}
          <Button fullWidth disabled={isPending} onClick={() => onAccept()}>
            {waiting.length > 1
              ? t('Accept all and join', {
                  description:
                    'Button accepting all the invitations sent together',
                })
              : t('Accept and join', {
                  description: 'Button accepting an invitation',
                })}
          </Button>
          {signedInAs}
        </Box>
      ) : (
        signIn
      )}
    </Box>
  );
};
