import { forwardRef, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { Box, Loading, Text } from '@/components';

import { TimeBar, useTimeline, withTimeline } from './TimeBar';
import { Presentation, usePresentationContent } from './api';
import { sealedDocument } from './sealedDocument';

export const ASPECT_RATIOS = {
  '16:9': '16 / 9',
  '4:3': '4 / 3',
  '1:1': '1 / 1',
} as const;

export type AspectRatio = keyof typeof ASPECT_RATIOS;

/**
 * A presentation and the bar under it (its time bar, or the buttons of its
 * slides): the bar is added below, the presentation keeps all its shape.
 * Full screen (or filling the page), the presentation takes what the bar
 * leaves.
 */
export const shownCss = (fill: boolean) => css`
  display: flex;
  flex-direction: column;
  width: 100%;
  ${fill ? 'height: 100%;' : ''}
  background: var(--c--contextuals--background--surface--tertiary);
  border-radius: ${fill ? '0' : '6px'};
  overflow: hidden;
  &:fullscreen {
    border-radius: 0;
  }
  &:fullscreen > [data-presentation-content] {
    flex: 1;
    min-height: 0;
    aspect-ratio: auto;
  }
`;

/** The presentation itself, in its shape */
export const contentCss = (aspectRatio: AspectRatio, fill: boolean) => css`
  position: relative;
  width: 100%;
  ${
    fill
      ? 'flex: 1; min-height: 0;'
      : `aspect-ratio: ${ASPECT_RATIOS[aspectRatio]};`
  }
`;

/** Once the element has come near the screen (then for good). */
const useNearScreen = () => {
  const ref = useRef<HTMLDivElement | null>(null);
  const [near, setNear] = useState(false);
  useEffect(() => {
    const element = ref.current;
    if (near || !element) {
      return;
    }
    if (typeof IntersectionObserver === 'undefined') {
      setNear(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNear(true);
        }
      },
      { rootMargin: '400px' },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [near]);
  return { ref, near };
};

interface PresentationFrameProps {
  presentation: Presentation;
  aspectRatio?: AspectRatio;
  /** Fill the space given (the full-screen page) instead of keeping a shape */
  fill?: boolean;
  /** Show the time bar of a measured animation, which then waits for Play */
  timeBar?: boolean;
  /** How long its animation lasts, once measured (0: it can't be) */
  onMeasured?: (seconds: number) => void;
}

/**
 * The presentation itself, in a sealed frame: its HTML is given to the frame
 * as text (`srcdoc`), in a sandbox that runs its scripts but keeps it from
 * the app — no access to the page, its cookies, its storage or the address
 * bar, no requests of its own (sealedDocument) — while readers click and
 * use the arrow keys in it. Loaded when it comes near the screen.
 */
export const PresentationFrame = forwardRef<
  HTMLDivElement,
  PresentationFrameProps
>(function PresentationFrame(
  { presentation, aspectRatio = '16:9', fill = false, timeBar, onMeasured },
  outerRef,
) {
  const { t } = useTranslation();
  const { ref, near } = useNearScreen();
  const iframe = useRef<HTMLIFrameElement>(null);
  const { timeline, send } = useTimeline(iframe);

  useEffect(() => {
    onMeasured?.(timeline.seconds);
  }, [timeline.seconds, onMeasured]);
  const { data, error, isLoading } = usePresentationContent(
    near && presentation.has_content ? presentation.id : '',
    presentation.updated_at,
  );

  const setRefs = (element: HTMLDivElement | null) => {
    ref.current = element;
    if (typeof outerRef === 'function') {
      outerRef(element);
    } else if (outerRef) {
      outerRef.current = element;
    }
  };

  const offline = typeof navigator !== 'undefined' && !navigator.onLine;

  return (
    <Box ref={setRefs} $css={shownCss(fill)} data-testid="presentation-frame">
      <Box $css={contentCss(aspectRatio, fill)} data-presentation-content>
        {data !== undefined ? (
          <iframe
            ref={iframe}
            title={presentation.title || t('Presentation')}
            srcDoc={withTimeline(
              sealedDocument(
                data,
                presentation.source === 'link' ? presentation.link : null,
              ),
              // with its time bar, it waits for the reader's Play
              Boolean(timeBar),
            )}
            // scripts run, in a sandbox of their own: no allow-same-origin
            sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox"
            allow="fullscreen"
            referrerPolicy="no-referrer"
            style={{
              width: '100%',
              height: '100%',
              border: 0,
              display: 'block',
              background: '#fff',
            }}
          />
        ) : (
          <Box $align="center" $justify="center" $height="100%" $padding="md">
            {isLoading && <Loading />}
            {!presentation.has_content && (
              <Text $variation="secondary" $textAlign="center">
                {t('This presentation is waiting for its file.', {
                  description:
                    'Shown in a presentation published by an AI assistant before its file was uploaded',
                })}
              </Text>
            )}
            {error && (
              <Text $variation="secondary" $textAlign="center">
                {offline
                  ? t('This presentation needs a connection.', {
                      description: 'Shown in a presentation while offline',
                    })
                  : error.message ||
                    t('This presentation can’t be shown right now.', {
                      description: 'Shown when a presentation fails to load',
                    })}
              </Text>
            )}
          </Box>
        )}
      </Box>
      {timeBar && data !== undefined && timeline.seconds > 0 && (
        <TimeBar timeline={timeline} send={send} />
      )}
    </Box>
  );
});
