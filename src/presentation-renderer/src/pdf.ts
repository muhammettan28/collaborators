import { readFileSync } from 'node:fs';

import fontkit from '@pdf-lib/fontkit';
import {
  PDFDocument,
  PDFName,
  PDFString,
  rgb,
  type PDFFont,
  type PDFPage,
} from 'pdf-lib';

import type { Capture } from './capture.js';

/** The page after the cover, as the backend words it (in the reader's language). */
export interface Notice {
  lines: { text: string; bold?: boolean }[];
  /** The permanent address of the PDF, written out and clickable */
  url: string;
  footer?: string;
}

export interface Fonts {
  regular: Uint8Array;
  bold: Uint8Array;
}

export const readFonts = (regular: string, bold: string): Fonts => ({
  regular: readFileSync(regular),
  bold: readFileSync(bold),
});

const MIN_NOTICE_WIDTH = 595;

/** The slides as a PDF, one page per slide, each the size of its picture. */
export const slidesPdf = async (captured: Capture): Promise<Uint8Array> => {
  if (captured.kind === 'pdf') {
    return captured.pdf;
  }
  const pdf = await PDFDocument.create();
  for (const slide of captured.slides) {
    // copied: pdf-lib reads the bytes from the start of their memory, which
    // a small Buffer shares with others
    const image = await pdf.embedJpg(new Uint8Array(slide));
    // pictures are taken at 1.5 times the screen's size: pages are drawn at
    // the screen's size, sharp when zoomed
    const width = image.width / 1.5;
    const height = image.height / 1.5;
    const page = pdf.addPage([width, height]);
    page.drawImage(image, { x: 0, y: 0, width, height });
  }
  return pdf.save();
};

/** Lines no wider than `width`, broken between words (or inside a long one). */
export const wrap = (
  text: string,
  font: PDFFont,
  size: number,
  width: number,
): string[] => {
  const lines: string[] = [];
  let line = '';
  const fits = (candidate: string) =>
    font.widthOfTextAtSize(candidate, size) <= width;
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const candidate = line ? `${line} ${word}` : word;
    if (fits(candidate)) {
      line = candidate;
      continue;
    }
    if (line) {
      lines.push(line);
    }
    // a word wider than a line (an address) is cut where it must be
    let rest = word;
    while (rest.length > 1 && !fits(rest)) {
      // at least one letter per line, even where none fits
      let cut = rest.length - 1;
      while (cut > 1 && !fits(rest.slice(0, cut))) {
        cut -= 1;
      }
      lines.push(rest.slice(0, cut));
      rest = rest.slice(cut);
    }
    line = rest;
  }
  if (line) {
    lines.push(line);
  }
  return lines;
};

const addLink = (
  pdf: PDFDocument,
  page: PDFPage,
  url: string,
  rect: [number, number, number, number],
) => {
  const link = pdf.context.register(
    pdf.context.obj({
      Type: 'Annot',
      Subtype: 'Link',
      Rect: rect,
      Border: [0, 0, 0],
      A: { Type: 'Action', S: 'URI', URI: PDFString.of(url) },
    }),
  );
  const existing = page.node.lookup(PDFName.of('Annots'));
  if (existing && 'push' in existing) {
    (existing as unknown as { push: (ref: unknown) => void }).push(link);
  } else {
    page.node.set(PDFName.of('Annots'), pdf.context.obj([link]));
  }
};

/**
 * The PDF with the notice as its second page (after the cover; at the end
 * of a one-page PDF), the size of the cover: its lines, then the permanent
 * address, clickable, then the footer.
 */
export const withNotice = async (
  bytes: Uint8Array,
  notice: Notice,
  fonts: Fonts,
): Promise<Uint8Array> => {
  const pdf = await PDFDocument.load(bytes);
  pdf.registerFontkit(fontkit);
  const regular = await pdf.embedFont(fonts.regular, { subset: true });
  const bold = await pdf.embedFont(fonts.bold, { subset: true });

  // the cover's shape, at least as wide as a sheet of paper
  const cover = pdf.getPage(0).getSize();
  const scale = Math.max(1, MIN_NOTICE_WIDTH / cover.width);
  const width = cover.width * scale;
  const height = cover.height * scale;
  const page = pdf.insertPage(Math.min(1, pdf.getPageCount()), [width, height]);
  page.drawRectangle({ x: 0, y: 0, width, height, color: rgb(1, 1, 1) });

  const margin = width * 0.1;
  const textWidth = width - 2 * margin;
  const size = Math.max(10, Math.round(width / 52));
  const ink = rgb(0.12, 0.12, 0.14);
  const accent = rgb(0.1, 0.3, 0.75);

  type Line = { text: string; font: PDFFont; size: number; color: typeof ink; gap: number; link?: string };
  const laid: Line[] = [];
  notice.lines.forEach((line, index) => {
    const font = line.bold ? bold : regular;
    const lineSize = index === 0 && line.bold ? size * 1.4 : size;
    wrap(line.text, font, lineSize, textWidth).forEach((text, part, all) =>
      laid.push({
        text,
        font,
        size: lineSize,
        color: ink,
        gap: part === all.length - 1 ? lineSize * 0.9 : 0,
      }),
    );
  });
  wrap(notice.url, regular, size, textWidth).forEach((text, part, all) =>
    laid.push({
      text,
      font: regular,
      size,
      color: accent,
      gap: part === all.length - 1 ? size * 1.6 : 0,
      link: notice.url,
    }),
  );
  if (notice.footer) {
    const small = size * 0.75;
    wrap(notice.footer, regular, small, textWidth).forEach((text) =>
      laid.push({ text, font: regular, size: small, color: rgb(0.4, 0.4, 0.45), gap: 0 }),
    );
  }

  const total = laid.reduce((sum, line) => sum + line.size * 1.35 + line.gap, 0);
  let y = (height + total) / 2;
  for (const line of laid) {
    y -= line.size * 1.35;
    page.drawText(line.text, {
      x: margin,
      y,
      size: line.size,
      font: line.font,
      color: line.color,
    });
    if (line.link) {
      const lineWidth = line.font.widthOfTextAtSize(line.text, line.size);
      addLink(pdf, page, line.link, [
        margin,
        y - line.size * 0.3,
        margin + lineWidth,
        y + line.size,
      ]);
    }
    y -= line.gap;
  }
  return pdf.save();
};
