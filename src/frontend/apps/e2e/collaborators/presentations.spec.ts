import { readFileSync } from 'node:fs';
import path from 'node:path';

import { type Page, expect, test } from '@playwright/test';
import { PDFParse } from 'pdf-parse';

/**
 * The presentation block of Collaborators, from the slash menu to the PDF.
 * See README.md next to this file for what it needs and how to run it.
 */

const APP = process.env.BASE_URL ?? 'http://localhost:3000';
const API = process.env.BASE_API_URL ?? 'http://localhost:8071/api/v1.0';
const DECKS = path.join(__dirname, 'decks');
/** A public HTML file, to show a presentation from a link */
const LINK =
  process.env.PRESENTATION_LINK ??
  'https://raw.githubusercontent.com/mustafa-yilmaz/collaborators/main/demo.html';

test.describe.configure({ mode: 'serial' });

let pageId = '';
let presentationId = '';

const csrf = async (page: Page) =>
  (await page.context().cookies()).find((cookie) => cookie.name === 'csrftoken')
    ?.value ?? '';

const api = async (
  page: Page,
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE',
  url: string,
  data?: unknown,
) =>
  page.request.fetch(`${API}/${url}`, {
    method,
    data,
    headers: { 'X-CSRFToken': await csrf(page), Referer: APP },
  });

const pdfText = async (body: Buffer) => {
  const parser = new PDFParse({ data: body });
  const { text, total } = await parser.getText();
  await parser.destroy();
  return { text, total };
};

/** The seeded e2e account, through the local Keycloak. */
const signIn = async (page: Page) => {
  await page.goto(`${APP}/signin/`);
  await page.getByRole('button', { name: 'Use a test account' }).click();
  await page
    .getByRole('textbox', { name: 'username' })
    .fill('user-e2e-chromium');
  await page
    .getByRole('textbox', { name: 'password' })
    .fill('password-e2e-chromium');
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/(home\/)?(\?.*)?$/, { timeout: 60_000 });
};

/** Past the first visit's welcome, in editing mode. */
const openPage = async (page: Page, edit = true, id = pageId) => {
  await page.goto(`${APP}/page/${id}/`);
  await expect(page.locator('.ProseMirror').first()).toBeVisible({
    timeout: 60_000,
  });
  const skip = page.getByRole('button', { name: 'Skip' });
  if (await skip.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await skip.click();
  }
  if (edit) {
    await page.getByText('Editing', { exact: true }).click();
  }
};

const frame = (page: Page) =>
  page.frameLocator('[data-testid="presentation-frame"] iframe').first();

const openMenu = async (page: Page) => {
  await page
    .getByTestId('presentation-block')
    .first()
    .getByRole('button', { name: 'Presentation options' })
    .click();
};

