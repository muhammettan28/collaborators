# Browser tests of Collaborators

The tests in this folder check what Collaborators adds to Docs, in a real
browser, against the local stack. They are kept apart from the upstream suite
(`__tests__/`): they have their own settings
(`playwright.collaborators.config.ts`), sign in on their own, and run one after
the other, since each test builds on the one before.

## presentations.spec.ts

An editor adds a presentation with `/presentation`, uploads an HTML file,
clicks through it, exports it to PDF (with the dated second page), replaces it,
shows an earlier version again, renames it, changes its shape, shows it from a
link, and opens it full screen. Then: pasting its address shows it again, a
signed-out reader of a public page sees it without the menu, presenter mode
shows it, and removing it frees the storage it used.

It needs:

- the local stack running and up to date (`make run`, then `make migrate`).
  The `user-e2e-chromium` account it signs in with comes with the local
  Keycloak (`docker/auth/realm.json`); nothing else needs seeding;
- the presentation renderer (`presentation-renderer` in `compose.yml`), for the
  PDF;
- internet access: the deck shown from a link is a public file on GitHub
  (set `PRESENTATION_LINK` to use another one).

## Running them

From `src/frontend`, once (installs the packages and Playwright's Chromium):

```bash
yarn install
yarn workspace app-e2e install-playwright chromium
```

Then:

```bash
yarn workspace app-e2e test:collaborators
```

The addresses come from `apps/e2e/.env` (`BASE_URL`, `BASE_API_URL`); put your
own in `.env.local`. Each run leaves a page called "E2E presentations" in the
e2e account. On a failure, a screenshot and a trace are kept in
`apps/e2e/test-results/collaborators/`; open a trace with
`npx playwright show-trace <its trace.zip>`.
