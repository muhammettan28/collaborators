import { diagramBlockMapping } from '@blocknote/diagram-block/pdf-exporter';
import {
  inlineMathMapping,
  mathBlockMapping,
} from '@blocknote/math-block/pdf-exporter';
import { pdfDefaultSchemaMappings } from '@blocknote/xl-pdf-exporter';

import { withLoopTableMapping } from '@/docs/doc-editor/components/custom-blocks/loop-table/export';
import { withPresentationMapping } from '@/docs/doc-editor/components/custom-blocks/presentation/export';

import {
  blockMappingCalloutPDF,
  blockMappingHeadingPDF,
  blockMappingImagePDF,
  blockMappingParagraphPDF,
  blockMappingQuotePDF,
  blockMappingTablePDF,
  blockMappingUploadLoaderPDF,
} from './blocks-mapping';
import { createInlineContentMappingInterlinkingLinkPDF } from './inline-content-mapping';
import { DocsExporterPDF } from './types';

export const getPdfDocsSchemaMappings = (
  interlinkTitles: Map<string, string>,
): DocsExporterPDF['mappings'] =>
  withPresentationMapping<DocsExporterPDF['mappings']>(
    withLoopTableMapping<
      Omit<DocsExporterPDF['mappings'], 'blockMapping'> & {
        blockMapping: Omit<
          DocsExporterPDF['mappings']['blockMapping'],
          'presentation'
        >;
      }
    >({
      ...pdfDefaultSchemaMappings,
      blockMapping: {
        ...pdfDefaultSchemaMappings.blockMapping,
        callout: blockMappingCalloutPDF,
        heading: blockMappingHeadingPDF,
        image: blockMappingImagePDF,
        paragraph: blockMappingParagraphPDF,
        quote: blockMappingQuotePDF,
        table: blockMappingTablePDF,
        // We're using the file block mapping for PDF blocks
        // The types don't match exactly but the implementation is compatible
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        pdf: pdfDefaultSchemaMappings.blockMapping.file as any,
        uploadLoader: blockMappingUploadLoaderPDF,
        // Renders the LaTeX as a vector formula (via @react-pdf/math).
        mathBlock: mathBlockMapping,
        // Renders the Mermaid source to a PNG in the browser (async mapping).
        diagram: diagramBlockMapping,
      },
      inlineContentMapping: {
        ...pdfDefaultSchemaMappings.inlineContentMapping,
        interlinkingLinkInline:
          createInlineContentMappingInterlinkingLinkPDF(interlinkTitles),
        // Inline math is rasterized to an image that flows with the text.
        math: inlineMathMapping,
        // A mention is exported as its bold "@name"
        mention: (inline, exporter) =>
          pdfDefaultSchemaMappings.inlineContentMapping.text(
            {
              type: 'text',
              text: `@${inline.props.label}`,
              styles: { bold: true },
            },
            exporter,
          ),
      },
      styleMapping: {
        ...pdfDefaultSchemaMappings.styleMapping,
        // Switch to core PDF "Courier" font to avoid relying on GeistMono
        // that is not available in italics
        code: (enabled?: boolean) =>
          enabled ? { fontFamily: 'Courier', backgroundColor: '#dcdcdc' } : {},
      },
    }),
  );
