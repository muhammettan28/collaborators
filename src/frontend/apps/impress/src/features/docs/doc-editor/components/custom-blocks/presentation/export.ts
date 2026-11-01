/**
 * Presentations seen by the exports (PDF, Word, ODT): a paragraph with the
 * presentation's title, linking to where it is shown, and to its PDF.
 */

const APP_ORIGIN = () =>
  typeof window === 'undefined' ? '' : window.location.origin;

interface PresentationBlockLike {
  id: string;
  props: { presentationId?: string; title?: string };
}

export const presentationAsParagraph = (block: PresentationBlockLike) => {
  const id = block.props.presentationId ?? '';
  const title = block.props.title || 'Presentation';
  const text = (value: string) => ({
    type: 'text' as const,
    text: value,
    styles: {},
  });
  return {
    id: block.id,
    type: 'paragraph' as const,
    props: {
      textColor: 'default',
      backgroundColor: 'default',
      textAlignment: 'left',
    },
    content: id
      ? [
          text('▶ '),
          {
            type: 'link' as const,
            href: `${APP_ORIGIN()}/presentation/${id}/`,
            content: [text(title)],
          },
          text(' · '),
          {
            type: 'link' as const,
            href: `${APP_ORIGIN()}/api/v1.0/presentations/${id}/pdf/`,
            content: [text('PDF')],
          },
        ]
      : [text(`▶ ${title}`)],
    children: [],
  };
};

/** The exporter's mappings, with presentations written as paragraphs. */
export const withPresentationMapping = <
  M extends { blockMapping: Record<string, unknown> },
>(
  mappings: Omit<M, 'blockMapping'> & {
    blockMapping: Omit<M['blockMapping'], 'presentation'>;
  },
): M => {
  const paragraphMapping = (mappings.blockMapping as Record<string, unknown>)
    .paragraph as (block: unknown, ...rest: unknown[]) => unknown;
  return {
    ...mappings,
    blockMapping: {
      ...mappings.blockMapping,
      presentation: (block: PresentationBlockLike, ...rest: unknown[]) =>
        paragraphMapping(presentationAsParagraph(block), ...rest),
    },
  } as unknown as M;
};
