import {
  Button,
  VariantType,
  useToastProvider,
} from '@gouvfr-lasuite/ui-components';
import { useQueryClient } from '@tanstack/react-query';
import Head from 'next/head';
import { useRouter } from 'next/router';
import { useEffect, useRef, useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { Box, Icon, Loading, Text } from '@/components';
import { Title } from '@/components/Title';
import { useConfig } from '@/core';
import {
  KEY_AUTH,
  gotoLogout,
  gotoProviderLogin,
  setAuthUrl,
  useAuth,
} from '@/features/auth';
import { Footer } from '@/features/footer';
import {
  InvitationBundleCard,
  KIND_ICONS,
} from '@/features/invitations/InvitationBundleCard';
import {
  invitationLogoUrl,
  isInvitationBundle,
  useAcceptInvitation,
  useInvitationInfo,
} from '@/features/invitations/api';
import { ProviderLogo } from '@/features/signin/ProviderLogo';
import { PROVIDER_NAMES } from '@/features/signin/SignIn';
import { useWorkspaceStore } from '@/features/workspaces/stores/useWorkspaceStore';
import { useResponsiveStore } from '@/stores';
import { NextPageWithLayout } from '@/types/next';
import { safeSessionStorage } from '@/utils/storages';

/** Set when leaving to sign in from here: accept once back, signed in. */
const ACCEPT_AFTER_SIGN_IN = 'collaborators-accept-invitation';

/**
 * /invite/?token=…: where an invitation by email leads. It shows what one is
 * invited to (its logo and name) and the ways to sign up or sign in; signed
 * in, it accepts the invitation and opens what it was for.
 * Collaborators: the link of invitations sent together lists them all.
 */
const Page: NextPageWithLayout = () => {
  const { t } = useTranslation();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { toast } = useToastProvider();
  const { isSmallMobile } = useResponsiveStore();
  const token =
    typeof router.query.token === 'string' ? router.query.token : '';
  const { data, isLoading, isError, refetch } = useInvitationInfo(token);
  const bundle = data && isInvitationBundle(data) ? data : undefined;
  const info = data && !isInvitationBundle(data) ? data : undefined;
  const { user, authenticated, isAuthLoading } = useAuth();
  const { data: config } = useConfig();
  const accept = useAcceptInvitation();
  const { setCurrentWorkspaceId } = useWorkspaceStore();
  const [logoFailed, setLogoFailed] = useState(false);
  const tried = useRef(false);
  const providers = config?.COLLABORATORS_SIGNIN_PROVIDERS ?? [];
  const withPassword = !!config?.COLLABORATORS_SIGNIN_PASSWORD;

  const onError = () =>
    toast(
      t('The invitation could not be accepted.', {
        description: 'Toast when accepting an invitation failed',
      }),
      VariantType.ERROR,
    );

  const onAccept = () =>
    accept.mutate(token, {
      onSuccess: async (result) => {
        // The newcomer is let in: who they are is read again
        await queryClient.invalidateQueries({ queryKey: [KEY_AUTH] });
        if (result.kind === 'workspace') {
          setCurrentWorkspaceId(result.id);
          void router.replace(`/workspace/${result.id}/`);
        } else {
          void router.replace(
            result.kind === 'space'
              ? `/space/${result.id}/`
              : `/page/${result.id}/`,
          );
        }
      },
      onError,
    });

  // Invitations sent together: one (its token) or all (the link's), then
  // the list shows what they open
  const onAcceptInBundle = (acceptToken = token) =>
    accept.mutate(acceptToken, {
      onSuccess: async () => {
        await queryClient.invalidateQueries({ queryKey: [KEY_AUTH] });
        await refetch();
      },
      onError,
    });

  // Back from signing in for this invitation: accept it straight away.
  // Collaborators: already used by the one signed in (a newcomer's account
  // takes their invitations when it is made): open what it was to
  useEffect(() => {
    if (
      bundle &&
      !tried.current &&
      authenticated &&
      safeSessionStorage.getItem(ACCEPT_AFTER_SIGN_IN) === token
    ) {
      tried.current = true;
      safeSessionStorage.removeItem(ACCEPT_AFTER_SIGN_IN);
      onAcceptInBundle();
      return;
    }
    if (
      tried.current ||
      !authenticated ||
      !info ||
      info.is_expired ||
      (!info.is_accepted &&
        safeSessionStorage.getItem(ACCEPT_AFTER_SIGN_IN) !== token)
    ) {
      return;
    }
    tried.current = true;
    safeSessionStorage.removeItem(ACCEPT_AFTER_SIGN_IN);
    onAccept();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authenticated, info, bundle, token]);

  const signInWith = (provider?: string) => {
    safeSessionStorage.setItem(ACCEPT_AFTER_SIGN_IN, token);
    setAuthUrl();
    gotoProviderLogin(provider);
  };

  const what = info
    ? {
        workspace: t('the workspace', {
          description: 'Invited to a workspace',
        }),
        space: t('the space', { description: 'Invited to a space' }),
        page: t('the page', { description: 'Invited to a page' }),
      }[info.kind]
    : '';
  const title = t('Invitation', { description: 'Title of the invite page' });

  const signedInAs = (
    <Text $size="xs" $variation="secondary" $textAlign="center">
      <Trans
        i18nKey="Signed in as <strong>{{email}}</strong>."
        values={{ email: user?.email ?? '' }}
        tOptions={{
          description: 'Who accepts, on the invite page',
        }}
        components={{ strong: <strong /> }}
      />{' '}
      <Box
        as="button"
        type="button"
        onClick={() => gotoLogout()}
        $display="inline"
        $css={css`
          border: none;
          background: none;
          padding: 0;
          color: var(--c--contextuals--content--semantic--brand--primary);
          text-decoration: underline;
          cursor: pointer;
          font: inherit;
        `}
      >
        {t('Not you?', {
          description: 'Link signing out on the invite page',
        })}
      </Box>
    </Text>
  );

  const signIn = (
    <Box $gap="xs" $width="100%">
      <Text $size="sm" $textAlign="center">
        {t('Sign up or sign in to join: you will be in right away.', {
          description: 'Invite page, signed out',
        })}
      </Text>
      {providers.map((provider) => (
        <Button
          key={provider}
          fullWidth
          variant="secondary"
          icon={<ProviderLogo provider={provider} />}
          onClick={() => signInWith(provider)}
          data-testid={`invite-${provider}`}
        >
          {t('Continue with {{provider}}', {
            description: 'Button signing in with an identity provider',
            provider: PROVIDER_NAMES[provider] ?? provider,
          })}
        </Button>
      ))}
      {withPassword && (
        <Button fullWidth variant="tertiary" onClick={() => signInWith()}>
          {t('Use a test account', {
            description:
              'Button signing in with a development account and password',
          })}
        </Button>
      )}
      <Text $size="xs" $variation="secondary" $textAlign="center">
        {t(
          'No password to remember: an account you already have signs you in. The first time, it creates your Collaborators account.',
          { description: 'Explanation under the sign-in buttons' },
        )}
      </Text>
    </Box>
  );

  return (
    <>
      <Head>
        <title>{`${title} - Collaborators`}</title>
      </Head>
      <Box as="main" $minHeight="100vh" $css="overflow-y: auto;">
        <Box
          $flex={1}
          $align="center"
          $justify="center"
          $gap="lg"
          $padding={{
            horizontal: isSmallMobile ? 'sm' : 'lg',
            vertical: 'lg',
          }}
        >
          <Title headingLevel="h2" $size={isSmallMobile ? '1.6rem' : '2rem'} />
          {(isLoading || isAuthLoading) && <Loading />}
          {(isError || (!token && !isLoading)) && (
            <Text $variation="secondary" $textAlign="center" $maxWidth="420px">
              {t(
                'This invitation can no longer be used: it was accepted, cancelled or its link is incomplete.',
                { description: 'Invite page for an unknown invitation' },
              )}
            </Text>
          )}
          {info && (
            <Box
              $align="center"
              $gap="md"
              $width="100%"
              $maxWidth="420px"
              $padding="lg"
              data-testid="invitation-card"
              $css={css`
                border: 1px solid
                  var(--c--contextuals--border--surface--primary);
                border-radius: var(--c--globals--spacings--sm);
                background: var(--c--contextuals--background--surface--primary);
              `}
            >
              <Box
                $width="96px"
                $height="96px"
                $align="center"
                $justify="center"
                $css={css`
                  overflow: hidden;
                  border-radius: var(--c--globals--spacings--sm);
                  background: var(
                    --c--contextuals--background--semantic--brand--tertiary
                  );
                `}
              >
                {info.has_logo && !logoFailed ? (
                  <img
                    src={invitationLogoUrl(token)}
                    alt=""
                    width={96}
                    height={96}
                    style={{ objectFit: 'contain' }}
                    onError={() => setLogoFailed(true)}
                  />
                ) : (
                  <Icon
                    iconName={KIND_ICONS[info.kind]}
                    $size="48px"
                    $theme="brand"
                  />
                )}
              </Box>
              <Box $align="center" $gap="2xs">
                <Text $size="sm" $variation="secondary" $textAlign="center">
                  {info.issuer
                    ? t('{{name}} invited you to join {{what}}', {
                        description: 'Who invites, on the invite page',
                        name: info.issuer,
                        what,
                      })
                    : t('You are invited to join {{what}}', {
                        description: 'Invite page without an inviter',
                        what,
                      })}
                </Text>
                <Text
                  as="h1"
                  $size="h4"
                  $weight="700"
                  $margin="none"
                  $textAlign="center"
                >
                  {info.name ||
                    t('Untitled page', {
                      description: 'Name of a page without title',
                    })}
                </Text>
                {info.description && (
                  <Text $size="sm" $variation="secondary" $textAlign="center">
                    {info.description}
                  </Text>
                )}
              </Box>

              {info.is_expired ? (
                <Text $variation="secondary" $textAlign="center">
                  {t(
                    'This invitation has expired: ask {{name}} for a new one.',
                    {
                      description: 'Invite page for an expired invitation',
                      name: info.issuer || '…',
                    },
                  )}
                </Text>
              ) : authenticated ? (
                <Box $gap="xs" $width="100%" $align="center">
                  {/* Collaborators: signed in as someone else than the one
                      invited (the inviter, say, in the same browser) */}
                  {!info.is_accepted &&
                    !!info.email &&
                    !!user?.email &&
                    info.email.toLowerCase() !== user.email.toLowerCase() && (
                      <Text
                        $size="sm"
                        $textAlign="center"
                        data-testid="invitation-other-email"
                      >
                        <Trans
                          i18nKey="This invitation was sent to <strong>{{invited}}</strong>. To accept it with that address, use “Not you?” below, then sign in with it."
                          values={{ invited: info.email }}
                          tOptions={{
                            description:
                              'Invite page, signed in with another email than the invited one',
                          }}
                          components={{ strong: <strong /> }}
                        />
                      </Text>
                    )}
                  <Button
                    fullWidth
                    disabled={accept.isPending}
                    onClick={onAccept}
                  >
                    {t('Accept and join', {
                      description: 'Button accepting an invitation',
                    })}
                  </Button>
                  {signedInAs}
                </Box>
              ) : (
                signIn
              )}
            </Box>
          )}
          {bundle && (
            <InvitationBundleCard
              bundle={bundle}
              authenticated={authenticated}
              userEmail={user?.email}
              isPending={accept.isPending}
              onAccept={onAcceptInBundle}
              signIn={signIn}
              signedInAs={signedInAs}
            />
          )}
        </Box>
        <Footer />
      </Box>
    </>
  );
};

export default Page;