test('an editor adds, reads, replaces and exports a presentation', async ({
  page,
}) => {
  await signIn(page);

  // a page of one's own
  const created = await api(page, 'POST', 'documents/', {
    title: 'E2E presentations',
  });
  expect(created.status(), await created.text()).toBe(201);
  pageId = ((await created.json()) as { id: string }).id;
  await openPage(page);
  const editor = page.locator('.ProseMirror').first();

  // "/presentation" in the slash menu
  await editor.click();
  await page.keyboard.type('/presentation');
  await expect(
    page.getByText('An HTML presentation readers click through'),
  ).toBeVisible();
  await page.keyboard.press('Enter');
  const setup = page.getByTestId('presentation-setup');
  await expect(setup).toBeVisible();
  await expect(setup.getByText(/You use [\d.]+ MB of your/)).toBeVisible();

  // upload an HTML file
  const upload = page.waitForResponse(
    (response) =>
      response.url().endsWith('/presentations/') &&
      response.request().method() === 'POST',
  );
  await setup
    .locator('input[type="file"]')
    .setInputFiles(path.join(DECKS, 'deck-a.html'));
  const response = await upload;
  expect(response.status()).toBe(201);
  presentationId = ((await response.json()) as { id: string }).id;

  // readers click through it, sealed from the app
  const deck = frame(page);
  await expect(deck.getByText('A · Slide 1')).toBeVisible({ timeout: 30_000 });
  await expect(deck.locator('#probe')).toHaveText(
    'parent:blocked cookie:blocked storage:blocked api:blocked',
    { timeout: 15_000 },
  );
  await expect(
    page.locator('[data-testid="presentation-frame"] iframe').first(),
  ).toHaveAttribute(
    'sandbox',
    'allow-scripts allow-popups allow-popups-to-escape-sandbox',
  );
  await deck.locator('body').click();
  await expect(deck.getByText('A · Slide 2')).toBeVisible();
  await page.keyboard.press('ArrowRight');
  await expect(deck.getByText('A · Slide 3')).toBeVisible();
  await expect(page.getByText('E2E deck A', { exact: true })).toBeVisible();

  // the title is kept in the block, for exports and search
  await expect
    .poll(
      async () => {
        const content = await api(
          page,
          'GET',
          `documents/${pageId}/formatted-content/?content_format=markdown`,
        );
        return content.ok() ? await content.text() : '';
      },
      { timeout: 30_000 },
    )
    .toContain('E2E deck A');

  // Export to PDF: the slides, with the dated page second
  const href = await page
    .getByRole('link', { name: 'Export to PDF' })
    .getAttribute('href');
  expect(href).toContain(`/presentations/${presentationId}/pdf/?tz=`);
  const pdf = await page.request.get(
    `${API}/presentations/${presentationId}/pdf/?tz=Europe%2FIstanbul`,
    { timeout: 180_000 },
  );
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()['content-disposition']).toContain('E2E%20deck%20A');
  const { text, total } = await pdfText(await pdf.body());
  expect(total).toBe(4);
  expect(text).toContain('Downloaded on');
  expect(text).toContain('(Europe/Istanbul)');
  expect(text).toContain('E2E presentations');
  expect(text.replace(/\s+/g, '')).toContain(
    `/api/v1.0/presentations/${presentationId}/pdf/`,
  );

  // replace with another file: same address, new content
  await openMenu(page);
  const chooser = page.waitForEvent('filechooser');
  await page.getByText('Replace with another file').click();
  await (await chooser).setFiles(path.join(DECKS, 'deck-b.html'));
  await expect(frame(page).getByText('B · Slide 1')).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText('E2E deck B', { exact: true })).toBeVisible();

  // earlier versions: show the first one again
  await openMenu(page);
  await page.getByText('Earlier versions').click();
  await expect(page.getByText('Shown now')).toBeVisible();
  await page.getByRole('button', { name: 'Show this one' }).click();
  await expect(frame(page).getByText('A · Slide 1')).toBeVisible({
    timeout: 30_000,
  });
  await page.getByRole('button', { name: 'Close' }).click();

  // rename
  const block = page.getByTestId('presentation-block').first();
  await openMenu(page);
  await page.getByText('Rename', { exact: true }).click();
  await block.getByLabel('Title').fill('Renamed deck');
  await block.getByRole('button', { name: 'Rename' }).click();
  await expect(page.getByText('Renamed deck', { exact: true })).toBeVisible();

  // shape 4:3
  await openMenu(page);
  await page.getByText('Shape 4:3').click();
  await expect
    .poll(async () => {
      const box = await page
        .getByTestId('presentation-frame')
        .first()
        .boundingBox();
      return box ? Math.round((box.width / box.height) * 100) / 100 : 0;
    })
    .toBe(1.33);

  // show it from a link instead
  await openMenu(page);
  await page.getByText('Show it from a link instead').click();
  // clicked first, as a person does: a fill right as the menu closes is lost
  const linkInput = block.getByLabel('Link to an HTML file (https://…)');
  await linkInput.click();
  await linkInput.fill(LINK);
  await expect(linkInput).toHaveValue(LINK);
  await block.getByRole('button', { name: 'Show it' }).click();
  await expect(page.getByText(`Shown from ${LINK}`)).toBeVisible({
    timeout: 30_000,
  });
  await expect(frame(page).locator('body')).not.toBeEmpty({ timeout: 30_000 });
  const linked = (await (
    await api(page, 'GET', `presentations/${presentationId}/`)
  ).json()) as { source: string };
  expect(linked.source).toBe('link');
  // its stored files stay listed, to show one again
  await openMenu(page);
  await page.getByText('Earlier versions').click();
  await expect(page.getByRole('button', { name: 'Show this one' })).toHaveCount(
    2,
  );
  await page.getByRole('button', { name: 'Close' }).click();

  // the full-screen page
  const view = await page.context().newPage();
  await view.goto(`${APP}/presentation/${presentationId}/`);
  await expect(view.getByRole('link', { name: 'Its page' })).toBeVisible({
    timeout: 60_000,
  });
  await expect(
    view
      .frameLocator('[data-testid="presentation-frame"] iframe')
      .locator('body'),
  ).not.toBeEmpty({ timeout: 30_000 });
  await view.close();
});

