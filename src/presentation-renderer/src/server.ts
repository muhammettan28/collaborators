import { createHash } from 'node:crypto';
import {
  createServer,
  type IncomingMessage,
  type ServerResponse,
} from 'node:http';

import { LRUCache } from 'lru-cache';

import { isBackend } from './auth.js';
import { capture, closeBrowser } from './capture.js';
import { config } from './config.js';
import {
  readFonts,
  slidesPdf,
  withNotice,
  type Fonts,
  type Notice,
} from './pdf.js';

// The presentation renderer: PDFs of HTML presentations, for the backend only.
//
//   POST /render  {html, baseUrl?, notice}  → application/pdf
//   GET  /ping                              → 200
//
// A browser steps through the slides (capture.ts); the slides of a file are
// kept a few minutes, so asking again only adds a fresh dated page.

interface RenderRequest {
  html?: unknown;
  baseUrl?: unknown;
  notice?: Notice;
}

class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const readJson = (request: IncomingMessage): Promise<RenderRequest> =>
  new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let size = 0;
    request.on('data', (chunk: Buffer) => {
      size += chunk.length;
      if (size > config.maxBodyBytes) {
        reject(new HttpError(413, 'Too large'));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch {
        reject(new HttpError(400, 'Not JSON'));
      }
    });
    request.on('error', reject);
  });

const isNotice = (value: unknown): value is Notice => {
  const notice = value as Notice;
  return (
    !!notice &&
    typeof notice.url === 'string' &&
    Array.isArray(notice.lines) &&
    notice.lines.every((line) => typeof line?.text === 'string')
  );
};

export interface Dependencies {
  capture: typeof capture;
  fonts: () => Fonts;
  isBackend: (header: string | undefined) => Promise<boolean>;
}

/** The request handler, with what it depends on given (tests give fakes). */
export const createHandler = (dependencies: Dependencies) => {
  const kept = new LRUCache<string, Uint8Array>({
    max: 20,
    ttl: Math.max(1, config.cacheSeconds) * 1000,
  });
  // one PDF at a time: a browser takes most of the memory it is given
  let queue: Promise<unknown> = Promise.resolve();
  let waiting = 0;

  const slidesOf = async (html: string, baseUrl: string | null) => {
    const key = createHash('sha256')
      .update(baseUrl ?? '')
      .update('\0')
      .update(html)
      .digest('hex');
    const found = config.cacheSeconds > 0 ? kept.get(key) : undefined;
    if (found) {
      return found;
    }
    if (waiting > config.queueLimit) {
      throw new HttpError(503, 'Busy');
    }
    waiting += 1;
    const turn = queue.then(async () => {
      try {
        return await slidesPdf(await dependencies.capture(html, baseUrl));
      } finally {
        waiting -= 1;
      }
    });
    queue = turn.catch(() => undefined);
    const made = await turn;
    kept.set(key, made);
    return made;
  };

  return async (request: IncomingMessage, response: ServerResponse) => {
    try {
      if (request.method === 'GET' && request.url === '/ping') {
        response.writeHead(200, { 'Content-Type': 'text/plain' }).end('pong');
        return;
      }
      if (request.method !== 'POST' || request.url !== '/render') {
        throw new HttpError(404, 'Not found');
      }
      if (!(await dependencies.isBackend(request.headers.authorization))) {
        throw new HttpError(401, 'Unauthorized');
      }
      const body = await readJson(request);
      if (typeof body.html !== 'string' || !body.html.trim()) {
        throw new HttpError(400, 'No html');
      }
      if (!isNotice(body.notice)) {
        throw new HttpError(400, 'No notice');
      }
      const baseUrl = typeof body.baseUrl === 'string' ? body.baseUrl : null;
      const slides = await slidesOf(body.html, baseUrl);
      const pdf = await withNotice(slides, body.notice, dependencies.fonts());
      response
        .writeHead(200, {
          'Content-Type': 'application/pdf',
          'Content-Length': pdf.length,
        })
        .end(Buffer.from(pdf));
    } catch (err) {
      const status = err instanceof HttpError ? err.status : 500;
      if (status === 500) {
        console.error('render failed', err);
      }
      if (!response.headersSent) {
        response
          .writeHead(status, { 'Content-Type': 'text/plain' })
          .end(err instanceof HttpError ? err.message : 'Failed');
      }
    }
  };
};

const isMain = import.meta.url === `file://${process.argv[1]}`;

if (isMain) {
  let fonts: Fonts | null = null;
  const server = createServer(
    createHandler({
      capture,
      fonts: () => (fonts ??= readFonts(config.fontPath, config.boldFontPath)),
      isBackend: (header) => isBackend(header, config.jwksUrl),
    }),
  );
  server.requestTimeout = config.renderTimeoutMs + 30_000;
  server.listen(config.port, () => {
    console.log(`presentation renderer listening on ${config.port}`);
  });
  const stop = () => {
    server.close();
    void closeBrowser().finally(() => process.exit(0));
  };
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
}
