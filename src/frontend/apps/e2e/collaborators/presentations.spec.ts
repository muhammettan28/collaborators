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
const openPage = async (page: Page, edit = true) => {
  await page.goto(`${APP}/page/${pageId}/`);
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
