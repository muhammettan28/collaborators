import {
  PDFArray,
  PDFDict,
  PDFDocument,
  PDFName,
  PDFString,
  StandardFonts,
} from 'pdf-lib';
import { describe, expect, it } from 'vitest';

import { slidesPdf, withNotice, wrap } from '../src/pdf.js';

import { slideJpeg, testFonts } from './_helpers.js';

const notice = {
  lines: [
    { text: 'Q4 & beyond', bold: true },
    { text: 'İndirilme tarihi: 28 Ekim 2026 09:00 (Europe/Istanbul) — çğış' },
    { text: 'Téléchargez-le à nouveau pour la version actuelle.' },
  ],
  url: 'https://collaborators.community/api/v1.0/presentations/0b7c/pdf/',
  footer: 'Shown in the page “Q4 Launch” on Collaborators',
};

const pagesOf = async (bytes: Uint8Array) => PDFDocument.load(bytes);

describe('slidesPdf', () => {
  it('makes one page per slide, at the screen size', async () => {
    const pdf = await pagesOf(
      await slidesPdf({ kind: 'slides', slides: [slideJpeg, slideJpeg, slideJpeg] }),
    );
    expect(pdf.getPageCount()).toBe(3);
    const { width, height } = pdf.getPage(0).getSize();
    expect(width).toBeCloseTo(4 / 1.5);
    expect(height).toBeCloseTo(3 / 1.5);
  });

  it('keeps a printed PDF as it is', async () => {
    const printed = await PDFDocument.create();
    printed.addPage([100, 50]);
    const bytes = await printed.save();
    expect(await slidesPdf({ kind: 'pdf', pdf: Buffer.from(bytes) })).toEqual(
      Buffer.from(bytes),
    );
  });
});

describe.skipIf(!testFonts)('withNotice', () => {
  const deck = async (pages: number) => {
    const pdf = await PDFDocument.create();
    for (let i = 0; i < pages; i++) {
      pdf.addPage([960, 540]);
    }
    return pdf.save();
  };

  it('goes second, the size of the cover, with the address clickable', async () => {
    const pdf = await pagesOf(await withNotice(await deck(4), notice, testFonts!));
    expect(pdf.getPageCount()).toBe(5);
    expect(pdf.getPage(1).getSize()).toEqual({ width: 960, height: 540 });
    const annots = pdf.getPage(1).node.lookup(PDFName.of('Annots'), PDFArray);
    const uris = annots
      .asArray()
      .map((ref) => pdf.context.lookup(ref, PDFDict))
      .map((link) => link.lookup(PDFName.of('A'), PDFDict))
      .map((action) => action.lookup(PDFName.of('URI'), PDFString).decodeText());
    expect(uris.every((uri) => uri === notice.url)).toBe(true);
    expect(uris.length).toBeGreaterThan(0);
    // the other pages have no notice
    expect(pdf.getPage(0).node.lookup(PDFName.of('Annots'))).toBeUndefined();
  });

  it('goes last after a one-page PDF', async () => {
    const pdf = await pagesOf(await withNotice(await deck(1), notice, testFonts!));
    expect(pdf.getPageCount()).toBe(2);
  });
});

describe('wrap', () => {
  it('breaks between words, and inside an address too long for a line', async () => {
    const font = await (await PDFDocument.create()).embedFont(StandardFonts.Helvetica);
    const lines = wrap(
      'Download it again from https://collaborators.community/api/v1.0/presentations/0b7c3f6a/pdf/',
      font,
      12,
      150,
    );
    expect(lines.length).toBeGreaterThan(2);
    for (const line of lines) {
      expect(font.widthOfTextAtSize(line, 12)).toBeLessThanOrEqual(150);
    }
    expect(lines.join('')).toContain('presentations/0b7c3f6a/pdf/');
  });

  it('ends even where not one letter fits', async () => {
    const font = await (await PDFDocument.create()).embedFont(StandardFonts.Helvetica);
    expect(wrap('https://x.example/pdf/', font, 12, 1).join('')).toBe(
      'https://x.example/pdf/',
    );
  });
});