test('pasting its address shows it again; readers see it without the menu', async ({
  page,
  browser,
}) => {
  await signIn(page);
  await openPage(page);
  const blocks = page.getByTestId('presentation-block');
  await expect(blocks).toHaveCount(1, { timeout: 30_000 });

  // paste its address at the end of the page
  await page.locator('.ProseMirror').first().click();
  await page.keyboard.press('ControlOrMeta+End');
  await page.evaluate((text) => {
    const data = new DataTransfer();
    data.setData('text/plain', text);
    document
      .querySelector('.ProseMirror')
      ?.dispatchEvent(
        new ClipboardEvent('paste', { clipboardData: data, bubbles: true }),
      );
  }, `${APP}/presentation/${presentationId}/`);
  await expect(blocks).toHaveCount(2, { timeout: 15_000 });

  // the page made public: a signed-out reader sees it, without the menu
  const shared = await api(
    page,
    'PUT',
    `documents/${pageId}/link-configuration/`,
    { link_reach: 'public', link_role: 'reader' },
  );
  expect(shared.status(), await shared.text()).toBe(200);
  const anonymous = await browser.newContext();
  const reader = await anonymous.newPage();
  await reader.goto(`${APP}/page/${pageId}/`);
  await expect(reader.getByTestId('presentation-block').first()).toBeVisible({
    timeout: 60_000,
  });
  await expect(
    reader.getByRole('link', { name: 'Export to PDF' }).first(),
  ).toBeVisible();
  await expect(
    reader.getByRole('button', { name: 'Presentation options' }),
  ).toHaveCount(0);
  const pdf = await reader.request.get(
    `${API}/presentations/${presentationId}/pdf/`,
    { timeout: 180_000 },
  );
  expect(pdf.status()).toBe(200);
  await anonymous.close();
});

test('presenter mode shows it in its slide', async ({ page }) => {
  await signIn(page);
  await openPage(page, false);
  // no click into the page first: it may land in the slides, which keep
  // the keys; the shortcut is that of Desktop Chrome, on Windows
  await page.keyboard.press('Control+Alt+KeyP');
  const presenter = page.getByLabel('Presenter mode');
  await expect(presenter).toBeVisible({ timeout: 15_000 });
  // the title slide, then the page's content with its presentation
  await page.keyboard.press('ArrowRight');
  await expect(
    presenter.locator('[data-testid="presentation-frame"] iframe').first(),
  ).toBeVisible({ timeout: 30_000 });
  await page.keyboard.press('Escape');
});

