// Every setting of the renderer, read and checked once, at import time: a
// wrong one stops the server at start rather than at the first PDF.

const integer = (name: string, dflt: number, min = 1): number => {
  const raw = process.env[name];
  if (raw === undefined || raw === '') {
    return dflt;
  }
  const value = Number(raw);
  if (!Number.isInteger(value) || value < min) {
    throw new Error(`${name} must be a whole number of at least ${min}`);
  }
  return value;
};

const required = (name: string): string => {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
};

export const config = {
  port: integer('PORT', 3010),
  // The backend's public keys: only its tokens for this service are accepted
  jwksUrl: required('JWKS_URL'),
  // Debian's chromium in the image; any Chromium or Chrome elsewhere
  chromiumPath: process.env.CHROMIUM_PATH || '/usr/bin/chromium',
  // A font with the letters of every language the notice is written in
  fontPath:
    process.env.NOTICE_FONT_PATH ||
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
  boldFontPath:
    process.env.NOTICE_BOLD_FONT_PATH ||
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
  maxBodyBytes: integer('MAX_BODY_BYTES', 16 * 1024 * 1024),
  maxSlides: integer('MAX_SLIDES', 120),
  // Each PDF, all included; longer ones stop and give what was captured
  renderTimeoutMs: integer('RENDER_TIMEOUT_MS', 90_000),
  // PDFs made one at a time; beyond this many waiting, "busy" (503)
  queueLimit: integer('QUEUE_LIMIT', 4, 0),
  // Slides of the same file are kept this long (the dated page is not)
  cacheSeconds: integer('CACHE_SECONDS', 600, 0),
  width: integer('SLIDE_WIDTH', 1280),
  height: integer('SLIDE_HEIGHT', 720),
};
