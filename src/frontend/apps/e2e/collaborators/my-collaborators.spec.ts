import { type Page, expect, test } from '@playwright/test';

/**
 * "My Collaborators" (the people one shares a workspace, a space or a page
 * with), against what the server lists for the e2e account. See README.md
 * next to this file for what it needs and how to run it.
 */

const APP = process.env.BASE_URL ?? 'http://localhost:3000';
const API = process.env.BASE_API_URL ?? 'http://localhost:8071/api/v1.0';
const SCREEN = `${APP}/?target=collaborators`;

interface DirectoryPerson {
  id: string;
  full_name: string;
  email: string;
  is_colleague: boolean;
  workspaces: string[];
}

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

test.describe.configure({ mode: 'serial' });

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

test('shows the people the server lists, or says nobody is there', async ({
  page,
}) => {
  const listed = (await (
    await page.request.get(`${API}/people/directory/?q=`)
  ).json()) as DirectoryPerson[];
  const me = (await (await page.request.get(`${API}/users/me/`)).json()) as {
    id: string;
  };
  expect(listed.map((person) => person.id)).not.toContain(me.id);

  await page.goto(SCREEN);
  const directory = page.getByTestId('people-directory');
  await expect(directory).toBeVisible({ timeout: 60_000 });

  for (const person of listed) {
    const row = directory.getByTestId(`person-${person.id}`);
    await expect(row).toBeVisible();
    await expect(row).toContainText(person.full_name || person.email);
    // the workspaces shared, if any ("" is in any text)
    await expect(row).toContainText(person.workspaces.join(', '));
  }
  // "Nobody here yet" exactly when nobody shares anything with the account
  const hasColleagues = listed.some((person) => person.is_colleague);
  await expect(directory.getByTestId('people-directory-empty')).toHaveCount(
    hasColleagues ? 0 : 1,
  );
  await expect(directory.getByText('People I work with')).toHaveCount(
    hasColleagues ? 1 : 0,
  );

  // A row opens the person's profile
  test.skip(!listed.length, 'Nobody to open: the list is empty');
  await directory.getByTestId(`person-${listed[0].id}`).click();
  await expect(page).toHaveURL(new RegExp(listed[0].id));
});

test('a list that cannot be loaded says so', async ({ page }) => {
  await page.route('**/people/directory/**', (route) =>
    route.fulfill({ status: 500, json: { detail: 'down' } }),
  );
  await page.goto(SCREEN);

  await expect(
    page.getByTestId('people-directory').getByRole('alert'),
  ).toContainText('The list could not be loaded.', { timeout: 60_000 });
  await expect(page.getByTestId('people-directory-empty')).toHaveCount(0);
});

test('with nobody around, the screen says so and points to workspaces', async ({
  page,
}) => {
  await page.route('**/people/directory/**', (route) =>
    route.fulfill({ json: [] }),
  );
  await page.goto(SCREEN);

  const empty = page.getByTestId('people-directory-empty');
  await expect(empty).toBeVisible({ timeout: 60_000 });
  await empty.getByRole('link', { name: 'Find a workspace to join' }).click();
  await expect(page).toHaveURL(/\/workspaces\/discover\/?/);
});
