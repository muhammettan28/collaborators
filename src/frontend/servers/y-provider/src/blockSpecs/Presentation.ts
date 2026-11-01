import { createBlockSpec } from '@blocknote/core';

import { COLLABORATION_SERVER_ORIGIN } from '@/env';

// Collaborators: an HTML presentation shown in the page (the backend's
// core/presentations.py). Must stay in sync with the frontend's
// PresentationBlock propSchema (custom-blocks/PresentationBlock.tsx).
const presentationPropSchema = {
  presentationId: { default: '' as string },
  // kept with the block for what can't ask the backend (exports, search)
  title: { default: '' as string },
  aspectRatio: {
    default: '16:9' as const,
    values: ['16:9', '4:3', '1:1'] as const,
  },
  view: { default: 'live' as const, values: ['live', 'slides'] as const },
  timeBar: { default: false as boolean },
} as const;

const presentationConfig = {
  type: 'presentation' as const,
  propSchema: presentationPropSchema,
  content: 'none' as const,
};

const APP_ORIGIN = COLLABORATION_SERVER_ORIGIN.split(',')[0].replace(/\/$/, '');

/** Where the presentation is shown on its own, and its PDF. */
export const presentationUrls = (presentationId: string) => ({
  view: `${APP_ORIGIN}/presentation/${presentationId}/`,
  pdf: `${APP_ORIGIN}/api/v1.0/presentations/${presentationId}/pdf/`,
});

const ID = /^[0-9a-f-]{36}$/i;

// Outside the app (HTML and Markdown exports, the text of the page) a
// presentation is its title, linking to where it is shown.
const buildPresentationDom = (block: {
  props: { presentationId: string; title: string };
}) => {
  const wrapper = document.createElement('p');
  wrapper.setAttribute('data-content-type', 'presentation');
  const title = block.props.title || 'Presentation';
  if (ID.test(block.props.presentationId)) {
    const link = document.createElement('a');
    link.setAttribute(
      'href',
      presentationUrls(block.props.presentationId).view,
    );
    link.textContent = `▶ ${title}`;
    wrapper.appendChild(link);
  } else {
    wrapper.textContent = `▶ ${title}`;
  }
  return wrapper;
};

export const PresentationBlock = createBlockSpec(presentationConfig, {
  render: (block) => ({ dom: buildPresentationDom(block) }),
  toExternalHTML: (block) => ({ dom: buildPresentationDom(block) }),
});
