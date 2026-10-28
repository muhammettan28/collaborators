import { Button } from '@gouvfr-lasuite/ui-components';
import Head from 'next/head';
import { useRouter } from 'next/router';
import { useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { Box, Icon, Loading, Text } from '@/components';
import { PresentationFrame } from '@/docs/doc-editor/components/custom-blocks/presentation/PresentationFrame';
import {
  pdfWithZone,
  usePresentation,
} from '@/docs/doc-editor/components/custom-blocks/presentation/api';
import { gotoLogin, useAuth } from '@/features/auth';
import { NextPageWithLayout } from '@/types/next';

/**
 * Collaborators: a presentation on its own, filling the screen, at its
 * permanent address; for whoever reads its page.
 */
const Page: NextPageWithLayout = () => {
  const { t } = useTranslation();
  const {
    query: { id },
  } = useRouter();
  const { authenticated } = useAuth();
  const {
    data: presentation,
    error,
    isLoading,
  } = usePresentation(typeof id === 'string' ? id : '');
  const frame = useRef<HTMLDivElement>(null);

  return (
    <Box
      $height="100dvh"
      $width="100%"
      $css={css`
        background: var(--c--contextuals--background--surface--primary);
      `}
    >
      <Head>
        <title>
          {presentation?.title ||
            t('Presentation', {
              description: 'Name of the presentation block',
            })}
        </title>
        <meta name="robots" content="noindex" />
      </Head>
      {isLoading && <Loading />}
      {error && (
        <Box
          $align="center"
          $justify="center"
          $flex={1}
          $gap="sm"
          $padding="md"
        >
          <Text $textAlign="center">
            {t('This presentation was removed, or you can’t see it.', {
              description:
                'Shown in a presentation block whose presentation is gone',
            })}
          </Text>
          {!authenticated && (
            <Button onClick={() => gotoLogin()}>
              {t('Sign in', { description: 'Button leading to sign in' })}
            </Button>
          )}
        </Box>
      )}
      {presentation && (
        <>
          <Box
            $direction="row"
            $align="center"
            $gap="xs"
            $padding={{ horizontal: 'sm', vertical: 'xs' }}
            $wrap="wrap"
          >
            <Icon iconName="slideshow" $size="20px" />
            <Text
              $weight="600"
              $flex={1}
              $css="min-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"
            >
              {presentation.title}
            </Text>
            <Button
              size="small"
              variant="tertiary"
              href={`/page/${presentation.page.id}/`}
              icon={
                <Icon iconName="arrow_back" $size="18px" $color="inherit" />
              }
            >
              {t('Its page', {
                description: 'Button leading to the page a presentation is in',
              })}
            </Button>
            <Button
              size="small"
              variant="tertiary"
              onClick={() => void frame.current?.requestFullscreen?.()}
              icon={
                <Icon iconName="fullscreen" $size="18px" $color="inherit" />
              }
            >
              {t('Full screen', {
                description: 'Button showing a presentation full screen',
              })}
            </Button>
            <Button
              size="small"
              variant="secondary"
              href={pdfWithZone(presentation.pdf_url)}
              icon={
                <Icon iconName="picture_as_pdf" $size="18px" $color="inherit" />
              }
            >
              {t('Export to PDF', {
                description: 'Button downloading a presentation as a PDF',
              })}
            </Button>
          </Box>
          <Box $flex={1} $css="min-height: 0;">
            <PresentationFrame ref={frame} presentation={presentation} fill />
          </Box>
        </>
      )}
    </Box>
  );
};

export default Page;
