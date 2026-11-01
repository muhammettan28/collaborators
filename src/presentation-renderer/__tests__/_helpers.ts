import { existsSync, readFileSync } from 'node:fs';

import type { Fonts } from '../src/pdf.js';

// A font with Turkish and French letters: the image's DejaVu, else one of
// macOS's; the specs that need one are skipped without.
const CANDIDATES: [string, string][] = [
  [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
  ],
  [
    '/System/Library/Fonts/Supplemental/Arial.ttf',
    '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
  ],
];

const found = CANDIDATES.find(
  ([regular, bold]) => existsSync(regular) && existsSync(bold),
);

export const testFonts: Fonts | null = found
  ? { regular: readFileSync(found[0]), bold: readFileSync(found[1]) }
  : null;

export const slideJpeg = readFileSync(
  new URL('./fixtures/slide.jpg', import.meta.url),
);