test('removing it frees the storage, and the blocks say so', async ({
  page,
}) => {
  await signIn(page);
  const storage = async () =>
    (await (await api(page, 'GET', 'presentations/storage/')).json()) as {
      used: number;
      presentations: { id: string; size: number }[];
    };
  const before = await storage();
  // what the presentation in the page holds (its stored versions)
  const held =
    before.presentations.find((entry) => entry.id === presentationId)?.size ??
    0;
  expect(held).toBeGreaterThan(0);

  // another one stored, then removed through the API
  const file = '<title>Q</title><p>q</p>';
  const added = await page.request.post(`${API}/presentations/`, {
    multipart: {
      document: pageId,
      file: {
        name: 'q.html',
        mimeType: 'text/html',
        buffer: Buffer.from(file),
      },
    },
    headers: { 'X-CSRFToken': await csrf(page), Referer: APP },
  });
  expect(added.status(), await added.text()).toBe(201);
  expect((await storage()).used).toBe(before.used + file.length);
  const addedId = ((await added.json()) as { id: string }).id;
  expect(
    (await api(page, 'DELETE', `presentations/${addedId}/`)).status(),
  ).toBe(204);

  // the one in the page, removed from its menu
  await openPage(page);
  await openMenu(page);
  await page.getByText('Remove the presentation').click();
  await page.getByRole('button', { name: 'Remove', exact: true }).click();
  // its block goes; the other block showing it says it was removed
  await expect(page.getByTestId('presentation-block')).toHaveCount(1, {
    timeout: 15_000,
  });
  await expect(
    page.getByText('This presentation was removed, or you can’t see it.'),
  ).toBeVisible({ timeout: 30_000 });
  expect(
    (await api(page, 'GET', `presentations/${presentationId}/`)).status(),
  ).toBe(404);
  expect((await storage()).used).toBe(before.used - held);
});

/** A page of one's own, open for editing, with an empty presentation block. */
const newPresentationBlock = async (page: Page, title: string) => {
  const created = await api(page, 'POST', 'documents/', { title });
  expect(created.status(), await created.text()).toBe(201);
  const id = ((await created.json()) as { id: string }).id;
  await openPage(page, true, id);
  await page.locator('.ProseMirror').first().click();
  await page.keyboard.type('/presentation');
  await page.keyboard.press('Enter');
  const setup = page.getByTestId('presentation-setup');
  await expect(setup).toBeVisible();
  return { id, setup };
};

/** A deck printed the way an AI makes its PDF twin: one slide per page. */
const printed = async (page: Page, file: string) => {
  const printer = await page.context().newPage();
  await printer.goto(`file://${path.join(DECKS, file)}`);
  const pdf = await printer.pdf({
    width: '1280px',
    height: '720px',
    printBackground: true,
  });
  await printer.close();
  return pdf;
};

