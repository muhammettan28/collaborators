import request from 'supertest';
import { describe, expect, test, vi } from 'vitest';
import * as Y from 'yjs';

vi.mock('../src/env', async (importOriginal) => {
  return {
    ...(await importOriginal()),
    COLLABORATION_SERVER_ORIGIN: 'http://localhost:3000',
  };
});

import { editor } from '@/handlers';
import { initApp } from '@/servers';

import { JWKS_URL } from '../src/env';

import { mockJwksEndpoint, signAdminToken } from './testUtils/adminJwt';

const apiKey = await signAdminToken();
const ID = '0b7c3f6a-1111-4222-8333-944445555666';
const presentation = {
  type: 'presentation',
  props: { presentationId: ID, title: 'Q4 & beyond' },
};

const pageOf = async (markdown: string) =>
  editor.blocksToYDoc(
    await editor.tryParseMarkdownToBlocks(markdown),
    'document-store',
  );

const append = (body: object) => {
  mockJwksEndpoint(JWKS_URL);
  return request(initApp())
    .post('/api/append-blocks/')
    .set('authorization', `Bearer ${apiKey}`)
    .send(body)
    .buffer(true)
    .parse((res, callback) => {
      const chunks: Buffer[] = [];
      res.on('data', (chunk: Buffer) => chunks.push(chunk));
      res.on('end', () => callback(null, Buffer.concat(chunks)));
    });
};

describe('append-blocks', () => {
  test('adds a presentation at the end of the page', async () => {
    const page = await pageOf('# Plan\n\nFirst paragraph.');
    const response = await append({
      doc: Buffer.from(Y.encodeStateAsUpdate(page)).toString('base64'),
      blocks: [presentation],
    });

    expect(response.status).toBe(200);
    Y.applyUpdate(page, response.body as Buffer);
    const blocks = editor.yDocToBlocks(page, 'document-store');
    const added = blocks[blocks.length - 1];
    expect(blocks.map((block) => block.type)).toEqual([
      'heading',
      'paragraph',
      'presentation',
    ]);
    expect(added.props).toMatchObject({
      presentationId: ID,
      title: 'Q4 & beyond',
      aspectRatio: '16:9',
    });
  });

  test('starts an empty page with it', async () => {
    const response = await append({ doc: '', blocks: [presentation] });
    expect(response.status).toBe(200);
    const page = new Y.Doc();
    Y.applyUpdate(page, response.body as Buffer);
    expect(editor.yDocToBlocks(page, 'document-store')[0].type).toBe(
      'presentation',
    );
  });

  test('takes only the blocks the backend adds this way', async () => {
    expect(
      (await append({ doc: '', blocks: [{ type: 'paragraph' }] })).status,
    ).toBe(400);
    expect((await append({ doc: '', blocks: [] })).status).toBe(400);
    expect((await append({ doc: '' })).status).toBe(400);
    expect(
      (await append({ doc: 'not yjs!', blocks: [presentation] })).status,
    ).toBe(400);
  });

  test('is for the backend only', async () => {
    mockJwksEndpoint(JWKS_URL);
    const response = await request(initApp())
      .post('/api/append-blocks/')
      .send({ doc: '', blocks: [presentation] });
    expect(response.status).toBe(401);
  });
});

describe('a presentation outside the app', () => {
  test('is its title, linking to where it is shown', async () => {
    const markdown = await editor.blocksToMarkdownLossy([
      presentation as never,
    ]);
    expect(markdown).toContain(
      `[▶ Q4 & beyond](http://localhost:3000/presentation/${ID}/)`,
    );
  });
});
