import { describe, expect, it } from 'vitest';

import { presentationPolicy, sealedDocument } from '../src/frame.js';

const META = 'http-equiv="Content-Security-Policy"';

describe('sealedDocument', () => {
  it('puts the rules first in the head', () => {
    const sealed = sealedDocument(
      '<!DOCTYPE html><html lang="fr"><head><title>T</title></head><body>x</body></html>',
    );
    expect(sealed.startsWith('<!DOCTYPE html><html lang="fr"><head><meta ')).toBe(
      true,
    );
    expect(sealed).toContain(META);
    expect(sealed.indexOf(META)).toBeLessThan(sealed.indexOf('<title>'));
  });

  it('makes a head when there is none, keeping the doctype first', () => {
    expect(sealedDocument('<html><body>x</body></html>')).toMatch(
      /^<html><head><meta [^]*?<\/head><body>/,
    );
    expect(sealedDocument('<!doctype html>\n<p>x</p>')).toMatch(
      /^<!doctype html><head><meta /,
    );
    expect(sealedDocument('<p>x</p>')).toMatch(/^<head><meta [^]*?<\/head><p>/);
  });

  it('gives a linked file its address as base, escaped', () => {
    const sealed = sealedDocument(
      '<head></head>',
      'https://ada.example.org/decks/q4.html?a=1&b="2"',
    );
    expect(sealed).toContain(
      '<base href="https://ada.example.org/decks/q4.html?a=1&amp;b=&quot;2&quot;">',
    );
  });

  it('lets libraries, fonts and pictures in, and nothing it asks itself', () => {
    const policy = presentationPolicy();
    expect(policy).toContain("connect-src 'none'");
    expect(policy).toContain("form-action 'none'");
    expect(policy).toContain("frame-src 'none'");
    expect(policy).toContain('https://cdnjs.cloudflare.com');
    expect(policy).toContain('https://fonts.gstatic.com');
    expect(policy).toContain('img-src data: blob: https:');
  });
});

describe('the copy in the frontend', () => {
  it('is the same code, so the PDF shows what readers see', async () => {
    const { readFileSync } = await import('node:fs');
    const body = (path: string) =>
      readFileSync(new URL(path, import.meta.url), 'utf8')
        .split('\n')
        .filter((line) => !line.startsWith('//'))
        .join('\n');
    expect(
      body(
        '../../frontend/apps/impress/src/features/docs/doc-editor/components/custom-blocks/presentation/sealedDocument.ts',
      ),
    ).toBe(body('../src/frame.ts'));
  });
});
