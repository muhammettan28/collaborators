# Collaborators — Feature Spec

> **Status:** living draft v0.1 (2026-10-19). Expect changes after the first demo.
> **Product:** Collaborators — https://collaborators.community
> **Base:** fork of [La Suite Docs](https://github.com/suitenumerique/docs) (MIT), cloned at `0579a0ff` (2026-10-14, after v6.0.1). The original repo is the `upstream` git remote.

Collaborators combines the best parts of Notion, Atlassian Confluence, Microsoft Loop, La Suite Docs and Docmost into one platform. This spec lists what we are building (**Must-haves**), how it maps onto the Docs codebase, and the order we build it in.

Legend for "Docs today": ✅ already there · 🟡 partly there · ❌ to build.

---

## 1. Vocabulary and structure

| Term | Meaning |
|---|---|
| **Collaborators** | The platform itself, the roof over everything. Run by its **owners, administrators and managers** (see Roles). Its logo is the text wordmark **CO✍️✍️ABORATORS**, in bold italic capitals (no logo image), so it works the same in the app and in emails; page titles and screen readers use the plain name "Collaborators". |
| **Collaborator** | A person with an account (we don't say "user" in the UI). There is no guest status (decided 2026-10-23): people from outside are invited to a workspace, space or page like anyone else. |
| **Workspace** | An organisation-level area (a company, university, community). Has its own members, admins and user groups. Address: `<slug>.collaborators.community`. |
| **Space** | A team or topic area inside a workspace, holding a tree of pages. |
| **Shared space** | A space owned by one workspace (its **home**) and linked into others. |
| **Independent space / page** | A space or page owned by a collaborator instead of a workspace. |
| **Page** | A document: blocks, sub-pages, Loop tables. |
| **User group** | A set of collaborators managed by workspace admins: a **Team** (task based) or an **Organization** (company, institution). Called "user groups" everywhere in the interface (2026-11-01); still `Group` in the code, the API (`/groups/`) and the page content (`kind: "group"`). |

```
Collaborators  (collaborators.community)
├── Workspace "Acme"                     acme.collaborators.community
│   ├── Space "Engineering"  → pages
│   │   └── "Roadmap" linked from "Q4 Launch" (same page, not a copy)
│   └── Space "Q4 Launch"    → pages     (shared with workspace "Partner Co")
├── Independent space "Mustafa's Research"   (owned by a collaborator)
│   └── pages
└── Independent page "Trip plan"             (no space, no workspace)
```

### Ownership rules

- Every space and every page has exactly **one owner**: a workspace or a collaborator.
- A page belongs to at most one space (its **home**); sub-pages follow their parent. It can be **linked into other spaces** as well: the same page, shown there as "Linked from <home>", with an "Also in" line under its title.
  - Whoever has a role on a linking space can read the page and its sub-pages there; it is still edited and shared from its home.
  - Linking needs owner/administrator rights on the page and edit rights in the space. The page's managers or the space's administrators can unlink it.
- **Moving, both ways:**
  - an independent page can move into a space ("Move into a space"), and a page can leave its space to be independent again ("Make independent": whoever does it owns it, and the space's roles no longer apply);
  - an independent space can move into a workspace or be linked into more as a Shared space, and a home-workspace admin can make a space independent again (the workspaces' roles on it go).
  - Moving content *out* of a workspace needs a workspace admin (or the page's owner/administrator).
- **Shared spaces:** the home workspace controls the space's settings, deletion and which workspaces it is linked to. Linked workspaces show it with a "Shared from Acme" badge, and their own admins decide which of their groups can open it. Unlinking removes it from that workspace without deleting content.

### Roles

| Level | Roles |
|---|---|
| Platform | Owner · Administrator · Manager · Collaborator |
| Workspace | Owner · Admin · Member |
| Space / page | Owner · Administrator · Editor · Commenter · Reader *(Docs' existing `RoleChoices`)* |

Space and page access can be granted to a collaborator or to a **user group**.

**Platform levels** (names decided 2026-10-25; one word each in the interface, without "platform", 2026-10-25), each with the rights of the levels below it:
- **Collaborator:** anyone with an account.
- **Manager:** approves new registrations (5c) and reads the list of everyone (the "Manage" tab).
- **Administrator:** suspends or removes accounts, from the platform and from Keycloak, with their pages handed over or deleted; handles content reports; appoints managers.
- **Owner:** appoints administrators and owners; full `/admin/` rights; platform-wide settings.
- Every action of these levels is logged.
- **Built 2026-10-25 (step 1):** the levels (`User.platform_role`, `core/platform_roles.py`; a superuser counts as an owner) and the **platform log** (`PlatformLog`, read only in `/admin/`), which records every change of level with who made it (or the command line, the settings, the migration). Owners alone open `/admin/` (they are its superusers); the other levels act in the app. Migration 0061 made the former staff users managers and superusers owners. Registrations are decided by managers and above (the emails of `COLLABORATORS_PLATFORM_ADMIN_EMAILS` become managers at sign-in). `manage.py set_platform_role <email> <level>` sets a level until appointing is in the app. On collaborators.community (2026-10-25): two owners, one administrator, one manager.
- **Built 2026-10-25 (step 2): suspending, removing and blocking** (`core/accounts.py`), always on people below one's own level, never oneself; each is logged, and the person is told by email (with the reason, if given):
  - **Suspend** (administrators and owners; "Suspend" on the person's row in Manage): the account is inactive (signed out of the app at once) and disabled at the sign-in server, its sessions there ended, until **Reinstate**. Their pages stay as they are. Suspended people stay listed, marked "Suspended", with a "Status: Active / Suspended" filter.
  - **Remove** (administrators and owners): the account is deleted from the platform and from the sign-in server. The dialog first shows what it alone owns (pages, with how many pages are below them, and workspaces). Their pages are **handed over** (to oneself by default, or to someone found by name) or **deleted for good** with the pages below them. Workspaces are never deleted: they go to whoever receives the pages, else to their next administrator or member, else to whoever removes.
  - **Block** (owners only; the "Blocked accounts" tab, and "Also block …" when removing): nobody signs in with a blocked email, whether or not it has an account yet (an account with it is suspended; one at the sign-in server is disabled). Unblocking leaves a suspended account suspended until reinstated. An owner's email can't be blocked.
  - If the sign-in server can't be updated, the change is made here all the same and the screen says so. Its accounts are found by email (2026-10-26: a collaborator's `sub` is their email on collaborators.community, not the sign-in server's id; before that fix nothing had been suspended or removed).
- **Built 2026-10-26 (step 3): appointing** ("Level" on a person's row in Manage): administrators make collaborators managers, or managers collaborators again; owners give any level, owner included (an owner also opens `/admin/`). Only for people below one's own level, let in and not suspended; each level is explained in the dialog. Logged, and the person is told by email. **Protected owners** (2026-10-26; `User.platform_protected`, set with `set_platform_role <email> owner --protected` on the server, so their emails stay out of the code): nobody changes their level in the app, not even each other; they alone change other owners' levels (from owner down to collaborator, and back). Other owners give any level to people below them, owner included, but lower no owner. Nobody changes their own level. On collaborators.community the two first owners are protected.
- **Built 2026-10-26 (step 4): content reports and platform settings.**
  - **Report this page** (the page's "…" menu, for anyone signed in who reads it): a reason (spam or advertising, abuse or harassment, illegal content, someone's personal data, copyright infringement, something else) and a few words. The page's text is kept with the report, as it was (`ContentReport`, `core/reports.py`), so administrators judge it even when they can't open the page; its owners don't learn who reported it. One open report per person and page.
  - **Reports** tab (administrators and owners), also reached from the notification each of them gets (and an email): "To decide" and "Decided". **Dismiss** (the reporter is told nothing was taken down), or **Take the page down**: it goes to the trash with the pages below it and its owners can't restore it (`Document.taken_down_at`); every open report of it is closed; its owners (with the reason given) and the reporters are told. **Put the page back** undoes it while it is in the trash. All logged.
  - **Settings** tab (owners; `PlatformSettings`, `core/platform_settings.py`): "New registrations wait for approval" and "Invitations by email" (now also for workspaces). A setting never changed follows the server's own (`COLLABORATORS_SIGNUP_APPROVAL`, `COLLABORATORS_EMAIL_INVITATIONS`); "Follow the server's own" forgets a change. Changes are logged.
  - The tabs of the "My CO✍️✍️ABORATORS" screen open from the address: `/?target=collaborators&tab=reports` (or `manage`, `blocked`, `settings`).
  - **Manage** (first called "Manage Collaborators"): a tab of the "My CO✍️✍️ABORATORS" screen (now at `/?target=collaborators`; `/?target=people` still opens it), for managers and above: everyone with an account, newest first, with their level, registration, email (verified or not), when they joined and last signed in, their workspaces and the pages they own; found by name or email, and filtered with three drop-down lists, **Level**, **Registration** and **Status** (active or suspended) (`GET platform/people/`, 50 a page). The tab is called **Manage** (2026-10-26).

---

## 2. Must-have features

| # | Feature | Docs today |
|---|---|---|
| F1 | Loop-style table, with @mentions and groups in cells | ❌ only simple BlockNote tables |
| F2 | Self sign-up through SSO only | ✅ phase 6 (see what is left below) |
| F3 | Lean dashboard each collaborator can customise | ✅ phase 4 |
| F4 | @mentions with notifications in pages, comments and table cells | 🟡 user mentions + email exist; inbox, groups, table cells to build |
| F5 | Groups managed by workspace admins (Teams, Organizations) | 🟡 a `team` access hook exists but is empty |
| F6 | Platform → Workspace → Space → Page, with Shared spaces | ❌ Docs has only a tree of documents |
| F7 | Independent spaces and pages | 🟡 every Docs document is independent today; independent *spaces* to build |
| F8 | Public sharing: pages to the web, spaces as public wikis | ✅ phase 5 (see what is left below) |

### F1 — Loop-style table

See **section 3**: it is the largest single piece of work.

### F2 — SSO-only self sign-up

**Requirements**
- Sign up and sign in only through: **Google** (personal + Google Workspace), **Microsoft** (personal + work/school), **LinkedIn**, all with ordinary personal accounts. More providers can be added by configuration.
- **No Apple and no X sign-in** (user's decision, 2026-10-19): Apple needs a paid Apple Developer membership; the X API is pay-per-use (about $0.01 per sign-in).
- **No email-invitation sign-up.** Anyone can create an account by signing in. Sharing only finds collaborators who already have an account; to bring someone new, you send them a join link.
- **Account linking:** signing in with a second provider whose *verified* email matches an existing account links to that account after confirmation. Settings → "Sign-in methods" lists, adds and removes providers (at least one must remain).
- **Provider quirks to handle:**
  - Microsoft: use the `common` endpoint so both personal and work accounts work; the `tid` claim identifies the company tenant.
  - Google: the `hd` claim identifies a Google Workspace domain.
- **Workspace joining:** a workspace can be joined by (a) a join link, (b) admin approval of a request, or (c) automatically by **verified domain** (`@acme.com`, or Microsoft tenant / Google Workspace domain), which also adds the person to that workspace's matching Organization group (F5).

**Docs today**
- Login is OIDC via `mozilla-django-oidc`, with Keycloak in development; users are created on first login (`OIDC_CREATE_USER`).
- An email `Invitation` model and endpoint exist (`InvitationViewset`).

**Work**
- Configure an identity broker in front of Django with the four providers: Keycloak, already in the dev stack, has all of them built in.
- Branded sign-in page with provider buttons.
- Turn off invitation-based sign-up in the UI and API; keep the model only until migration cleanup.
- Account linking and "Sign-in methods" settings.
- Store provider, tenant id and domain claims on the collaborator for F5 auto-join.

**Built in phase 6:**
- **Sign-in page** `/signin`: one *Continue with …* button per provider set up (Google, Microsoft, LinkedIn), each going straight to it; a test-account button in development only.
- **Providers:** the setup script adds Google, Microsoft and LinkedIn (all Keycloak's own providers). Each needs its app made once at the provider by the owner of Collaborators (see `sso-setup.md`).
- **Unverified emails** (Microsoft) are confirmed by a link the first time (Keycloak's *Verify email*); Google and LinkedIn emails are trusted.
- **Account linking:** Keycloak's first sign-in flow links a second provider giving the same email, after confirmation (sign in with the first method, or a link by email). Google and LinkedIn emails count as verified; Microsoft's don't.
- **Joining a workspace:**
  - **Join link**, made, renewed or turned off by admins; `/join/<link>` asks to sign in, then joins.
  - **Email domain:** a verified email at the domain joins on sign-in, also into an organisation group if one is chosen. An admin can only add the domain of their own verified email; public domains (Gmail, Outlook…) are refused.
  - **Organisation:** whoever signs in with an account of a chosen Google Workspace (`hd`) or Microsoft work tenant (`tid`) joins. An admin can only add an organisation they signed in with themselves; personal Google and Microsoft accounts have none. The backend reads these claims at sign-in from the provider ID tokens Keycloak stores (`storeToken`), with the person's own access token (`broker` `read-token` role).
  - **Admins approve who joins** (a workspace setting): joining by link, domain or organisation then sends the admins a request, in their inbox and the workspace settings. Approving lets the person in and notifies them; a declined request is kept, so it isn't made again.
- **Email invitations** to documents are turned off; documents are shared with people who have an account.
- **Sign-in methods page** `/account/sign-in-methods/` (account menu): each provider with its logo, connected (with the account) or not.
  - **Connect** starts Keycloak's `idp_link` action: the person signs in with that provider once (at most an hour after signing in, else they sign in again first).
  - **Disconnect** removes the link, never the last way in.
  - The backend reads and removes links through Keycloak's admin API, with its own service client `collaborators-backend` (`COLLABORATORS_KEYCLOAK_*`).
- The sign-in buttons and the methods page show each provider's official logo.
- **Several Google or Microsoft accounts** can open one collaborator's account: *Add another Google account* on the sign-in methods page, through the provider's account chooser. Keycloak links one account per provider, so the others are recorded in the app (`SignInIdentity`). One that already opens a separate Collaborators account isn't added. LinkedIn: one account.
- **Merging two accounts of one's own** (built 2026-10-26, `core/merging.py`), through **Add another Google / Microsoft account** on the sign-in methods page: when the account added already opens a separate Collaborators account, signing in with it proved it is theirs, and the page offers "<email> already has its own Collaborators account. Merge it into this one?" with what it brings (Merge into this account / Not now). An account that signs in only with LinkedIn is merged the other way round (sign in with it, add the Google or Microsoft account there). Everything moves over: page and space accesses (the higher role kept), pages made, favourites, comments, reactions, mentions, assignments, workspace memberships (the higher role kept), join requests, groups (managers stay managers), labels, invitations sent, notifications, the profile (if the account kept has none), its other sign-in accounts; its account at the sign-in server opens the account kept from then on, and the other account goes. Never between different people (only whoever signs in with both). Not merged: a suspended account, a protected owner's, or one at a higher level than the account kept (merge the other way). Logged. Not rewritten: mentions and Person cells already in pages keep the other account's name (their hover card no longer finds it).
- **Dashboard notes**, one at a time (the welcome closes for good; the other stays until another provider is connected):
  - a new account is welcomed, warning that an account under another email is a separate one;
  - someone connected with a single provider is told, with a yellow symbol, that another account under a different email opens a separate account, and where to connect it. The sign-in methods page shows the same note.

**Not planned** (decided 2026-10-25): emailing admins about requests to join. They reach the in-app inbox, to be improved there if needed; emails only if someone asks for them.

### F3 — Lean, customisable dashboard

**Requirements**
- The landing screen after sign-in. Lean by default: a search box and **three cards**: *Recent pages*, *Mentions & notifications*, *Assigned to me*.
- Optional cards a collaborator can add: *Favorites*, *My spaces*, *My workspaces*, *Independent pages*, *Shared with me*.
- Each collaborator can **collapse**, **hide**, **show** and **reorder** cards (drag and drop, plus keyboard), and **Reset to default**.
- Layout is saved on the server per collaborator, so it follows them across devices.
- Works on phone widths (cards stack in one column).

**Docs today:** ❌ the home page lists documents.

**Work:** dashboard page, card registry, per-user layout preference (API + model), "Assigned to me" query over Loop tables (F1).

### F4 — @mentions and notifications

**Requirements**
- `@` suggests **collaborators and user groups** in page text, comments and **Loop table cells**.
- Typing `@` alone lists, with nothing typed: the people one works with, all user groups and all pages one can read. Typing narrows the list.
  - **People** = members of one's workspaces + people one shares pages with. Never every account on the platform (user's decision).
  - Anyone else is found by the platform-wide search after 3 letters.
  - **User groups** = every user group of every workspace one belongs to.
- Assigning a collaborator or group in a table's **Person** column also notifies them.
- **Notification inbox** (bell icon) with unread count, mark read / all read, and filters; each item links to the exact block, comment or **table cell** and highlights it.
- **Email** per collaborator preference: right away, or off. (Daily digests were dropped.)
- Only *newly added* mentions notify; re-editing a page doesn't notify again.
- If the person can't see the page, the writer is asked whether to share it with them.
- **Group mentions:** members are resolved when the notification is sent. Mentioning more than 20 people asks "Notify N people?" first.
- Collaborators can mute a page, a space or a group mention.
- On public pages (F8), mentions show the display name only.

**Docs today**
- `Mention` model (document, block `anchor_id`, optional comment thread, mentioned user) and `POST /documents/{id}/mention/`, which emails the user with a cooldown so repeated mentions don't spam.
- No in-app inbox, no group mentions, no table-cell anchors.

**Work**
- `Notification` model and inbox UI (bell, list, read state, preferences).
- Extend `Mention`: optional `mentioned_group`; anchor that can point at a **table cell** (table id + row id + column id).
- Fan-out of group mentions to members; "Notify N people?" confirmation.
- Later hardening: detect added and removed mentions on the server when the collaboration server reports new content (`content-updated`), rather than trusting the client alone.

### F5 — User groups

**Requirements**
- Workspace admins create, rename and delete groups; add and remove members; optionally appoint **group managers** who can manage membership.
- Two kinds: **Team** (task based, e.g. "Q4 Launch") and **Organization** (company or institution, e.g. "Acme").
- Organizations can fill automatically from verified domains or Microsoft tenants at sign-in (F2).
- Groups work everywhere a person works: @mentions (pages, comments, **table cells**), Person columns in Loop tables, sharing and permissions, and filters ("Assigned to me" includes rows assigned to my groups).
- A group chip shows its name; hovering lists its current members.
- In a Shared space, each linked workspace grants access to its own groups.

**Docs today:** `DocumentAccess` already accepts a `team` instead of a user, and `User.teams` is a hook that currently returns an empty list.

**Work:** `Group` and `GroupMembership` models scoped to a workspace; make `User.teams` return the collaborator's group ids so existing team-based access works unchanged; admin UI; group search in the mention menu and Person columns.

### F6 — Workspaces, spaces and Shared spaces

**Requirements:** as described in section 1, with a workspace switcher, a space list in the sidebar, workspace settings (members, groups, domains, join link, publishing policy) and space settings (members, groups, linked workspaces).

**Docs today:** ❌ documents form one tree per root document (`django-treebeard`), with no workspace or space layer.

**Work:** `Workspace`, `WorkspaceMembership`, `Space`, `SpaceWorkspaceLink` (with one *home* link). A space owns a set of root documents, so Docs' existing tree, sharing and history keep working inside it. Subdomain routing per workspace.

### F7 — Independent spaces and pages

**Requirements**
- A collaborator can create spaces and pages that belong to no workspace.
- They are shared person by person (groups become available once the content joins a workspace).
- A "My spaces & pages" section in the sidebar.
- Moving rules as in section 1.

**Docs today:** ✅ for pages: every Docs document is already owned by people, not a workspace.

**Built:** independent spaces and pages ("My spaces & pages" lists both, with a + for each), moving pages into and out of spaces, making spaces independent again, and linking a page into several spaces (`PageSpaceLink`).

**Built 2026-10-25:** a page linked into a public space (or one open to everyone signed in) is public through it, read-only as the space, with its pages down to one kept private; its home is unchanged (`Document.linked_link_reach`, kept up to date when links or spaces change).

### F8 — Public sharing and public wikis

**Requirements**
- **Publish a page to the web:** public read-only link, optionally including sub-pages, with a switch for search engine indexing.
- **Publish a space as a wiki:** public read-only site with a page-tree sidebar, wiki-wide search, its own logo and colours, and clean addresses (`collaborators.community/wiki/<slug>` or `<workspace>.collaborators.community/<slug>`). Custom domains later.
- Pages can be marked **Keep private** to leave them out of a published wiki.
- **Privacy:** mentions show display names only; links to private pages render as "Private page"; Loop tables publish read-only with names only in Person cells.
- Workspace admins choose who may publish; an audit log records who published what and when.
- Published content updates live; "publish a fixed version" may come later.

**Docs today:** 🟡 a document's link reach can be `public` with a reader role, and access passes down to sub-pages. No wiki mode, slugs, indexing control or redaction.

**Work:** wiki renderer and routes, slugs, `noindex` control, Keep private flag, redaction of mentions and private links for anonymous readers, publishing policy and audit log.

**Built in phase 5:**
- *Publish to the web* in the share dialog:
  - **Spaces:** *Publish as wiki*, with an address, one of six accent colours and a search-engine switch. Publishing makes the space public and read-only for everyone not invited.
  - **Public pages:** a *Let search engines find this page* switch.
  - **Sub-pages:** *Keep private*. A page kept private inherits no link access (public, or any signed-in collaborator) from the pages above it, so it and its sub-pages leave public links and wikis. Invited people keep their access.
- **Wiki reader** at `/wiki/<slug>` and `/wiki/<slug>/<page>`, for anyone:
  - the page tree and a title search on the side;
  - the wiki's colour, and an *Edit* button for its editors;
  - links to its own pages stay in the wiki;
  - links to pages the reader can't open read "Private page".
- **Search engines:** pages are `noindex` unless published with indexing allowed.
- **Workspace settings → Publishing:**
  - *Who can publish*: space owners and administrators, or workspace administrators only.
  - The **publishing log**: page published or unpublished, and wiki published, updated or unpublished.

**Built after phase 6 (wiki extras):**
- **Full-text search:** the wiki's search finds pages by their text as well as their titles, showing the words around the match.
  - Each page of a published wiki keeps a plain-text copy (`Document.text_content`). It is refreshed whenever the collaboration server reports a change, and on first search for older pages.
- **A logo:** an image uploaded in the share dialog. It shows in the wiki's header, beside its title.
- **A fixed version:** in the share dialog, *Publish a fixed version* copies every page of the wiki as it is now (`WikiRelease`).
  - Readers see that copy until the next one. *Publish the current version* replaces it; *Show the live pages* goes back to live.
  - Meanwhile the live pages are not public (the space is restricted), but the copy's images are.
- **Addresses:** a wiki is also read at `<workspace>.collaborators.community/<wiki>/` (that address lists the workspace's wikis). It can also have its own domain (e.g. `help.example.com/`), set in the share dialog.
  - Settings: `COLLABORATORS_WIKI_BASE_DOMAIN`, `COLLABORATORS_APP_HOSTS` (any other address is looked up as a wiki's domain) and `COLLABORATORS_WIKI_DOMAIN_TARGET` (the CNAME target shown to admins).
  - In dev: `<workspace>.localhost:3000`.
  - **To deploy:**
    - DNS: a wildcard record for `*.collaborators.community`, and a CNAME from each own domain to the target.
    - TLS: certificates for those addresses (e.g. on-demand TLS at the reverse proxy).
    - Routing: the proxy serves the frontend, `/api`, `/media` and the collaboration websocket on them too (or allows their origins).
- The wiki's page tree is hidden until the reader shows it, as in the app.


---

## 3. Loop-style table (F1)

The goal is Microsoft Loop's table with all its features, plus what Collaborators needs on top (groups, notifications) and fixes for gaps Loop users often complain about.

**Sources.** Microsoft has no single reference page for Loop tables. Behaviour below comes from Microsoft 365 Insider posts, Microsoft Support, and hands-on reviews (research done 2026-10-19; source links in the appendix).

**Tags used in this section:**
- **Origin:** **L** = Loop does this (documented) · **L?** = Loop behaviour not documented; to verify hands-on in Loop (section 3.7) · **C** = Collaborators addition.
- **Phase:** **v1** = first table demo (delivery phase 2) · **v2** = next iteration · **Later**.

### 3.1 Inserting and structure

| # | Behaviour | Origin | Phase |
|---|---|---|---|
| T1 | `/table` inserts a table into a page; it starts as 2 columns × 2 rows | L | v1 |
| T2 | A built-in, non-removable **row-number column** on the left. It holds the row's drag handle and the "open details" icon | L | v1 |
| T3 | A header row with column names; header text is plain (no rich formatting) | L | v1 |
| T4 | A **summary row** at the bottom (see T25), off by default: added or removed from the table menu ("Add a summary row", 2026-10-20); older tables keep it where a summary was chosen | L | v1 |
| T5 | The table can be widened into the page margins ("expand to margins") | L | v1 |
| T6 | Pasting cells from Excel or Google Sheets fills the table, adding rows and columns as needed | L | v1 |
| T7 | Import a CSV file into a new table | L? | v2 |
| T8 | Templates built on the same table: Task list, Voting table, Progress tracker, Kanban, Retrospective | L | Later |

### 3.2 Column types

| # | Type | Behaviour | Origin | Phase |
|---|---|---|---|---|
| T9 | **Text** (default) | Rich text: bold, italic, text and background colour, links. `/` inside a cell inserts inline elements (label, date, person, emoji, image) | L | v1 |
| T10 | **Number** | Right-aligned. **Formats** (plain, decimals, %, currency) | L / formats C | v1 |
| T11 | **Date** | Calendar picker; the year is hidden for dates in the current year | L | v1 |
| T12 | **Person** | Pick one or more **collaborators or groups**; assigning notifies them (F4). Group chips show members on hover | L / groups + notify C | v1 |
| T13 | **Label** | Coloured single-select chips from a **label group**. Built-in groups: Priority (Low/Medium/High) and Progress (Not started/In progress/Done); custom groups with editable names and colours | L | v1 |
| T14 | **Label (multi-select)** | Several labels in one cell. Loop can't do this; users ask for it | C | v2 |
| T15 | **Voting** | A `+` button and count; hover shows who voted | L | v1 |
| T16 | Reusable label groups across a workspace (Loop limits them to one page) | C | v2 |
| T17 | Checkbox, URL, Formula and Rollup columns. Loop has none of these | C | Later |

- **Change column type** from the header menu. Loop erases the column's contents when you do this. We **convert values where possible** (e.g. text "12" → number 12) and ask for confirmation before discarding anything. **C**, v1.

### 3.3 Column and row operations

| # | Behaviour | Origin | Phase |
|---|---|---|---|
| T18 | **Add a column:** hover over a column border and click the `+` at the top; also insert left/right from the header menu | L | v1 |
| T19 | **Header menu** (down-arrow on hover): rename (or double-click the header), change type, insert left/right, sort, filter, hide, delete | L | v1 |
| T20 | **Resize** a column by dragging its border | L | v1 |
| T21 | **Reorder columns** by dragging the six-dot handle above the header | L | v1 |
| T22 | **Add a row:** "New" at the bottom, the `+` between row numbers, or **Tab in the last cell** | L | v1 |
| T23 | **Reorder rows** by dragging the six-dot handle beside the row number | L | v1 |
| T24 | Row menu (right-click or handle): insert above/below, duplicate, delete, open details, comment | L / L? | v1 |
| T25 | **Summary row:** Number columns show Sum (default), Average, Count, Min or Max; Person columns show a count per person. Click the summary cell to change it | L | v1 |
| T26 | **Select several rows**, then delete, copy or drag them together | L (task lists) | v2 |
| T27 | **Row height** setting (compact / normal / tall), and text wrap per column | L? | v2 |
| T28 | **Hide columns** | L? | v1 |
| T29 | **Freeze** the first column(s) while scrolling sideways. Loop doesn't have this | C | v2 |
| T30 | Merged cells: **not supported** (Loop doesn't support them either; they break sorting and filtering) | — | — |

**Drag-and-drop feedback (T21, T23)**
- While dragging, the moving row or column is highlighted, a copy of its cells follows the cursor, and a drop line shows where it will land.
- This is the behaviour from your BlockNote PR [#2920](https://github.com/TypeCellOS/BlockNote/pull/2920), carried over to the Loop table.
- **C additions:** reordering also works by **keyboard** and on **touch screens**. BlockNote's own tables can't do either today.

### 3.4 Sort, filter, group and views

| # | Behaviour | Origin | Phase |
|---|---|---|---|
| T31 | **Toolbar** above the table: Filter, Sort, Switch view, Group by, Expand/Collapse | L | v1 |
| T32 | **Filter:** rules of column + condition + value, combined with AND. The icon shows how many rules are active. A row you edit stays visible until the filter is reapplied | L | v1 |
| T33 | Filter rules combined with **OR**, and rule groups | C | v2 |
| T34 | **Sort** by a column, ascending or descending | L | v1 |
| T35 | Sort by **several columns** | L? / C | v2 |
| T36 | Filters and sort are **saved with the table and shared** with everyone who can see the page | L | v1 |
| T37 | A personal "only for me" filter that doesn't change the table for others | C | v2 |
| T38 | **Board view** of the same data: cards grouped by a chosen Label or Person column; drag cards between columns; duplicate cards. Needs at least one Text and one Label column. Filters carry over between Table and Board | L | v2 |
| T39 | **Group rows by a column** in Table view, with collapsible groups | C | v2 |
| T40 | "Assigned to me" filter, which includes rows assigned to my groups | C | v1 |

### 3.5 Cells, details and collaboration

| # | Behaviour | Origin | Phase |
|---|---|---|---|
| T41 | **@mentions in Text cells** of collaborators **and groups**. Mentioning notifies; the notification opens the page and highlights the cell (F4) | L / groups C | v1 |
| T42 | Page links in cells (`Ctrl/⌘+K`, and `[[` to link to another page) | L / `[[` C | v1 |
| T43 | **Real-time co-editing** with coloured cursors and presence avatars | L | v1 (comes from Docs) |
| T44 | **Comments on a cell:** right-click → New comment, or `Ctrl/⌘+Shift+F2`. A small icon marks commented cells; threaded replies; you can edit or delete only your own comments | L | v2 |
| T45 | **Row details panel:** open a row from the number column (or right-click → View details) to edit all its fields in a side panel and add free-form notes below them | L | v2 |
| T46 | Row details as a full page, next/previous row navigation, and a link to a single row | L? | Later |
| T47 | **Rules:** "when this column changes or has this value, then notify…", with in-app and email notifications (no external automation service needed) | L | Later |
| T48 | Page version history includes table changes (Docs' history already covers the whole document) | L | v1 |

### 3.6 Keyboard, mobile, accessibility, export

| # | Behaviour | Origin | Phase |
|---|---|---|---|
| T49 | **Keyboard:** arrow keys move between cells; Enter edits; Esc leaves the cell; Tab and Shift+Tab move along a row; Tab in the last cell adds a row; `/` and `@` work inside cells; `Ctrl/⌘+Z` and `Ctrl/⌘+Y` undo and redo | L / L? | v1 |
| T50 | Selecting ranges with Shift+arrows, then copy, paste or clear them | C | v2 |
| T51 | Screen readers announce cells, headers and column types | L | v1 |
| T52 | **Touch:** tap to edit; long-press handles to drag; tables scroll sideways on phones | L? / C | v2 |
| T53 | **Export** a table to Excel (.xlsx) and CSV, mapping column types to the nearest Excel format | L / CSV C | v2 |
| T54 | Tables appear correctly in page PDF/DOCX export and in search results | C | v1 |
| T55 | Tables render read-only on public pages and wikis (F8), with names only in Person cells | C | v1 |
| T56 | Smooth with **1,000+ rows** (only visible rows are drawn) | C | v1 |
| T57 | **Background colour** and **text alignment** (horizontal and vertical) for a whole column (its "⌄" menu) or row (its "⋮" menu) | Collaborators | ✅ built |
| T58 | The same two for a **single cell** (format button on the selected cell, or right-click) | Collaborators | ✅ built |
| T59 | **Corner cell menu**: show or hide the numbers column; formatting of all the cells, of the header row and of the numbers column, each as a submenu (also in the block's "⋮⋮" menu) | Collaborators | ✅ built |
| T60 | **Text style and colour of whole cells** (bold, italic, underline, strikethrough; text colour) for all the cells, a column, a row or the selected cell, in the same menus as colour and alignment (asked for 2026-10-20). The latest choice wins (2026-10-23), whatever it was made for: a cell, a row, a column, the numbers column, the header row or all cells (formats made before that date: the most specific wins). "None" and "Default" are choices too; *Clear … formatting* takes a level's own choices away, so earlier ones show again. ⌘/Ctrl + B, I, U on a selected cell. Styles of parts of a text (T9) still apply on top. Exports (page PDF/DOCX) carry them | Collaborators | ✅ built |

### 3.7 To verify hands-on in Microsoft Loop

Loop's public documentation doesn't cover the following. Before building them, we should check them in a real Loop workspace, using your Microsoft account in the built-in browser, and record the exact behaviour here.

- **Formats and editing:** number formats, text wrap, row height in plain tables, insert row above/below.
- **Sharing and navigation:** whether sort is shared or per person, cell-to-cell keyboard keys.
- **Feel and limits:** drag-and-drop visuals (spacing, colours), touch gestures, row and column limits.
- **Features:** column hide and freeze, CSV import.

### 3.8 How we'll build it

- **A custom BlockNote block.** The table is a custom block in the editor. The block stores only a `tableId`. The table's data (columns, row order, cells, label groups, filters, sort, summaries) lives in the **same shared document** as the page, in its own part keyed by `tableId`. This gives tables real-time sync, offline support and version history for free.
  - Text cells hold rich text, so @mentions and links work inside them.
- **Grid and drag-and-drop libraries.** The grid is drawn with TanStack Table (sorting, filtering, grouping) and TanStack Virtual (large tables). Reordering uses dnd-kit, which supports keyboard and touch dragging. The visual feedback follows PR #2920.
- **Mentions point at cells.** A cell mention is a `Mention` whose anchor is *table + row + column*. Opening the notification scrolls to that cell and highlights it.
- **Spike first (start of phase 2).** Before building the full table, confirm three things:
  1. Docs' search indexing can read data stored outside the page's normal blocks.
  2. So can PDF/DOCX export and version history.
  3. Copying, duplicating and pasting a table copies its data.

  If any of these fail, the fallback is to store the table inside the block itself.
- **Simple tables stay.** BlockNote's own simple table stays available for plain layout tables. We apply your PR #2920 to it as a local patch until BlockNote merges it (or #2963).

---

## 4. Delivery plan

Each phase ends with something you can click through. Requirements may change after each one.

**Status (2026-10-19):** phases 0, 1, 2 (Loop table v1), 3 (mentions and notifications), 4 (the dashboard), 5 (public pages and wikis) and 6 (sign-in providers, account linking, joining) are built, on branches `collaborators/phase-0` to `-phase-6`.

Moved out of the table v1:
- **Table v2 (built):** rich formatting in Text cells (T9), "expand to margins" (T5), drawing only the visible rows of very large tables (T56, from 150 rows).
- **Done in phase 3:** @mentions inside Text cells (T41).

| Phase | Delivers | Features |
|---|---|---|
| 0 | Fork runs locally under the Collaborators name; Google and Microsoft sign-in | F2 (part) |
| 1 | Workspaces, spaces, groups; independent spaces | F5, F6, F7 |
| 2 | **Loop table v1**: column types, add/reorder/resize, sort, filter, Person column with people and groups | F1 (core) |
| 3 | Notification inbox; mentions of people and groups in pages, comments and table cells | F4, F1 (mentions) |
| 4 | Lean customisable dashboard | F3 |
| 5 | Public pages and public wikis | F8 |
| 6 | Remaining sign-in providers (LinkedIn), account linking, domain auto-join | F2 |

---

### Order of work (decided 2026-10-25)

1. The slash menu shows its "Basic blocks" heading twice.
2. **Public reach, checked and corrected:** what is public in public workspaces, independent public spaces and independent public pages, and what their pages and sub-pages show to readers (including pages linked into a public space, F7).
3. ✅ **Live checks, with the owner:** an invitation email accepted from a second address; dragging a table column and hiding then showing the header row on a live table; the space and workspace screens; press-and-hold block dragging on a phone. Done 2026-10-25; only the touch screens are left (see "Later" below).
4. ✅ **Publishing the Google sign-in app** (item 6 below): done 2026-10-25, tried with an account outside the test users.
5. **Microsoft and LinkedIn sign-in in production:** checked live; the LinkedIn app's settings in its developer portal (linkedin.com/developers) checked or completed. 2026-10-26: Microsoft works. LinkedIn worked, but the first try ended on an empty dashboard: a second return from the sign-in server for the same sign-in ("authentication_expired") signed the person out right after signing them in (it happened once with Microsoft too, in the other order). Such a return now changes nothing (`core/authentication/views.py`).
5b. **Platform roles** (see section 1, Roles): four levels instead of two. Steps: ✅ the levels and the list of everyone ("Manage", 2026-10-25); ✅ suspending, removing and blocking accounts (2026-10-25); ✅ appointing (2026-10-26); ✅ content reports and platform settings (2026-10-26). Done.
5c. ✅ **Notifications: "See all" and two tabs** (asked for 2026-10-25, built 2026-10-26): the bell shows "See all" at the top of its popup (above the list, however long), and the dashboard's Notifications card at its foot, always (even empty), both leading to the Notifications screen (the panel's "Notifications" item). That screen has two tabs: **Active** (unread notifications, and what is still assigned to one) and **Read** (the notifications read, latest 50; `GET notifications/?unread=true` / `?read=true`). "Mark all as read" shows on the Active tab.
6. ✅ **Input from one's own AI tools** (item 11 below; moved before grant calls and built 2026-10-26).
7. **Grant calls** (items 7–10 below), once the owner has decided where calls come from.
8. Last: a README of Collaborators for the GitHub repository.
   - **Animated product demo** (2026-10-26): `demo.html` at the repository's root, published at https://collaborators.community/demo (its copy `src/frontend/apps/impress/public/demo/index.html`; keep the two the same). A 40-second animation with fictional people: writing together live, Claude adding a person's input through the MCP server, what an assistant may do.

Later (found in the live checks of 2026-10-25): **touch screens.** On a phone, the table's handles and menus (columns, rows, header row) and the press-and-hold dragging of blocks don't work yet; they work with a mouse. Needed for tablets at least, when a real need arises.

Not planned: emailing admins about join requests (see F2). Dropped (2026-10-25): checking a wiki domain's DNS before accepting it, and keeping several fixed versions of a wiki.

### To do next, in order

Done: the Loop table tweaks, Loop table v2 (T9, T5, T56), the wiki extras (F8), the in-app sign-in methods page, and the joining extras (join requests approved by admins; joining by Google Workspace or Microsoft organisation) (F2).

**Before the first public version** (asked for 2026-10-20; in this order, small ones first, then the ones that shape data and privacy from day one):

1. ✅ **Group management by group creators** (built 2026-10-20): any workspace member can create a team (organizations stay with administrators) and manages it like an administrator: renames or deletes it, adds and removes people, appoints managers. People are moved or copied between the groups one manages (tick them, then *Move or copy*). A person can be in several groups.
2. ✅ **Profile badge on mentions** (built 2026-10-20): hovering a mentioned person (in pages, comments, and table cells, text or Person columns) shows a card: initials, name, and, for someone the viewer works with, their email, shared workspaces and their groups there (`GET people/<id>/`). Once profile pages exist, the card shows what the profile lets the viewer see, with a link to it.
3. ✅ **One visibility setting** (built 2026-10-20):
   - **Pages and spaces:** the share dialog's "Who can see this?":
     - Public on the internet; Everyone on Collaborators (both with "people can read / comment / edit");
     - Members of <workspace> (each workspace the space belongs to);
     - for a page in a space, "Same as <space>"; otherwise Only invited people.
     - A page in a space can't be hidden from the space's people (accesses flow down): it is made independent first. A space published live as a wiki stays public until the wiki is unpublished. Search engines: the "Publish to the web" switch, for public pages and wikis.
   - **Workspaces:** "Who can find this workspace" in its settings: public, everyone on Collaborators, or only its members. Findable ones are listed in **Discover workspaces** (`/workspaces/discover/`, also signed out for public ones) with their public spaces; "Ask to join" always sends the admins a request.
   - **To decide:** inviting people from outside the platform needs email invitations, turned off so far.
3b. ✅ **Table tweaks** (built 2026-10-20): new tables start without the row-number column (the table menu shows it; existing tables keep theirs), and a table is never highlighted as a whole block: only its active cell is.
4. ✅ **Labels** (built 2026-10-20): one shared vocabulary for the platform (case doesn't matter; the first spelling is kept). Pages and spaces are labelled under their title by those who can edit them; workspaces in their settings by their administrators. Typing suggests labels already used. The dashboard's **Labels** card is a cloud (the more used, the bigger) of the labels of what the viewer can see; each label opens `/labels/?name=…`, listing the workspaces, spaces and pages carrying it that the viewer can see. Items 7–10 below build on them.
5. ✅ **Profile pages** (built 2026-10-20): name, headline, organisation, location, about, website, email, interests (labels) and workspaces, each shown to its chosen audience: public on the internet, everyone on Collaborators, people I work with, or chosen workspaces and spaces. The name is always shown to the people one works with, so a profile is never fully hidden. Edited at `/account/profile/` ("My profile" in the account menu); shown at `/profile/?id=…` (public pieces also signed out), linked from the hover card of mentions. Not yet: a profile photo (initials for now).
5b. ✅ **Group badge on mentions** (built 2026-10-20): hovering a mentioned group (in pages, comments and table cells, text or Person columns) shows a card with the group's name, kind (team, organization, everyone in a workspace, or its administrators), workspace and members (managers or admins first; up to 50, then "and N more"), each linking to their profile (`GET teams/<team>/`). The member list is shown to people of that group's workspace only; others see the name alone.

5c. ✅ **Approval of new registrations** (built 2026-10-20): with `COLLABORATORS_SIGNUP_APPROVAL` (on for collaborators.community), someone signing in for the first time waits until a platform administrator (a staff user) lets them in at `/registrations/` ("New registrations" in the account menu; each registration also reaches the administrators' inbox and email). Waiting or declined, they see only a page saying where they stand (and count as signed out for the API); they're emailed when registering, and when accepted or declined; once accepted, they join what their verified email's domain or organisation opens. The verified emails of `COLLABORATORS_PLATFORM_ADMIN_EMAILS` are platform administrators let in at once; also `manage.py approve_registration <email> --admin`. Emails need the SMTP service (until then they're logged, never blocking).

5d. ✅ **Assignments anywhere, and one card for them** (built 2026-10-21): besides a table's Person cells, a person or group mentioned in a page's to-do item is assigned that item (ticking it off marks it done), and any mention in a page can be made an assignment from its menu ("Assign this to …"). The dashboard's "Mentions, notifications and assignments for me" card lists them with the inbox, newest first, beside Labels (Recent pages across, under them); empty, it says "No mentions or assignments yet."

5e. ✅ **"Page" everywhere, pages directly in a workspace** (built 2026-10-21): the interface and emails say "page" where Docs said "doc" or "document" ("Move into a page", "Delete page", "This page will be placed in the trashbin…"). A page can be moved directly into a workspace, in none of its spaces ("Move to a workspace" in its menu; its members read it, its administrators manage it), listed under the workspace's Pages in the sidebar; "Make independent" takes it out again. Outside workspaces, the sidebar's empty Pages list says "Pages of your own, outside any workspace and/or space, appear here."
5f. ✅ **Dashboard touches** (built 2026-10-21): the combined card is "Mentions, notifications, assignments"; the sidebar logo is about 20% smaller. At the very bottom of the dashboard, centred and not a card, "The hierarchical structure in CO✍️✍️ABORATORS" shows Workspace → Space → Page with one sentence and a "Learn more" link to the guide (`/guide/`, a first version to complete over time).
5h. ✅ **Simpler left panel** (built 2026-10-21): the dashboard's combined card is "Notifications"; the workspace dropdown is gone. Outside workspaces the panel shows only the lists of "My collaborations", with "Search" (the "Discover workspaces" screen) under Labels; a workspace opens from those lists, and inside it the panel starts with "← My collaborations", its name and its settings. Creating a workspace is in "New".
5g. ✅ **"New" and "My collaborations"** (built 2026-10-21): "New" offers Create a new workspace / space / page (a page goes in the workspace shown, if any; on a page, also New sub-page); importing a file is no longer offered there. "My spaces & pages" is now "My collaborations", with only its lists: Recent (the latest 6 workspaces, independent spaces and independent pages one is involved in), Notifications (everything of the dashboard card, with "Mark all as read"), Labels (the cloud and every label with its uses), Owned by me (with buttons creating each), Shared with me, Starred (workspaces can be starred now), Trashbin (`GET collaborations/?view=…`). The dashboard's two cards link to their full lists ("See all"). Following labels comes with the post-launch "label followers" (item 9).
5i. ✅ **One search, cards matching the sidebar, the panel on either side** (built 2026-10-21):
   - **Search:** the four ways in (the icons at the top of the panel and of the page, the panel's "Search" item, the dashboard's "Search" box) search workspaces, spaces, pages and labels, by name and by the text inside (`GET search/?q=`), in two groups: "Yours" (what one is part of) and "Visible to you" (what one may see without being part of it). The panel's "Search" item (formerly "Explore", same icon as the search button) opens the Search screen; with nothing typed it shows the workspaces one can ask to join and the labels (the Labels item and card are gone).
   - **Cards = sidebar:** Notifications (across, by default) and the bell show the same summary (8 entries) and "See all" leads to the Notifications screen; both end with "Also send me emails", one setting, off for everyone until they turn it on. "Recent", "Starred", "Owned by me" and "Shared with me" are summaries (3 per group) of the panel's lists, with "See all". "Add a card" offers Starred, Owned by me, Shared with me (My spaces, My workspaces and Independent pages are gone).
   - **Reordering** the panel's items is done by their handle (shown on hover); a click on an item only opens it. Default order: Recent, Notifications, Search, Starred, Owned by me, Shared with me, Trashbin (always last); once moved, a quiet "Reset the order" under the list puts it back.
   - **Panel on the right:** a slider at the bottom of the panel, between the profile and "?" buttons, moves it to the right (kept per collaborator). The panel is then mirrored (words keep their letters in order), and so are the bars over the page: the search button, Reading/Editing, Share and "…" go to the left, the comments and contents panel too.

5j. ✅ **Who sees whom, invitations by email, My CO✍️✍️ABORATORS** (built 2026-10-22):
   - **Who sees whom:** people find each other by name (user search, pickers, My CO✍️✍️ABORATORS), see each other's profile and add each other only when they share a workspace, a space or a page — the same tree (a space and its pages), through a group or a workspace. The exception is someone whose profile's "Who can find me and invite me" is "Everyone on Collaborators" or "Public on the internet". That choice also caps each piece of their profile; the default is the people they share something with. A full email finds its owner only under the same rule, otherwise it is invited by email, without telling whether it has an account (`COLLABORATORS_PEOPLE_PRIVACY`).
   - **Invitations by email** to workspaces (settings, and while creating one), spaces (while creating one, and the share dialog) and pages (share dialog), together with people found by name. The email links to `/invite/?token=…`, which shows the item's logo and name, who invites, and the Google / Microsoft / LinkedIn buttons. Once signed in (with any email), it joins at once. Invited newcomers need no approval of their registration; invitations last 7 days and can be sent again or cancelled.
   - A newcomer's account takes their invitations when it is made, before they come back to the link: the link (since 2026-10-25 it also names what it is to) then opens the workspace, space or page, instead of saying the invitation can no longer be used.
   - **Logos:** a workspace's in its settings, a space's or page's from its "…" menu ("Logo"), shown in invitations and on that page. Since 2026-11-01 also in the invitation's email, above its title (not in its plain text version), while the invitation lasts: it is read through the invitation's token, so it no longer shows once the invitation is accepted or cancelled.
   - **Invitations sent together** (built 2026-11-01): the invitations by email someone sends one person less than 2 minutes apart (`COLLABORATORS_INVITATION_BUNDLE_DELAY`, in seconds) go out as one email, 2 minutes after the last one (`InvitationBundle`, sent by a Celery task; `core/invitations.py`). A single invitation keeps its email as before. Several are listed in it, workspaces first, then spaces, then pages, each with its logo and role ("Ada invited you to Acme and 2 more"). Its link opens a page listing them: signed out, the sign-in buttons; signed in, "Accept all and join" or "Accept" for each, and those accepted then show "Open". Each invitation keeps its own role, expiry, "Send again" and "Cancel"; a cancelled one leaves the list. Invitations from different people never share an email. Signing up still takes all of one's invitations at once. Not built yet: declining an invitation.
   - **Also add them to spaces** (built 2026-11-01): above "Add a collaborator by name or email" in a workspace's settings (which adds someone as soon as they are picked, so the spaces are checked first), "Also add them to these spaces" lists the spaces of the workspace its administrator may share, each with a checkbox and the role to give. Picked by name, the person gets that role on each space checked once in the workspace; invited by email, they are invited to each too, all in the workspace invitation's email (above). A space all members already get says "Members already get it as reader" (`members_role` in the list of a workspace's spaces) and offers only the roles above; one they get as administrators is not offered. A space that could not be added is named in a toast. People added by name still get one "shared with you" email per space.
   - **My CO✍️✍️ABORATORS** (left panel, above Trashbin): everyone one may see, the people one works with first (with the workspaces shared), then those open to everyone; each opens their profile.
     - **Fixed 2026-11-01** (it looked blank): with nobody to share with, it shows "Nobody here yet", what makes people appear and a link to find a workspace to join (the people open to everyone still show below); a list that fails to load says so, with "Try again", instead of looking empty. "Sharing" now also counts a page linked into a space (the space's people may read it, so they and the page's people see each other), and no longer counts a page in the trashbin (the others lost it; restored, it counts again). Its people are computed in a fixed number of queries, however many there are (`users_sharing_documents_with`, `core/tests/collaborators/test_my_collaborators.py`, browser test `my-collaborators.spec.ts`). On collaborators.community that day, nobody shared a workspace, a space or a page with anybody else, so the list was rightly empty.
   - Also: the Notifications screen starts with "Also send me emails"; the dashboard's list cards are one plain list (the latest 6); a weekly mobile check runs (documentation/collaborators/mobile-check.js); the cover page's address is as wide as the logo above it; the panel's lists always lead to the home (not the Search address).
5k. ✅ **Table and page touches** (built 2026-10-23):
   - **Tables:** the cells of the numbers column are formatted one by one like any other cell (their "⌄", or a right-click), but never typed in. A cell's "⌄" menu, header cells included, always ends with "Clear cell formatting" (greyed out while there is nothing to clear). A column's "⋮" menu starts with "Column type" (and "Number format" for numbers), then a line. Column names have no type icon any more.
   - **Formats:** the latest choice wins, at any level (see T60).
   - **Table of contents:** optional per page and off by default: editors turn it on or off from the page's "…" menu ("Table of contents"), kept with the page's content. Off, the contents button doesn't show.
5l. ✅ **Moving blocks on a page, smoother** (built 2026-10-23), around BlockNote's own dragging by the "⠿" handle (`components/BlockMotion`):
   - the blocks being dragged are dimmed; the line where they land is thicker, in the accent colour; the copy following the pointer is a card at most 180px tall;
   - the page scrolls when a dragged block is held near its top or bottom edge;
   - moved blocks slide from where they were to their new place and light up for a moment (not the slide with "reduce motion");
   - "Move up" and "Move down" in the "⠿" menu, with BlockNote's shortcuts ⌘/Ctrl ⇧ ↑/↓ shown beside them; they slide too;
   - on touch screens, a finger resting on the "⠿" (0.4 s) picks the block up; a line shows where it will land; lifting the finger drops it. A tap still opens the menu.
   - The motion never changes the editor's own elements (ProseMirror redraws them): the dimming is a style rule, the slide and the light are animations.
5m. ✅ **What is public, checked and corrected** (job 2 of the order of work, built 2026-10-25; tests in `tests/collaborators/test_public_reach.py`):
   - A workspace's visibility only decides who finds it (Discover, search, profiles); what is readable follows roles and links (a space's or page's own, passed down to pages below unless kept private, and that of the spaces a page is linked into).
   - **Closed leaks:** a wiki logo is checked whole (a crafted one made another page's file public); files of a page kept private are no longer served through the public space above; a hidden workspace's name stays hidden (its spaces, wikis and address, which exists only if it publishes wikis); a space in the trashbin links nothing; search, linked pages, the label picker and "Starred" no longer show titles or labels of what one can't open.
   - **Settings:** a page placed in a workspace keeps its members; a shared space's setting no longer removes what another workspace granted; a live wiki stays public and read-only; leaving a workspace takes its roles from the pages below too; moving public pages into a workspace follows its publishing policy.
   - **Shown where it should:** Discover lists shared spaces and those open to everyone signed in; unpublishing a wiki gives back the space's former reach; logos and labels of public items show signed out; `robots.txt` and an `X-Robots-Tag: noindex` header keep search engines to the cover, legal and guide pages and what is published.
5n. ✅ **Spaces kept; workspaces and spaces as folders** (decided and built 2026-10-25). Spaces stay: they are a team's or topic's boundary inside a workspace, the unit published as a wiki, shared with other workspaces and linked into; what made them feel like pages was how they looked.
   - **A workspace's screen** at `/workspace/<id>/` (it showed the dashboard): its logo, name, description and labels, its settings for administrators, then its spaces as folders (with "Shared from …" for those of other workspaces) and the pages placed directly in it as documents, each with "New space" / "New page". The left panel is inside the workspace there too (it showed nothing at that address), and a workspace made after the panel's list was loaded opens from "Recent" (it was forgotten at once).
   - **A space opens as a folder:** below its own text (its introduction), its pages, and the pages linked into it ("Linked from …"), as documents, with "New page". Spaces show a folder in the page tree too.
6. **Sign-in providers in production** (Google, Microsoft and LinkedIn set up on collaborators.community 2026-10-20: the development apps with the production redirect addresses added; their credentials in the server's `env/sso.env`). Email (2026-10-20): Brevo, sending from noreply@collaborators.community (domain authenticated with DKIM; DMARC reject), for the app and Keycloak (set with `deploy/production/bin/set-smtp.sh`). Google app **published** 2026-10-25 (domain verified in Search Console by a DNS TXT record; Branding filled; In production): any Google account signs in. Originally: production redirect addresses, publishing the Google app (home page and privacy policy), a real SMTP server for Keycloak (F2, see `sso-setup.md` → Production). Locally, Google, Microsoft and LinkedIn sign-in work (apps registered 2026-10-19); Apple and X are dropped.

**After the first public version** (grant calls, built on labels):

7. **Call alerts:** notifications about upcoming grant programmes and calls matching the labels a collaborator follows.
8. **Calls dashboard:** a second dashboard of upcoming and open calls, searchable by labels.
9. **Label followers:** a third dashboard listing, per label, the collaborators who follow it and agreed "other users can discover me as a follower of this label".
10. **Following calls:** the same following and discoverability for calls themselves.
   - To decide first: where calls come from (e.g. the EU Funding & Tenders portal's public API, other funders' feeds, or entered by hand), and how often they're refreshed.

**Also wanted** (asked for 2026-10-23, not yet scheduled):

11. **Input from one's own AI tools:** besides typing on the platform, a collaborator can send content from the AI assistant they already use (ChatGPT, Claude, Gemini, Copilot…) into CO✍️✍️ABORATORS: create or update pages, fill Loop tables, add comments, labels or assignments, always as themselves and only where they may edit.
   - Possible ways in, to choose from: an MCP server (the open standard many assistants connect to), a public API with personal access tokens (also for custom GPTs and automations), a "share to" or email-in address per space or page, and pasting an assistant's answer with its formatting kept.
   - To decide first: which assistants and ways in come first; what an assistant may do (read only, draft for review, or write directly); how its changes are marked in the page history and notifications; and how tokens are given, limited per workspace and revoked.
   - **Decided and built (2026-10-26), first version:**
     - **Way in: an MCP server** at `<app>/mcp` (`core/api/mcp.py`; MCP's streamable HTTP transport, stateless JSON), for **Claude, ChatGPT and Gemini** at first (others later, on request).
     - **Access: sign-in approval.** The assistant registers itself at the sign-in server (Keycloak's dynamic client registration, allowed only for the sign-in return addresses of Claude, ChatGPT and Gemini, plus localhost for Gemini CLI), then the person signs in and approves it on Keycloak's consent screen. Its tokens are meant for the MCP server (an audience every new client gets) and name the person by email. Claude registers asking for the scopes `openid` and `basic`, and a client asking for scopes gets only those: the realm (made from an older Keycloak export) had no `basic`, so it has one carrying the email (also as `sub`) and the audience, and the registration policy allows `openid` (fixed 2026-10-26 after Claude's first attempt was refused). Set by `bin/setup-sso-providers.sh` (production: `MCP_RESOURCE` in `setup-keycloak.sh`); `/.well-known/oauth-protected-resource` points assistants to the realm, and Caddy also serves the realm's metadata at the RFC 8414 address.
     - **What an assistant may do:** find the pages the person can edit (`find_pages`), and add the person's input at the end of one (`add_input_to_page`), as a closed **toggle heading 3** titled "Input from <name> (<email>) · via <assistant> · <date>" holding the input (Markdown converted to blocks). Nothing else changes; edit rights are needed. The converter builds the update against the page's current state (`append-toggle`), the collaboration server adds it (`append-ydoc`, admin token only), credited to the person in the page history, live for everyone on the page.
     - **AI assistants**, at the bottom of the sign-in methods page (it replaced a separate "Connected assistants" page, 2026-10-26): Claude, ChatGPT and Gemini, each **Connected** (approved, with a live session at the sign-in server; "last used …" from the MCP server's record, `AssistantUse`), **Not in use** (approved, its session gone: the assistant revoked its tokens as its connector was removed, if it does, or it went unused until the session expired, about 30 days), or **Not connected**, with **Connect** (the address, with Copy, and where to paste it) or **Disconnect** (its approvals and tokens go); other assistants approved under them. Recognised by the name they registered under, else by where their sign-in returns. The backend's Keycloak service account reads clients for their names (`view-clients`).
     - **Costs:** the assistant runs on the person's own plan with its provider; Collaborators calls no AI model and neither charges nor pays for it, as the page says.
12. **Presentations in pages** (explored and decided 2026-10-28, built the same day):
   - **What it is:** a page can show an **HTML presentation** (slides made in a Claude chat, exported from Claude Design as "standalone HTML", or made any other way) that readers click through in the page and always see in its current version. The **presentation** block: "/presentation" in the slash menu (aliases slides, deck, html, embed), or pasting the address of a presentation of this site.
   - **Why not embedding Google Slides, Canva, Gamma, Figma, Pitch, Prezi or Claude Artifacts** (decided 2026-10-28, after testing each in a page): most can be framed, but none gives a PDF to readers that our server may fetch (Canva and Gamma answer it with a "verify you are human" check), and Claude Artifacts refuse to be framed by other sites (only with "Allowed domains" set by the author, on legacy chat artifacts). Presentations are HTML files instead.
   - **Two ways in** (`core/presentations.py`, `POST api/v1.0/presentations/`):
     - **stored here:** an HTML file uploaded in the block (or sent by an AI assistant). Replacing it keeps its addresses; the latest versions are kept (platform setting, 5 by default) and can be shown again ("Earlier versions"). What each person stores, every version they uploaded, has a **limit** (platform setting, 25 MB by default), told in the block; removing a presentation frees it. Files are in MinIO, under `presentations/`.
     - **a link** to an HTML file hosted anywhere public (GitHub, Netlify, Cloudflare Pages, Dropbox, Google Drive or OneDrive shared with anyone…; their share links are turned into the file's own): nothing is stored; the server fetches it when it is shown (kept 2 minutes), so it is always the one at that address. Only https, never the server's own network.
   - **Safety:** the HTML runs in a **sealed frame** (`sandbox="allow-scripts"`, no same origin; the file given as `srcdoc`, with rules first in its head: script libraries, styles and fonts from cdnjs, jsDelivr, unpkg and Google Fonts, images from anywhere, no requests of its own, no forms, no frames, no referrer). It is never served as a page of the site: `content/` gives it as text. No new domain was needed.
   - **Addresses:** `/presentation/<id>/` shows it full screen on its own (signed out too, for public pages); `/api/v1.0/presentations/<id>/pdf/` is its **PDF**. Whoever reads the page sees its presentations; whoever edits the page adds, replaces, renames, relinks, reshapes (16:9, 4:3, 1:1) or removes them (and whoever uploaded a file may remove it).
   - **Export to PDF** (the button under each presentation, and on its own page): its PDF twin when it has a current one (above); otherwise made each time by the **presentation renderer** (`src/presentation-renderer`, its own service): Chromium steps through the slides with the right arrow key, one picture per slide (a presentation that scrolls is printed instead), then a page is inserted **after the cover**: the date and time of the download in the reader's time zone, that the presentation is live and may have changed, and the PDF's permanent address (clickable) to download the current one, with the page it is shown in. In the reader's language. Slides are images (their text isn't selectable).
   - **Its PDF twin** (decided and built 2026-10-29): a PDF made **with** the HTML (by the AI that wrote it, printing one slide per page) can go with it: picked with the HTML in the block, added later ("Add its PDF", "Link to its PDF"), or sent with it by an AI assistant. That of a stored version is replaced, restored and removed with it, and counts in the person's storage; a linked presentation's can be stored here or linked too, and remembers the fingerprint of the HTML it was made for. When it is current, "Export to PDF" gives **it**, with the dated page inserted after its cover (no photographing, real text), and the block gets two tabs: **Motion** (the HTML; called "Live" until 2026-10-30) and **Slides** (the PDF page by page, with first, back, play/pause, forward and last, "3 / 12", and how many seconds each slide shows while they play, 3 by default, chosen by whoever watches; the arrow keys, Home and End too; drawn by pdf.js. Until 2026-11-01 a slider ran along the bottom; it is the Motion tab that keeps a time bar); the editor chooses which one readers see first. When the HTML changed without it (a new file alone, or the linked file changed since), it is **out of date**: editors are told so in the block, and readers get the photographed PDF until the new one comes.
   - **The time bar** (decided and built 2026-10-29): for an **animation**, an optional bar along the bottom of the Motion tab (off by default, the editor turns it on per block): play/pause, "0:12 / 0:45", and a slider to move through it. A small helper goes into the sealed frame with each presentation and only exchanges numbers with the page; it measures CSS animations and transitions and `element.animate()` when they play once, or uses the file's own handle (`window.collaboratorsTimeline`) for one driven by a script. The handle may also say where it is (`time`, `playing`), and the bar then follows the file's own clock: one that waits for its fonts starts later than the page (fixed 2026-10-29 after the demo's live check). An animation it can't measure (endless, or a script without a handle) gets no time bar, and the option isn't offered.
   - **No whole-block tint** (2026-10-30, asked after the demo went live): a click in a presentation (a tab, its slides, the time bar) selects the block, and the editor painted all of it in a tint until a click elsewhere; like the Loop table, a presentation is no longer drawn as a selected block.
   - **Bars below, not over** (2026-11-01): the time bar of the Motion tab and the buttons of the Slides tab are added under the presentation, which keeps its whole shape (16:9, 4:3 or 1:1); they used to cover its bottom edge. Full screen, the presentation takes the screen less the bar.
   - **Waits for Play** (2026-11-01): with its time bar, an animation no longer plays on its own when the page opens; it waits at its start until the reader presses Play (or moves the slider). The helper holds it from the first frame: CSS animations are paused by a rule put in before the file's own styles, those a script makes with `element.animate()` as soon as they are made, and a handle (`window.collaboratorsTimeline`) as soon as the file has set it, then again if the file starts it on its own (one waiting for its fonts). An animation it can't measure is let go, since there would be no Play. Without its time bar (off by default), an animation plays as before, since nothing would start it; nor is the full-screen page held, having no time bar.
   - **First in the "/" menu** (2026-11-01): typing "/" in a page shows Presentation first, above the headings and every other group, with no heading of its own; the rest of the menu keeps its order, and typing still narrows it ("/pres", "/head"). It used to sit among the media blocks, far down the list.
   - **Teaching the AIs** (decided and built 2026-10-29): `core/presentation_guide.py` holds the rules for making presentations that work best here: send the PDF with it, one slide per printed page (`@page`, `@media print`), a **presentation card** (`<script type="application/json" id="collaborators-presentation">{"kind": "slides", "slides": 12}</script>`, or `"animation"` with its `"seconds"`), arrow keys and clicks, measurable animations or the time handle. It is the MCP tool `presentation_guide`, the tools' descriptions point to it, and **every file sent is checked against it**: the answer lists what it misses (no card, no print rules, a card saying 12 slides for a 10-page PDF, a script animation without a handle, no PDF) so the AI fixes it. People copy the same rules from the empty block ("Copy these instructions"). The card is only a hint: what the browser measures wins.
   - **Not done:** a PowerPoint download (decided 2026-10-29: not now).
   - **AI assistants (MCP):** `publish_presentation` (in a page one edits: the HTML itself, a link, or an upload address for big files, `curl -F file=@deck.html <address>`, valid 15 minutes, once), `replace_presentation` (same address), `list_presentations` and `presentation_guide`; the HTML's PDF twin goes with it (`pdf_base64`, `pdf_link`, or `-F pdf=@deck.pdf` at the upload address). So a plain Claude chat with Collaborators connected, or Claude Code, publishes and replaces a presentation in one prompt.
   - **Elsewhere:** exports (PDF, Word, ODT) write it as its title linking to it and to its PDF; "Report this page" keeps its titles and addresses with the page's text; offline, the block says it needs a connection; the presenter mode shows it in its slide.
   - **Not done:** presenting together (one person moving the slides for everyone), and keeping uploaded presentations for offline reading.

## 5. Open questions

1. **Identity broker:** Keycloak (already in the dev stack, with all four providers built in).
2. ✅ **Hosting** (decided 2026-10-20): one Hetzner Cloud **CX33** server (4 vCPU, 8 GB RAM) running everything with Docker Compose (`deploy/production/`), files in MinIO on the same server, HTTPS by Caddy. Chosen over Render (about $105–180 a month) and managed Kubernetes (€150+) for cost; the same images can move to a bigger server or Kubernetes later.
3. ✅ **GitHub** (decided 2026-10-23, published 2026-10-25): **https://github.com/mustafa-yilmaz/collaborators**, public, a fork of suitenumerique/docs (the owner's earlier fork, renamed). `main` holds our work, with the `collaborators/phase-*` branches; Issues are on; GitHub Actions are off (Docs' own workflows would publish images and need La Suite's secrets). The history was checked for secrets before the first push: secrets stay on the server in `deploy/production/env/` and `keys/`, which are git-ignored. The home page invites people to contribute there or report an issue.
4. ✅ **Editor extras under GPL** (decided 2026-10-23): **MIT only**. Production already builds without them (`PUBLISH_AS_MIT` isn't set to `false` there), so PDF, Word and ODT export, multi-column and the AI menu are off on collaborators.community. Development builds keep them, to evaluate later which ones are really needed (each would then need its GPL licence or a BlockNote subscription).
5. ✅ **Group managers:** built (item 1 of "To do next"): group creators and the managers they appoint run their groups.
6. ✅ **Guest collaborators** (decided 2026-10-23): there is **no guest status**. Everyone is a collaborator; outsiders are invited to a workspace, space or page like anyone else (5j). Workspace roles are Owner, Administrator and Member.

---

## 6. Later (not Must-have yet)

Candidates from the five source products, to revisit after the demo: database views beyond tables (board, calendar, timeline), page templates, page verification and ownership (Confluence), page analytics, AI assistance, whiteboards and diagrams (Docmost: draw.io, Excalidraw, Mermaid), Loop-style portable components embedded in other apps, offline-first improvements, custom domains for public wikis.

---

## Appendix — Loop table sources (checked 2026-10-19)

- Microsoft 365 Insider / Tech Community:
  - [Filters](https://techcommunity.microsoft.com/t5/microsoft-365-insider-blog/introducing-filters-in-microsoft-loop-tables-and-boards/ba-p/4225058)
  - [Boards](https://techcommunity.microsoft.com/t5/microsoft-365-insider-blog/bringing-flexibility-and-customization-to-microsoft-loop-boards/ba-p/4226686)
  - [Board view](https://techcommunity.microsoft.com/blog/microsoft365insiderblog/board-visualization-for-loop-tables/4223705)
  - [Comments](https://techcommunity.microsoft.com/blog/microsoft365insiderblog/introducing-comments-in-loop-tables-and-boards/4226549)
  - [Detail view](https://techcommunity.microsoft.com/blog/microsoft365insiderblog/add-context-to-microsoft-loop-tables-and-boards-with-the-detail-view/4224014)
  - [Task lists](https://techcommunity.microsoft.com/blog/microsoft365insiderblog/improved-task-list-components-in-loop/4224232)
  - [Rules](https://techcommunity.microsoft.com/blog/microsoft365insiderblog/streamline-your-workflow-with-automation-in-microsoft-loop/4223906)
  - [Export to Excel](https://insider.microsoft365.com/en-us/blog/export-tables-to-excel-in-loop)
- Microsoft Support:
  - [Keyboard shortcuts for Loop](https://support.microsoft.com/en-us/office/keyboard-shortcuts-for-microsoft-loop-134d4c99-d28a-4d03-a5c9-0d3000011433)
  - [Loop components in Outlook](https://support.microsoft.com/en-us/office/use-loop-components-in-outlook-9b47c279-011d-4042-bd7f-8bbfca0cb136)
  - [Loop storage limits](https://support.microsoft.com/en-us/office/microsoft-loop-storage-limits-c2f1a5e9-be65-4289-b322-bae070bfb751)
- Hands-on reviews:
  - [Business Tech Planet](https://businesstechplanet.com/microsoft-loop-components-a-complete-guide-on-how-to-use-them/)
  - [Computerworld](https://www.computerworld.com/article/1621861/how-to-use-microsoft-loop-in-outlook-and-teams.html)
  - [noraajunker.ch](https://noraajunker.ch/loop-3/)
  - SharePoint Maven: [label groups](https://sharepointmaven.com/label-groups-in-microsoft-loop/), [detail pane](https://sharepointmaven.com/detail-pane-in-microsoft-loop/)
  - [XDA (column types)](https://www.xda-developers.com/10-features-microsoft-loop-needs-to-become-a-productivity-powerhouse/)