test('a presentation with its PDF: slides, its own PDF, kept in step', async ({
  page,
}) => {
  await signIn(page);
  await page
    .context()
    .grantPermissions(['clipboard-read', 'clipboard-write'], { origin: APP });
  const { id, setup } = await newPresentationBlock(page, 'E2E twin');

  // the instructions to give to one's AI
  await setup.getByRole('button', { name: 'Copy these instructions' }).click();
  await expect(
    setup.getByRole('button', { name: 'Copied: paste them to your AI' }),
  ).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(
    'window.collaboratorsTimeline',
  );

  // the HTML and its PDF, picked together
  const twin = await printed(page, 'twin.html');
  const upload = page.waitForResponse(
    (response) =>
      response.url().endsWith('/presentations/') &&
      response.request().method() === 'POST',
  );
  await setup.locator('input[type="file"]').setInputFiles([
    {
      name: 'twin.html',
      mimeType: 'text/html',
      buffer: readFileSync(path.join(DECKS, 'twin.html')),
    },
    { name: 'twin.pdf', mimeType: 'application/pdf', buffer: twin },
  ]);
  const made = (await (await upload).json()) as {
    id: string;
    pdf: { state: string; pages: number };
  };
  expect(made.pdf).toMatchObject({ state: 'current', pages: 3 });

  // Motion first; the Slides tab pages through the PDF
  const motion = page.getByRole('tab', { name: 'Motion' });
  await expect(motion).toHaveAttribute('aria-selected', 'true');
  await expect(frame(page).getByText('Twin slide 1')).toBeVisible({
    timeout: 30_000,
  });
  await page.getByRole('tab', { name: 'Slides' }).click();
  const slides = page.getByTestId('presentation-slides');
  await expect(slides.getByLabel('Slide 1 of 3')).toBeVisible({
    timeout: 30_000,
  });
  await slides.getByRole('button', { name: 'Next slide' }).click();
  await expect(slides.getByText('2 / 3')).toBeVisible();
  await slides.getByRole('button', { name: 'Last slide' }).click();
  await expect(slides.getByLabel('Slide 3 of 3')).toBeVisible();
  await slides.press('ArrowLeft');
  await expect(slides.getByText('2 / 3')).toBeVisible();
  await slides.getByRole('button', { name: 'First slide' }).click();
  await expect(slides.getByText('1 / 3')).toBeVisible();

  // played, they move on by themselves (3 seconds each unless chosen) and
  // stop on the last; played again, they start from the first
  const seconds = slides.getByRole('combobox', { name: 'Seconds per slide' });
  await expect(seconds).toHaveValue('3');
  await seconds.selectOption('1');
  await slides.getByRole('button', { name: 'Play the slides' }).click();
  await expect(slides.getByText('2 / 3')).toBeVisible({ timeout: 3_000 });
  await expect(slides.getByText('3 / 3')).toBeVisible({ timeout: 3_000 });
  await expect(
    slides.getByRole('button', { name: 'Play the slides' }),
  ).toBeVisible();
  await seconds.selectOption('5');
  await slides.getByRole('button', { name: 'Play the slides' }).click();
  await expect(slides.getByText('1 / 3')).toBeVisible();
  await slides.getByRole('button', { name: 'Pause the slides' }).click();
  await page.waitForTimeout(1_500);
  await expect(slides.getByText('1 / 3')).toBeVisible();
  await slides.getByRole('button', { name: 'Next slide' }).click();
  await expect(slides.getByText('2 / 3')).toBeVisible();

  // a click in it doesn't tint the whole block, as a selected block would be
  await slides.click({ position: { x: 40, y: 40 } });
  await expect
    .poll(() =>
      page
        .locator('.bn-block-content[data-content-type="presentation"] > *')
        .first()
        .evaluate((element) => getComputedStyle(element, '::after').content),
    )
    .toBe('none');

  // Export to PDF gives the twin itself, with the dated page second
  const pdf = await page.request.get(
    `${API}/presentations/${made.id}/pdf/?tz=Europe%2FIstanbul`,
    { timeout: 60_000 },
  );
  expect(pdf.status()).toBe(200);
  const exported = await pdfText(await pdf.body());
  expect(exported.total).toBe(4);
  expect(exported.text).toContain('Twin slide 1');
  expect(exported.text).toContain('Twin slide 3');
  expect(exported.text).toContain('Downloaded on');

  // the editor opens it on its slides
  await openMenu(page);
  await page.getByText('Open on the Slides tab').click();
  await expect
    .poll(async () => {
      await openPage(page, false, id);
      return page
        .getByRole('tab', { name: 'Slides' })
        .getAttribute('aria-selected');
    })
    .toBe('true');

  // a new file without its PDF: out of date, no slides, until it comes
  await openPage(page, true, id);
  await openMenu(page);
  const chooser = page.waitForEvent('filechooser');
  await page.getByText('Replace with another file').click();
  await (await chooser).setFiles(path.join(DECKS, 'deck-b.html'));
  const outdated = page.getByTestId('presentation-pdf-outdated');
  await expect(outdated).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('tab', { name: 'Slides' })).toHaveCount(0);
  const pdfChooser = page.waitForEvent('filechooser');
  await outdated.getByRole('button', { name: 'Add its PDF' }).click();
  await (
    await pdfChooser
  ).setFiles({
    name: 'b.pdf',
    mimeType: 'application/pdf',
    buffer: await printed(page, 'deck-b.html'),
  });
  await expect(outdated).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByRole('tab', { name: 'Slides' })).toBeVisible();
});

