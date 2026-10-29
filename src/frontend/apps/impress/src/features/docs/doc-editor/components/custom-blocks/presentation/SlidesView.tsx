import { forwardRef, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { Box, Icon, Loading, Text } from '@/components';

import { ASPECT_RATIOS, type AspectRatio } from './PresentationFrame';
import { Presentation, usePresentationSlides } from './api';

type PdfModule = typeof import('pdfjs-dist');
type PdfDocument = Awaited<ReturnType<PdfModule['getDocument']>['promise']>;

/**
 * pdf.js, loaded the first time slides are shown (it is big), with its
 * worker bundled as one (the build turns `new Worker(new URL(…))` into its
 * own file), shared by every slides view.
 */
const loadPdfjs = async (): Promise<PdfModule> => {
  const pdfjs = await import('pdfjs-dist');
  if (!pdfjs.GlobalWorkerOptions.workerPort) {
    pdfjs.GlobalWorkerOptions.workerPort = new Worker(
      new URL('./pdfWorker.ts', import.meta.url),
      { type: 'module' },
    );
  }
  return pdfjs;
};

const controlsCss = css`
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  & button {
    background: none;
    border: 0;
    color: inherit;
    cursor: pointer;
    display: flex;
    padding: 2px;
  }
  & button:disabled {
    opacity: 0.4;
    cursor: default;
  }
  & input {
    flex: 1;
    accent-color: #fff;
    min-width: 60px;
  }
`;

/**
 * The presentation's PDF twin, one page at a time: back and forward (the
 * arrow keys too), where one is, and a slider to jump anywhere. Its pages
 * are drawn by pdf.js, which runs no script of the file.
 */
export const SlidesView = forwardRef<
  HTMLDivElement,
  { presentation: Presentation; aspectRatio?: AspectRatio; fill?: boolean }
>(function SlidesView(
  { presentation, aspectRatio = '16:9', fill = false },
  ref,
) {
  const { t } = useTranslation();
  const { data, error } = usePresentationSlides(
    presentation.id,
    presentation.updated_at,
    presentation.pdf.state === 'current',
  );
  const [pdf, setPdf] = useState<PdfDocument | null>(null);
  const [failed, setFailed] = useState(false);
  const [page, setPage] = useState(1);
  const [width, setWidth] = useState(0);
  const canvas = useRef<HTMLCanvasElement>(null);
  const area = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!data) {
      return;
    }
    let cancelled = false;
    let loaded: PdfDocument | null = null;
    void (async () => {
      try {
        const pdfjs = await loadPdfjs();
        // a copy: pdf.js hands its bytes over to its worker
        loaded = await pdfjs.getDocument({
          data: new Uint8Array(data.slice(0)),
          isEvalSupported: false,
        }).promise;
        if (cancelled) {
          void loaded.destroy();
          return;
        }
        setPdf(loaded);
        // where the reader went while it loaded, if the PDF has it
        const pages = loaded.numPages;
        setPage((current) => Math.min(current, pages));
      } catch {
        if (!cancelled) {
          setFailed(true);
        }
      }
    })();
    return () => {
      cancelled = true;
      void loaded?.destroy();
    };
  }, [data]);

  // drawn again when the space it has changes
  useEffect(() => {
    const element = area.current;
    if (!element || typeof ResizeObserver === 'undefined') {
      return;
    }
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.round(entry.contentRect.width)),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!pdf || !canvas.current || !area.current) {
      return;
    }
    let task: { cancel: () => void; promise: Promise<void> } | null = null;
    let cancelled = false;
    void (async () => {
      const shown = await pdf.getPage(page);
      if (cancelled || !canvas.current || !area.current) {
        return;
      }
      const box = area.current.getBoundingClientRect();
      const natural = shown.getViewport({ scale: 1 });
      const fit = Math.min(
        box.width / natural.width,
        box.height / natural.height || Infinity,
      );
      const ratio = window.devicePixelRatio || 1;
      const viewport = shown.getViewport({ scale: fit * ratio });
      const target = canvas.current;
      target.width = Math.floor(viewport.width);
      target.height = Math.floor(viewport.height);
      target.style.width = `${Math.floor(viewport.width / ratio)}px`;
      target.style.height = `${Math.floor(viewport.height / ratio)}px`;
      task = shown.render({ canvas: target, viewport });
      await task.promise.catch(() => undefined);
    })();
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [pdf, page, width]);

  const total = pdf?.numPages ?? presentation.pdf.pages ?? 0;
  const go = (to: number) => setPage(Math.max(1, Math.min(total, to)));

  return (
    <Box
      ref={ref}
      $width="100%"
      $position="relative"
      $css={css`
        ${fill ? 'height: 100%;' : `aspect-ratio: ${ASPECT_RATIOS[aspectRatio]};`}
        background: var(--c--contextuals--background--surface--tertiary);
        border-radius: ${fill ? '0' : '6px'};
        overflow: hidden;
      `}
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'ArrowRight' || event.key === 'PageDown') {
          event.preventDefault();
          go(page + 1);
        } else if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
          event.preventDefault();
          go(page - 1);
        }
      }}
      data-testid="presentation-slides"
    >
      <Box
        ref={area}
        $position="absolute"
        $align="center"
        $justify="center"
        $css="inset: 0 0 32px 0;"
      >
        {pdf ? (
          <canvas
            ref={canvas}
            aria-label={t('Slide {{page}} of {{total}}', {
              description:
                'The slide shown in the Slides tab of a presentation',
              page,
              total,
            })}
          />
        ) : error || failed ? (
          <Text $variation="secondary" $textAlign="center">
            {t('The slides can’t be shown right now.', {
              description: 'Shown when the PDF of a presentation fails to load',
            })}
          </Text>
        ) : (
          <Loading />
        )}
      </Box>
      <Box
        $direction="row"
        $align="center"
        $gap="xs"
        $padding={{ horizontal: 'xs', vertical: '2px' }}
        $css={controlsCss}
      >
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => go(page - 1)}
          aria-label={t('Previous slide', {
            description: 'Button showing the previous slide',
          })}
        >
          <Icon iconName="chevron_left" $size="20px" $color="inherit" />
        </button>
        <button
          type="button"
          disabled={page >= total}
          onClick={() => go(page + 1)}
          aria-label={t('Next slide', {
            description: 'Button showing the next slide',
          })}
        >
          <Icon iconName="chevron_right" $size="20px" $color="inherit" />
        </button>
        <input
          type="range"
          min={1}
          max={Math.max(1, total)}
          step={1}
          value={page}
          aria-label={t('Slide', {
            description: 'Label of the slider moving through the slides',
          })}
          onChange={(event) => go(Number(event.target.value))}
        />
        <Text
          $size="xs"
          $color="inherit"
          $css="font-variant-numeric: tabular-nums;"
        >
          {page} / {total}
        </Text>
      </Box>
    </Box>
  );
});
