import { forwardRef, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { Box, Icon, Loading, Text } from '@/components';

import { type AspectRatio, contentCss, shownCss } from './PresentationFrame';
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
  flex-shrink: 0;
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
  & select {
    background: transparent;
    color: inherit;
    border: 1px solid rgba(255, 255, 255, 0.4);
    border-radius: 4px;
    font-size: 12px;
    padding: 0 2px;
  }
  & option {
    color: #000;
  }
`;

/** How long each slide shows while they play, to choose from */
const SECONDS = [1, 2, 3, 5, 10, 15, 30];
const DEFAULT_SECONDS = 3;

/**
 * The presentation's PDF twin, one page at a time: first, back, play or
 * pause, forward and last (the arrow keys, Home and End too), where one is,
 * and how many seconds each slide shows while they play (3 by default). Its
 * pages are drawn by pdf.js, which runs no script of the file.
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
  const [playing, setPlaying] = useState(false);
  const [seconds, setSeconds] = useState(DEFAULT_SECONDS);
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

  // while it plays, the next slide after its seconds; it stops on the last
  useEffect(() => {
    if (!playing || !pdf) {
      return;
    }
    if (page >= total) {
      setPlaying(false);
      return;
    }
    const timer = setTimeout(
      () => setPage((current) => Math.min(total, current + 1)),
      seconds * 1000,
    );
    return () => clearTimeout(timer);
  }, [playing, pdf, page, total, seconds]);

  const togglePlay = () => {
    if (playing) {
      setPlaying(false);
      return;
    }
    // played to its end, it starts again from the first
    if (page >= total) {
      setPage(1);
    }
    setPlaying(true);
  };

  return (
    <Box
      ref={ref}
      $css={shownCss(fill)}
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === 'ArrowRight' || event.key === 'PageDown') {
          event.preventDefault();
          go(page + 1);
        } else if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
          event.preventDefault();
          go(page - 1);
        } else if (event.key === 'Home') {
          event.preventDefault();
          go(1);
        } else if (event.key === 'End') {
          event.preventDefault();
          go(total);
        }
      }}
      data-testid="presentation-slides"
    >
      <Box
        ref={area}
        $align="center"
        $justify="center"
        $css={contentCss(aspectRatio, fill)}
        data-presentation-content
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
        $justify="center"
        $gap="xs"
        $padding={{ horizontal: 'xs', vertical: '2px' }}
        $css={controlsCss}
        data-testid="presentation-slides-controls"
      >
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => go(1)}
          aria-label={t('First slide', {
            description: 'Button showing the first slide',
          })}
        >
          <Icon iconName="first_page" $size="20px" $color="inherit" />
        </button>
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
          disabled={total <= 1}
          onClick={togglePlay}
          aria-label={
            playing
              ? t('Pause the slides', {
                  description: 'Button stopping the slides from moving on',
                })
              : t('Play the slides', {
                  description:
                    'Button moving on to the next slide every few seconds',
                })
          }
        >
          <Icon
            iconName={playing ? 'pause' : 'play_arrow'}
            $size="20px"
            $color="inherit"
          />
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
        <button
          type="button"
          disabled={page >= total}
          onClick={() => go(total)}
          aria-label={t('Last slide', {
            description: 'Button showing the last slide',
          })}
        >
          <Icon iconName="last_page" $size="20px" $color="inherit" />
        </button>
        <Text
          $size="xs"
          $color="inherit"
          $css="font-variant-numeric: tabular-nums; min-width: 3.5em;"
        >
          {page} / {total}
        </Text>
        <select
          value={seconds}
          onChange={(event) => setSeconds(Number(event.target.value))}
          aria-label={t('Seconds per slide', {
            description:
              'Label of the choice of how long each slide shows while they play',
          })}
        >
          {SECONDS.map((choice) => (
            <option key={choice} value={choice}>
              {t('{{seconds}} s', {
                description: 'A number of seconds, short: "3 s"',
                seconds: choice,
              })}
            </option>
          ))}
        </select>
      </Box>
    </Box>
  );
});
