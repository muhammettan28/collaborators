// The sealed document a presentation runs in, here as in the page.
//
// Keep it the same as the renderer's
// (src/presentation-renderer/src/frame.ts):
// the PDF must show what readers see.

const SCRIPT_HOSTS =
  'https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com';
const STYLE_HOSTS = `${SCRIPT_HOSTS} https://fonts.googleapis.com`;
const FONT_HOSTS = `${SCRIPT_HOSTS} https://fonts.gstatic.com`;

/**
 * The rules the presentation runs under: script libraries, styles and fonts
 * from the usual public hosts, images and media from anywhere public (and
 * from the file itself), and nothing else — no requests of its own, no
 * forms, no frames.
 */
export const presentationPolicy = (): string =>
  [
    "default-src 'none'",
    `script-src 'unsafe-inline' 'unsafe-eval' ${SCRIPT_HOSTS}`,
    `style-src 'unsafe-inline' ${STYLE_HOSTS}`,
    `font-src data: ${FONT_HOSTS}`,
    'img-src data: blob: https:',
    'media-src data: blob: https:',
    "connect-src 'none'",
    "form-action 'none'",
    "frame-src 'none'",
    "object-src 'none'",
  ].join('; ');

const escapeAttribute = (value: string) =>
  value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');

/**
 * The HTML with the rules first in its head (a page can't loosen them once
 * read), and, for a file hosted elsewhere, its address as the base of its
 * relative links (its own pictures). The doctype stays first, else the page
 * would be drawn in the browser's "quirks" mode.
 */
export const sealedDocument = (html: string, baseUrl?: string | null) => {
  const head =
    `<meta http-equiv="Content-Security-Policy" content="${escapeAttribute(presentationPolicy())}">` +
    // the hosts it loads from never learn which page it is shown in
    '<meta name="referrer" content="no-referrer">' +
    (baseUrl ? `<base href="${escapeAttribute(baseUrl)}">` : '');
  const headTag = /<head(\s[^>]*)?>/i.exec(html);
  if (headTag) {
    const at = headTag.index + headTag[0].length;
    return html.slice(0, at) + head + html.slice(at);
  }
  const htmlTag = /<html(\s[^>]*)?>/i.exec(html);
  if (htmlTag) {
    const at = htmlTag.index + htmlTag[0].length;
    return `${html.slice(0, at)}<head>${head}</head>${html.slice(at)}`;
  }
  const doctype = /^\s*<!doctype[^>]*>/i.exec(html);
  if (doctype) {
    const at = doctype[0].length;
    return `${html.slice(0, at)}<head>${head}</head>${html.slice(at)}`;
  }
  return `<head>${head}</head>${html}`;
};
