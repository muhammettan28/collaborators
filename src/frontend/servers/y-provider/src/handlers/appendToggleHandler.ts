import * as Sentry from '@sentry/node';
import { Request, Response } from 'express';
import * as Y from 'yjs';

import { logger } from '@/utils';

import { DocsPartialBlock, editor } from './convertHandler';

const FRAGMENT = 'document-store';

interface AppendToggleBody {
  /** The page's current Yjs state, base64 encoded ("" for an empty page) */
  doc?: string;
  /** The toggle's title, e.g. "Input from Ada (ada@example.org) · via Claude" */
  title?: string;
  /** What goes inside it, as Markdown */
  markdown?: string;
}

/** Whether a block holds nothing: the editor's empty last line, say. */
const isEmptyParagraph = (container: Y.XmlElement) => {
  const content = container.get(0);
  return (
    container.length === 1 &&
    content instanceof Y.XmlElement &&
    content.nodeName === 'paragraph' &&
    content.toString().replace(/<[^>]*>/g, '') === ''
  );
};

class InvalidDocument extends Error {}

/**
 * The Yjs update adding blocks at the end of a page, computed against the
 * page's current state (base64 encoded, "" for an empty page) and touching
 * nothing else, so applying it merges with whatever editors are doing at the
 * same time (the backend hands it to the collaboration server's
 * `append-ydoc`). The blocks go before the editor's empty last line, if
 * there is one.
 */
const appendToPage = (encoded: string, blocks: DocsPartialBlock[]): Buffer => {
  const doc = new Y.Doc();
  let built: Y.Doc | null = null;
  try {
    try {
      if (encoded) {
        Y.applyUpdate(doc, Buffer.from(encoded, 'base64'));
      }
    } catch (e) {
      logger('Invalid document:', e);
      throw new InvalidDocument();
    }
    const before = Y.encodeStateVector(doc);
    // The blocks built on their own, then copied into the page
    built = editor.blocksToYDoc(blocks, FRAGMENT);
    const builtGroup = built.getXmlFragment(FRAGMENT).get(0) as Y.XmlElement;
    const page = doc.getXmlFragment(FRAGMENT);
    doc.transact(() => {
      const group = page.get(0);
      if (!(group instanceof Y.XmlElement)) {
        page.insert(0, [builtGroup.clone()]);
        return;
      }
      const containers = builtGroup
        .toArray()
        .map((container) => (container as Y.XmlElement).clone());
      const last = group.get(group.length - 1);
      if (last instanceof Y.XmlElement && isEmptyParagraph(last)) {
        group.insert(group.length - 1, containers);
      } else {
        group.push(containers);
      }
    });
    return Buffer.from(Y.encodeStateAsUpdate(doc, before));
  } finally {
    doc.destroy();
    built?.destroy();
  }
};

const send = async (
  res: Response<Uint8Array | { error: string }>,
  handler: string,
  build: () => Promise<Buffer>,
) => {
  try {
    res
      .status(200)
      .setHeader('content-type', 'application/octet-stream')
      .send(await build());
  } catch (e) {
    if (e instanceof InvalidDocument) {
      res.status(400).json({ error: 'Invalid document' });
      return;
    }
    Sentry.captureException(e, { tags: { handler } });
    logger(`${handler} failed:`, e);
    res.status(500).json({ error: 'An error occurred' });
  }
};

/**
 * Collaborators: the update adding, at the end of a page, a toggle heading 3
 * titled as given, closed, holding the Markdown converted to blocks (input
 * from one's own AI assistant).
 */
export const appendToggleHandler = async (
  req: Request<object, Uint8Array | { error: string }, AppendToggleBody>,
  res: Response<Uint8Array | { error: string }>,
) => {
  const { doc: encoded = '', title = '', markdown = '' } = req.body ?? {};
  if (!title.trim() || !markdown.trim()) {
    res.status(400).json({ error: 'A title and some content are needed' });
    return;
  }
  await send(res, 'append-toggle', async () =>
    appendToPage(encoded, [
      // A toggle heading 3, as the owner chose for input from assistants
      {
        type: 'heading',
        props: { level: 3, isToggleable: true },
        content: [{ type: 'text', text: title.trim(), styles: {} }],
        children: await editor.tryParseMarkdownToBlocks(markdown),
      },
    ]),
  );
};

interface AppendBlocksBody {
  /** The page's current Yjs state, base64 encoded ("" for an empty page) */
  doc?: string;
  /** The blocks, as BlockNote's JSON (e.g. a presentation block) */
  blocks?: DocsPartialBlock[];
}

// What the backend adds this way; anything else is refused
const APPENDABLE_BLOCKS = new Set(['presentation']);

/**
 * Collaborators: the update adding blocks at the end of a page (a
 * presentation published by one's AI assistant).
 */
export const appendBlocksHandler = async (
  req: Request<object, Uint8Array | { error: string }, AppendBlocksBody>,
  res: Response<Uint8Array | { error: string }>,
) => {
  const { doc: encoded = '', blocks } = req.body ?? {};
  if (
    !Array.isArray(blocks) ||
    blocks.length === 0 ||
    !blocks.every((block) => APPENDABLE_BLOCKS.has(String(block?.type)))
  ) {
    res.status(400).json({ error: 'Blocks of a known type are needed' });
    return;
  }
  await send(res, 'append-blocks', async () => appendToPage(encoded, blocks));
};
