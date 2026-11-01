import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import fetchMock from 'fetch-mock';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import { AppWrapper } from '@/tests/utils';

import { pairOf, presentationIdFromUrl } from '../PresentationBlock';
import { PresentationFrame } from '../PresentationFrame';
import { TIME_MESSAGE, clockTime, withTimeline } from '../TimeBar';
import { NO_PDF, Presentation, pdfWithZone } from '../api';
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
  pdf: NO_PDF,
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

describe('the time bar', () => {
  test('its helper goes in after the rules, before the file’s scripts', () => {
    const sealed = withTimeline(
      sealedDocument('<html><head><script>own()</script>'),
    );
    const helper = sealed.indexOf(TIME_MESSAGE);
    expect(helper).toBeGreaterThan(sealed.indexOf('no-referrer'));
    expect(helper).toBeLessThan(sealed.indexOf('own()'));
    expect(withTimeline('<p>unsealed</p>')).toBe('<p>unsealed</p>');
  });

  test('held, its animations wait from the first frame for Play', () => {
    const page = sealedDocument('<html><head><script>own()</script>');
    const held = withTimeline(page, true);
    const pause = held.indexOf('animation-play-state:paused!important');
    expect(pause).toBeGreaterThan(held.indexOf('no-referrer'));
    expect(pause).toBeLessThan(held.indexOf('own()'));
    expect(held).toContain('var held = true');
    expect(withTimeline(page)).not.toContain('<style data-collaborators-hold>');
    expect(withTimeline(page)).toContain('var held = false');
  });

  test('says minutes and seconds', () => {
    expect(clockTime(0)).toBe('0:00');
    expect(clockTime(65.7)).toBe('1:05');
  });
});

describe('files picked', () => {
  test('give the HTML file and its PDF, in any order', () => {
    const html = new File(['<p>'], 'deck.html', { type: 'text/html' });
    const pdf = new File(['%PDF'], 'deck.PDF', { type: '' });
    expect(pairOf([pdf, html])).toEqual({ file: html, pdf });
    expect(pairOf([pdf])).toEqual({ file: undefined, pdf });
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

  test('offers the time bar only for an animation its helper measured', async () => {
    fetchMock.get(`${API}/presentations/${ID}/content/`, {
      body: '<!doctype html><title>Deck</title><p>One</p>',
      headers: { 'Content-Type': 'text/plain' },
    });
    const measured = vi.fn();
    render(
      <PresentationFrame
        presentation={presentation}
        timeBar
        onMeasured={measured}
      />,
      { wrapper: AppWrapper },
    );
    const frame = await waitFor(() =>
      screen.getByTitle<HTMLIFrameElement>('Q4 & beyond'),
    );
    const say = (data: unknown, source: Window | null) =>
      act(() => {
        window.dispatchEvent(new MessageEvent('message', { data, source }));
      });

    // from elsewhere, or not numbers: nothing
    say({ type: TIME_MESSAGE, seconds: 45, time: 0, playing: true }, window);
    say({ type: TIME_MESSAGE, seconds: 'x', time: 0 }, frame.contentWindow);
    expect(screen.queryByTestId('presentation-time-bar')).toBeNull();

    say(
      { type: TIME_MESSAGE, seconds: 45, time: 12.3, playing: true },
      frame.contentWindow,
    );
    expect(screen.getByText('0:12 / 0:45')).toBeInTheDocument();
    expect(measured).toHaveBeenLastCalledWith(45);

    const posted = vi.spyOn(frame.contentWindow!, 'postMessage');
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    expect(posted).toHaveBeenLastCalledWith(
      { type: TIME_MESSAGE, action: 'pause', time: undefined },
      '*',
    );
    fireEvent.change(
      screen.getByRole('slider', { name: 'Time in the animation' }),
      {
        target: { value: '30' },
      },
    );
    expect(posted).toHaveBeenLastCalledWith(
      { type: TIME_MESSAGE, action: 'seek', time: 30 },
      '*',
    );

    // endless, or driven by a script without a handle: no bar
    say({ type: TIME_MESSAGE, seconds: 0, time: 0 }, frame.contentWindow);
    expect(screen.queryByTestId('presentation-time-bar')).toBeNull();
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
