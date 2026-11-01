import {
  BlockNoteSchema,
  defaultBlockSpecs,
  defaultInlineContentSpecs,
  withPageBreak,
} from '@blocknote/core';

import { CalloutBlock } from './Callout';
import { InterlinkingLinkInline } from './InterlinkingLinkInline';
import { LoopTableBlock } from './LoopTable';
import { MentionInline } from './Mention';
import { PdfBlock } from './Pdf';
import { PresentationBlock } from './Presentation';
import { UploadLoaderBlock } from './UploadLoader';

// Must stay in sync with the frontend schema (BlockNoteEditor.tsx) so Yjs
// documents authored client-side round-trip without dropping nodes.
export const docsBlockNoteSchema = withPageBreak(
  BlockNoteSchema.create({
    blockSpecs: {
      ...defaultBlockSpecs,
      callout: CalloutBlock(),
      loopTable: LoopTableBlock(),
      pdf: PdfBlock(),
      presentation: PresentationBlock(),
      uploadLoader: UploadLoaderBlock(),
    },
    inlineContentSpecs: {
      ...defaultInlineContentSpecs,
      interlinkingLinkInline: InterlinkingLinkInline,
      mention: MentionInline,
    },
  }),
);

export type DocsBlockSchema = typeof docsBlockNoteSchema.blockSchema;
export type DocsInlineContentSchema =
  typeof docsBlockNoteSchema.inlineContentSchema;
export type DocsStyleSchema = typeof docsBlockNoteSchema.styleSchema;
