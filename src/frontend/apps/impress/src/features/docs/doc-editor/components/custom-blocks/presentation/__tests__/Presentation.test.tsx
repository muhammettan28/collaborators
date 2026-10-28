import { render, screen, waitFor } from '@testing-library/react';
import fetchMock from 'fetch-mock';
import { beforeEach, describe, expect, test } from 'vitest';

import { AppWrapper } from '@/tests/utils';

import { presentationIdFromUrl } from '../PresentationBlock';
import { PresentationFrame } from '../PresentationFrame';
import { Presentation, pdfWithZone } from '../api';
import { presentationAsParagraph } from '../export';
import { sealedDocument } from '../sealedDocument';

const API = 'http://test.jest/api/v1.0';
const ID = '0b7c3f6a-1111-4222-8333-944445555666';

const presentation: Presentation = {
  id: ID,
  title: 'Q4 & beyond',
  source: 'file',
  link: '',
  page: { id: 'p-1', title: 'Q4 Launch' },
  size: 120,
  has_content: true,
  updated_at: '2026-10-28T08:00:00Z',
  view_url: `https://app.example.org/presentation/${ID}/`,
  pdf_url: `https://app.example.org/api/v1.0/presentations/${ID}/pdf/`,
  abilities: { edit: true, remove: true },
};

describe('the sealed document', () => {
  test('puts its rules first, keeping the doctype first', () => {
    const sealed = sealedDocument(
      '<!doctype html><html><head><title>T</title>',
    );
    expect(sealed).toMatch(
      /^<!doctype html><html><head><meta http-equiv="Content-Security-Policy"/,
    );
    expect(sealed).toContain("connect-src 'none'");
    expect(sealed).toContain('<meta name="referrer" content="no-referrer">');
  });

  test('gives a linked file its address as base', () => {
    expect(
      sealedDocument('<p>x</p>', 'https://ada.example.org/d.html'),
    ).toContain('<base href="https://ada.example.org/d.html">');
  });
});

describe('pasted addresses', () => {
  test('of a presentation of this site give its id', () => {
    const origin = 'https://collaborators.community';
    expect(presentationIdFromUrl(`${origin}/presentation/${ID}/`, origin)).toBe(
      ID,
    );
    expect(
      presentationIdFromUrl(
        `  ${origin}/presentation/${ID.toUpperCase()}  `,
        origin,
      ),
    ).toBe(ID);
    expect(
      presentationIdFromUrl(
        `https://elsewhere.org/presentation/${ID}/`,
        origin,
      ),
    ).toBeNull();
    expect(
      presentationIdFromUrl(`${origin}/presentation/${ID}/ and more`, origin),
    ).toBeNull();
  });
});

describe('exports', () => {
  test('write a presentation as its title, linking to it and its PDF', () => {
    const paragraph = presentationAsParagraph({
      id: 'b-1',
      props: { presentationId: ID, title: 'Q4' },
    });
    expect(paragraph.type).toBe('paragraph');
    const links = paragraph.content.filter((part) => part.type === 'link');
    expect(links.map((link) => 'href' in link && link.href)).toEqual([
      `${window.location.origin}/presentation/${ID}/`,
      `${window.location.origin}/api/v1.0/presentations/${ID}/pdf/`,
    ]);
  });

  test('the PDF address carries the reader’s time zone', () => {
    expect(pdfWithZone(presentation.pdf_url)).toMatch(
      new RegExp(
        `/pdf/\\?tz=${encodeURIComponent(Intl.DateTimeFormat().resolvedOptions().timeZone).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`,
      ),
    );
  });
});

describe('the frame', () => {
  beforeEach(() => {
    fetchMock.hardReset();
    fetchMock.mockGlobal();
  });

  test('runs the presentation sealed: scripts, but no access to the app', async () => {
    fetchMock.get(`${API}/presentations/${ID}/content/`, {
      body: '<!doctype html><title>Deck</title><p>One</p>',
      headers: { 'Content-Type': 'text/plain' },
    });
    render(<PresentationFrame presentation={presentation} />, {
      wrapper: AppWrapper,
    });

    const frame = await waitFor(() => {
      const found = screen.getByTitle('Q4 & beyond');
      expect(found.tagName).toBe('IFRAME');
      return found;
    });
    expect(frame.getAttribute('sandbox')).toBe(
      'allow-scripts allow-popups allow-popups-to-escape-sandbox',
    );
    expect(frame.getAttribute('sandbox')).not.toContain('allow-same-origin');
    expect(frame.getAttribute('srcdoc')).toContain('<p>One</p>');
    expect(frame.getAttribute('srcdoc')).toContain('Content-Security-Policy');
  });

  test('says when its file has not arrived yet', () => {
    render(
      <PresentationFrame
        presentation={{ ...presentation, has_content: false }}
      />,
      { wrapper: AppWrapper },
    );
    expect(
      screen.getByText('This presentation is waiting for its file.'),
    ).toBeInTheDocument();
  });
});
