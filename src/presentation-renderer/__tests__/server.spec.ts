import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';

import { PDFDocument } from 'pdf-lib';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { Capture } from '../src/capture.js';

import { slideJpeg, testFonts } from './_helpers.js';

process.env.QUEUE_LIMIT = '0';
const { createHandler } = await import('../src/server.js');

const notice = { lines: [{ text: 'Q4', bold: true }], url: 'https://x.example/pdf/' };
let server: Server | null = null;

const start = async (capture: (html: string) => Promise<Capture>) => {
  server = createServer(
    createHandler({
      capture: vi.fn(capture),
      fonts: () => testFonts!,
      isBackend: async (header) => header === 'Bearer backend',
    }),
  );
  await new Promise<void>((resolve) => server!.listen(0, resolve));
  const { port } = server.address() as AddressInfo;
  return `http://127.0.0.1:${port}`;
};

const render = (base: string, body: unknown, auth = 'Bearer backend') =>
  fetch(`${base}/render`, {
    method: 'POST',
    headers: { Authorization: auth, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

afterEach(async () => {
  // fetch keeps its connections open, which close() would wait for
  server?.closeAllConnections();
  await new Promise((resolve) => server?.close(resolve));
  server = null;
});

describe.skipIf(!testFonts)('the renderer', () => {
  it('answers pings, and only the backend', async () => {
    const base = await start(async () => ({ kind: 'slides', slides: [slideJpeg] }));
    expect((await fetch(`${base}/ping`)).status).toBe(200);
    expect((await render(base, { html: '<p>', notice }, 'Bearer other')).status).toBe(
      401,
    );
    expect((await render(base, { html: '', notice })).status).toBe(400);
    expect((await render(base, { html: '<p>x</p>' })).status).toBe(400);
    expect((await fetch(`${base}/elsewhere`)).status).toBe(404);
  });

  it('gives the slides with the notice second, and keeps the slides', async () => {
    const capture = vi.fn(
      async (): Promise<Capture> => ({
        kind: 'slides',
        slides: [slideJpeg, slideJpeg, slideJpeg],
      }),
    );
    const base = await start(capture);
    const first = await render(base, { html: '<p>deck</p>', notice });
    expect(first.status).toBe(200);
    expect(first.headers.get('content-type')).toBe('application/pdf');
    const pdf = await PDFDocument.load(new Uint8Array(await first.arrayBuffer()));
    expect(pdf.getPageCount()).toBe(4);

    const again = await render(base, { html: '<p>deck</p>', notice });
    expect(again.status).toBe(200);
    expect(capture).toHaveBeenCalledTimes(1);
  });

  it('says it is busy rather than queueing without end', async () => {
    let release: (() => void) | null = null;
    const base = await start(
      () =>
        new Promise<Capture>((resolve) => {
          release = () => resolve({ kind: 'slides', slides: [slideJpeg] });
        }),
    );
    const first = render(base, { html: '<p>one</p>', notice });
    await vi.waitFor(() => expect(release).not.toBeNull());
    const second = await render(base, { html: '<p>two</p>', notice });
    expect(second.status).toBe(503);
    release!();
    expect((await first).status).toBe(200);
  });
});
