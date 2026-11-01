import { chromium, type Browser, type Page } from 'playwright-core';

import { config } from './config.js';
import { sealedDocument } from './frame.js';
import { isAllowedRequest } from './network.js';

/** What a presentation gave: one picture per slide, or a printed PDF. */
export type Capture =
  | { kind: 'slides'; slides: Buffer[] }
  | { kind: 'pdf'; pdf: Buffer };

let browser: Promise<Browser> | null = null;

/** One browser for every PDF, started at the first and again if it dies. */
const getBrowser = (): Promise<Browser> => {
  if (!browser) {
    browser = chromium
      .launch({
        executablePath: config.chromiumPath,
        // In a container without the user namespaces Chromium's own sandbox
        // needs. What a presentation can reach is limited by the sealed
        // document's rules and by the request filter below instead.
        args: ['--no-sandbox', '--disable-dev-shm-usage', '--hide-scrollbars'],
      })
      .then((started) => {
        started.on('disconnected', () => {
          browser = null;
        });
        return started;
      })
      .catch((err: unknown) => {
        browser = null;
        throw err;
      });
  }
  return browser;
};

export const closeBrowser = async () => {
  const running = browser;
  browser = null;
  if (running) {
    await (await running).close();
  }
};

const settle = async (page: Page, ms: number) => {
  await page.waitForTimeout(ms);
  await page.evaluate(() => document.fonts?.ready).catch(() => undefined);
};

/**
 * Draw a presentation and capture it. Slides are stepped through as a
 * reader would, with the right arrow key, a picture of each, until the
 * picture stops changing (the last slide), the slide limit or the time
 * limit. Pictures are taken with CSS animations stilled, so a transition
 * never makes two pictures of one slide.
 *
 * A page that keeps changing on its own (an animation played by script) is
 * not stepped through: every picture would differ. It is captured once.
 * Either way, a page that scrolls (slides one below the other) and has a
 * single picture is printed instead, one screen per page.
 */
export const capture = async (
  html: string,
  baseUrl?: string | null,
): Promise<Capture> => {
  const started = Date.now();
  const context = await (
    await getBrowser()
  ).newContext({
    viewport: { width: config.width, height: config.height },
    deviceScaleFactor: 1.5,
    serviceWorkers: 'block',
    acceptDownloads: false,
  });
  try {
    const page = await context.newPage();
    await page.route('**/*', async (route) => {
      const allowed = await isAllowedRequest(route.request().url()).catch(
        () => false,
      );
      await (allowed ? route.continue() : route.abort('blockedbyclient'));
    });
    page.on('dialog', (dialog) => void dialog.dismiss());
    await page.setContent(sealedDocument(html, baseUrl), {
      waitUntil: 'load',
      timeout: 30_000,
    });
    await settle(page, 1500);

    const picture = () =>
      page.screenshot({ type: 'jpeg', quality: 85, animations: 'disabled' });

    const first = await picture();
    await settle(page, 1000);
    const movesOnItsOwn = !(await picture()).equals(first);

    const slides: Buffer[] = [first];
    let previous = first;
    while (
      !movesOnItsOwn &&
      slides.length < config.maxSlides &&
      Date.now() - started < config.renderTimeoutMs
    ) {
      await page.keyboard.press('ArrowRight');
      await settle(page, 700);
      const shot = await picture();
      if (shot.equals(previous)) {
        break;
      }
      slides.push(shot);
      previous = shot;
    }

    if (slides.length === 1) {
      const scrolls = await page.evaluate(
        () =>
          document.documentElement.scrollHeight > window.innerHeight * 1.2,
      );
      if (scrolls) {
        await page.keyboard.press('Home');
        const pdf = await page.pdf({
          width: `${config.width}px`,
          height: `${config.height}px`,
          printBackground: true,
          margin: { top: '0', right: '0', bottom: '0', left: '0' },
        });
        return { kind: 'pdf', pdf: Buffer.from(pdf) };
      }
    }
    return { kind: 'slides', slides };
  } finally {
    await context.close();
  }
};
