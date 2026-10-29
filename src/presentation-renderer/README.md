# Presentation renderer

PDFs of the HTML presentations shown in Collaborators pages (the editor's
"presentation" block, `core/presentations.py` in the backend). The backend
calls it when a reader clicks **Export to PDF**:

    POST /render   {html, baseUrl?, notice}   → application/pdf
    POST /notice   {pdf (base64), notice}     → application/pdf
    POST /inspect  {pdf (base64)}             → {pages}
    GET  /ping                                → 200

`/render` photographs the slides (below). When the presentation has its PDF
twin (made with the HTML and sent with it), the backend calls `/notice`
instead: the dated page is added after its cover, no browser needed. It
calls `/inspect` when a PDF arrives, to count its pages (and refuse one that
can't be opened: damaged, or locked by a password).

## What it does

1. Opens the HTML in Chromium, sealed as in the page (`src/frame.ts`: the
   same rules as the frontend's frame — script libraries, fonts and pictures
   from public hosts, no requests of its own, no forms, no frames).
2. Steps through the slides with the right arrow key, one picture per slide,
   until the picture stops changing (the last slide), `MAX_SLIDES` or
   `RENDER_TIMEOUT_MS`, with CSS animations stilled. A page that keeps
   changing on its own (an animation played by script) is captured once
   rather than stepped through. A presentation whose slides are one below
   the other (it scrolls, the arrow changes nothing) is printed instead,
   one screen per page.
3. Inserts the **dated page** after the cover (at the end of a one-page PDF):
   the lines the backend wrote in the reader's language (when the file was
   made, that the presentation is live), the permanent address of the PDF,
   clickable, and the page it is shown in.

The slides of a file are kept `CACHE_SECONDS` (10 minutes): asking again only
adds a fresh dated page. PDFs are made one at a time; beyond `QUEUE_LIMIT`
waiting, it answers 503 (the backend says "try again in a minute").

## Security

- Only the backend may ask: a short-lived RS256 token it signs for the
  audience `presentation-renderer`, checked against its public keys
  (`JWKS_URL`).
- What a presentation can reach while drawn: data it carries, and https
  addresses on the public internet (`src/network.ts`). Never this server's
  own network — the backend, the database, the files — whatever the file
  asks; the sealed document's rules refuse its own requests first.
- Chromium runs without its own sandbox (`--no-sandbox`: a container has no
  user namespaces for it); the two locks above and an unprivileged user
  without secrets stand in for it.

## Settings

| Variable | Default | |
|---|---|---|
| `JWKS_URL` | (required) | the backend's public keys, e.g. `http://backend:8000/api/v1.0/jwks` |
| `PORT` | 3010 | |
| `CHROMIUM_PATH` | `/usr/bin/chromium` | |
| `NOTICE_FONT_PATH`, `NOTICE_BOLD_FONT_PATH` | DejaVu Sans | the dated page's fonts |
| `MAX_SLIDES` | 120 | |
| `RENDER_TIMEOUT_MS` | 90000 | |
| `QUEUE_LIMIT` | 4 | |
| `CACHE_SECONDS` | 600 | 0: never kept |
| `SLIDE_WIDTH`, `SLIDE_HEIGHT` | 1280, 720 | the screen slides are drawn on |

## Development

A standalone package, like `src/yhub-server`:

    yarn test        # Vitest; browser.spec.ts only with CHROMIUM_PATH set:
                     # CHROMIUM_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" yarn test
    yarn typecheck
    yarn lint
    yarn build