test('an animation gets a time bar when its editor turns it on', async ({
  page,
}) => {
  await signIn(page);
  const { setup } = await newPresentationBlock(page, 'E2E animation');
  await setup
    .locator('input[type="file"]')
    .setInputFiles(path.join(DECKS, 'animation.html'));
  await expect(frame(page).getByText('Growing')).toBeVisible({
    timeout: 30_000,
  });

  // off by default; offered once measured
  const bar = page.getByTestId('presentation-time-bar');
  await expect(bar).toHaveCount(0);
  await expect
    .poll(
      async () => {
        await openMenu(page);
        const offered = await page.getByText('Show the time bar').isVisible();
        await page.keyboard.press('Escape');
        return offered;
      },
      { timeout: 15_000 },
    )
    .toBe(true);
  await openMenu(page);
  await page.getByText('Show the time bar').click();
  await expect(bar).toBeVisible();
  await expect(bar.getByText('/ 0:06')).toBeVisible();

  // paused, then moved to its middle: the animation is there
  const pause = bar.getByRole('button', { name: 'Pause' });
  if (await pause.isVisible()) {
    await pause.click();
  }
  // a click in the slider's middle, as a person does (fill() sets the value
  // without the events React listens to)
  const slider = bar.getByRole('slider', { name: 'Time in the animation' });
  const box = (await slider.boundingBox())!;
  await slider.click({ position: { x: box.width / 2, y: box.height / 2 } });
  await expect(bar.getByText(/^0:0[23] \/ 0:06$/)).toBeVisible();
  const width = () =>
    frame(page)
      .locator('#bar')
      .evaluate((element) => element.getBoundingClientRect().width);
  await expect.poll(width).toBeGreaterThan(260);
  expect(await width()).toBeLessThan(340);
  await bar.getByRole('button', { name: 'Play' }).click();
  await expect(bar.getByText('0:06 / 0:06')).toBeVisible({ timeout: 10_000 });
  await expect.poll(width).toBeGreaterThan(590);
});

test('a script-driven animation moves with its handle, at its own time', async ({
  page,
}) => {
  await signIn(page);
  const { setup } = await newPresentationBlock(page, 'E2E script animation');
  await setup
    .locator('input[type="file"]')
    .setInputFiles(path.join(DECKS, 'script-animation.html'));
  await expect(frame(page).getByText('Moving')).toBeVisible({
    timeout: 30_000,
  });
  await expect
    .poll(
      async () => {
        await openMenu(page);
        const offered = await page.getByText('Show the time bar').isVisible();
        await page.keyboard.press('Escape');
        return offered;
      },
      { timeout: 15_000 },
    )
    .toBe(true);
  await openMenu(page);
  await page.getByText('Show the time bar').click();
  const bar = page.getByTestId('presentation-time-bar');
  await expect(bar.getByText('/ 0:05')).toBeVisible();

  // the bar says where the file is, though its clock started late
  const slider = bar.getByRole('slider', { name: 'Time in the animation' });
  const fileTime = () =>
    frame(page)
      .locator('body')
      .evaluate(
        () =>
          (window as unknown as { collaboratorsTimeline: { time: number } })
            .collaboratorsTimeline.time,
      );
  await bar.getByRole('button', { name: 'Pause' }).click();
  await expect(bar.getByRole('button', { name: 'Play' })).toBeVisible();
  await expect
    .poll(async () =>
      Math.abs(Number(await slider.inputValue()) - (await fileTime())),
    )
    .toBeLessThan(0.3);

  // moved to its middle, then played to its end, where it stops
  const box = (await slider.boundingBox())!;
  await slider.click({ position: { x: box.width / 2, y: box.height / 2 } });
  await expect.poll(fileTime).toBeGreaterThan(2);
  expect(await fileTime()).toBeLessThan(3);
  await bar.getByRole('button', { name: 'Play' }).click();
  await expect(bar.getByText('0:05 / 0:05')).toBeVisible({ timeout: 10_000 });
  await expect(bar.getByRole('button', { name: 'Play' })).toBeVisible();
  expect(await fileTime()).toBe(5);
});
