import { insertOrUpdateBlockForSlashMenu } from '@blocknote/core/extensions';
import { createReactBlockSpec } from '@blocknote/react';
import { Button, Input } from '@gouvfr-lasuite/ui-components';
import { TFunction } from 'i18next';
import { FormEvent, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { Box, DropdownMenu, Icon, Text } from '@/components';
import { useDocStore } from '@/docs/doc-management';

import { DocsBlockNoteEditor } from '../../../types';

import { type AspectRatio, PresentationFrame } from './PresentationFrame';
import {
  Presentation,
  megabytes,
  pdfWithZone,
  useChangePresentation,
  useCreatePresentation,
  usePresentation,
  usePresentationStorage,
  usePresentationVersions,
  useRemovePresentation,
  useRestorePresentation,
} from './api';

const ACCEPT = '.html,.htm,text/html';

const errorCss = css`
  color: var(--c--contextuals--content--semantic--error--primary);
`;

const panelCss = css`
  border: 1px solid var(--c--contextuals--border--surface--primary);
  border-radius: 6px;
  padding: var(--c--globals--spacings--sm);
`;

/** "You use 3.2 MB of your 25 MB for presentations." */
const StorageLine = () => {
  const { t } = useTranslation();
  const { data } = usePresentationStorage(true);
  if (!data) {
    return null;
  }
  return (
    <Text $size="xs" $variation="secondary">
      {t('You use {{used}} of your {{limit}} for presentations.', {
        description: 'What one stores of presentations, and one’s limit',
        used: megabytes(data.used),
        limit: megabytes(data.limit),
      })}
    </Text>
  );
};

/** An HTML file to send, picked from the computer. */
const FileButton = ({
  label,
  disabled,
  onFile,
}: {
  label: string;
  disabled?: boolean;
  onFile: (file: File) => void;
}) => {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = '';
          if (file) {
            onFile(file);
          }
        }}
      />
      <Button
        size="small"
        disabled={disabled}
        icon={<Icon iconName="upload" $size="18px" $color="inherit" />}
        onClick={() => input.current?.click()}
      >
        {label}
      </Button>
    </>
  );
};

/** A link to an HTML file hosted elsewhere, typed in. */
const LinkForm = ({
  label,
  disabled,
  initial = '',
  onLink,
}: {
  label: string;
  disabled?: boolean;
  initial?: string;
  onLink: (link: string) => void;
}) => {
  const { t } = useTranslation();
  const [link, setLink] = useState(initial);
  return (
    <Box
      as="form"
      $direction="row"
      $gap="xs"
      $align="flex-end"
      $wrap="wrap"
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        if (link.trim()) {
          onLink(link.trim());
        }
      }}
    >
      <Box $flex={1} $css="min-width: 220px;">
        <Input
          fullWidth
          type="url"
          label={t('Link to an HTML file (https://…)', {
            description: 'Label of the link of a presentation hosted elsewhere',
          })}
          value={link}
          onChange={(event) => setLink(event.target.value)}
        />
      </Box>
      <Button size="small" type="submit" disabled={disabled || !link.trim()}>
        {label}
      </Button>
    </Box>
  );
};

/** An empty block, for editors: a file of theirs, or a link. */
const PresentationSetup = ({
  onCreated,
}: {
  onCreated: (presentation: Presentation) => void;
}) => {
  const { t } = useTranslation();
  const page = useDocStore((state) => state.currentDoc);
  const create = useCreatePresentation();

  if (!page) {
    return null;
  }
  const add = (fields: { file?: File; link?: string }) =>
    create.mutate({ document: page.id, ...fields }, { onSuccess: onCreated });

  return (
    <Box $gap="sm" $css={panelCss} data-testid="presentation-setup">
      <Box $direction="row" $gap="xs" $align="center">
        <Icon iconName="slideshow" $size="22px" />
        <Text $weight="600">
          {t('Presentation', { description: 'Name of the presentation block' })}
        </Text>
      </Box>
      <Text $size="sm" $variation="secondary">
        {t(
          'An HTML presentation readers click through in the page, made with Claude or anything else: upload its file, or link to it where it is hosted.',
          { description: 'Explanation of the empty presentation block' },
        )}
      </Text>
      <Box $direction="row" $gap="xs" $align="center" $wrap="wrap">
        <FileButton
          label={t('Upload an HTML file', {
            description: 'Button adding a presentation from a file',
          })}
          disabled={create.isPending}
          onFile={(file) => add({ file })}
        />
        <StorageLine />
      </Box>
      <LinkForm
        label={t('Show it', {
          description: 'Button adding a presentation from a link',
        })}
        disabled={create.isPending}
        onLink={(link) => add({ link })}
      />
      {create.error && (
        <Text $size="sm" $css={errorCss}>
          {create.error.message}
        </Text>
      )}
    </Box>
  );
};

type Panel = 'link' | 'rename' | 'versions' | 'remove' | null;

/** Earlier stored versions, to show one again. */
const VersionsPanel = ({ presentation }: { presentation: Presentation }) => {
  const { t, i18n } = useTranslation();
  const { data } = usePresentationVersions(presentation.id, true);
  const restore = useRestorePresentation(presentation.id);
  return (
    <Box $gap="xs">
      {data?.map((version) => (
        <Box key={version.id} $direction="row" $gap="xs" $align="center">
          <Text $size="sm" $flex={1}>
            {new Date(version.created_at).toLocaleString(i18n.language)} ·{' '}
            {megabytes(version.size)}
            {version.uploaded_by && ` · ${version.uploaded_by}`}
          </Text>
          {version.current ? (
            <Text $size="sm" $variation="secondary">
              {t('Shown now', { description: 'The version shown' })}
            </Text>
          ) : (
            <Button
              size="small"
              variant="tertiary"
              disabled={restore.isPending}
              onClick={() => restore.mutate(version.id)}
            >
              {t('Show this one', {
                description: 'Button showing an earlier version again',
              })}
            </Button>
          )}
        </Box>
      ))}
      <Text $size="xs" $variation="secondary">
        {t(
          'The latest versions are kept; older ones are removed as new ones arrive.',
          { description: 'How many versions of a presentation are kept' },
        )}
      </Text>
    </Box>
  );
};

/** The bar under a presentation: its title, full screen, open, PDF; editors' menu. */
const PresentationBar = ({
  presentation,
  aspectRatio,
  onFullScreen,
  onAspectRatio,
  onRemoved,
}: {
  presentation: Presentation;
  aspectRatio: AspectRatio;
  onFullScreen: () => void;
  onAspectRatio: (ratio: AspectRatio) => void;
  onRemoved: () => void;
}) => {
  const { t } = useTranslation();
  const [panel, setPanel] = useState<Panel>(null);
  const change = useChangePresentation(presentation.id);
  const remove = useRemovePresentation();
  const fileInput = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState(presentation.title);
  const editable = presentation.abilities.edit;

  const ratios: AspectRatio[] = ['16:9', '4:3', '1:1'];
  const options = [
    {
      label: t('Replace with another file', {
        description: 'Menu item replacing a presentation by a new file',
      }),
      icon: <Icon iconName="upload" $size="18px" />,
      callback: () => fileInput.current?.click(),
      show: editable,
    },
    {
      label:
        presentation.source === 'link'
          ? t('Change the link', {
              description: 'Menu item changing the link of a presentation',
            })
          : t('Show it from a link instead', {
              description: 'Menu item showing a presentation from a link',
            }),
      icon: <Icon iconName="link" $size="18px" />,
      callback: () => setPanel('link'),
      show: editable,
    },
    {
      label: t('Rename', { description: 'Menu item renaming a presentation' }),
      icon: <Icon iconName="edit" $size="18px" />,
      callback: () => setPanel('rename'),
      show: editable,
    },
    {
      label: t('Earlier versions', {
        description: 'Menu item listing the stored versions of a presentation',
      }),
      icon: <Icon iconName="history" $size="18px" />,
      callback: () => setPanel('versions'),
      show: editable && presentation.source === 'file',
    },
    ...ratios.map((ratio, index) => ({
      label: t('Shape {{ratio}}', {
        description: 'Menu item choosing the shape of a presentation',
        ratio,
      }),
      icon: <Icon iconName="aspect_ratio" $size="18px" />,
      callback: () => onAspectRatio(ratio),
      isSelected: ratio === aspectRatio,
      showSeparator: index === 0,
      show: editable,
    })),
    {
      label: t('Remove the presentation', {
        description: 'Menu item removing a presentation and its files',
      }),
      icon: <Icon iconName="delete" $size="18px" />,
      danger: true,
      showSeparator: true,
      callback: () => setPanel('remove'),
      show: presentation.abilities.remove,
    },
  ].filter((option) => option.show);

  const error = change.error ?? remove.error;

  return (
    <Box $gap="xs" $margin={{ top: 'xs' }}>
      <input
        ref={fileInput}
        type="file"
        accept={ACCEPT}
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = '';
          if (file) {
            change.mutate({ file });
          }
        }}
      />
      <Box $direction="row" $gap="xs" $align="center" $wrap="wrap">
        <Icon iconName="slideshow" $size="18px" $variation="secondary" />
        <Text
          $size="sm"
          $weight="600"
          $flex={1}
          $css="min-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"
          title={presentation.title}
        >
          {presentation.title ||
            t('Presentation', {
              description: 'Name of the presentation block',
            })}
        </Text>
        <Button
          size="small"
          variant="tertiary"
          icon={<Icon iconName="fullscreen" $size="18px" $color="inherit" />}
          onClick={onFullScreen}
        >
          {t('Full screen', {
            description: 'Button showing a presentation full screen',
          })}
        </Button>
        <Button
          size="small"
          variant="tertiary"
          href={presentation.view_url}
          target="_blank"
          rel="noopener"
          icon={<Icon iconName="open_in_new" $size="18px" $color="inherit" />}
        >
          {t('Open', {
            description: 'Button opening a presentation on its own',
          })}
        </Button>
        <Button
          size="small"
          variant="secondary"
          href={pdfWithZone(presentation.pdf_url)}
          icon={
            <Icon iconName="picture_as_pdf" $size="18px" $color="inherit" />
          }
          data-testid="presentation-pdf"
        >
          {t('Export to PDF', {
            description: 'Button downloading a presentation as a PDF',
          })}
        </Button>
        {options.length > 0 && (
          <DropdownMenu
            options={options}
            label={t('Presentation options', {
              description: 'Label of the menu of a presentation',
            })}
          >
            <Icon iconName="more_horiz" $size="20px" />
          </DropdownMenu>
        )}
      </Box>
      {presentation.source === 'link' && (
        <Text $size="xs" $variation="secondary">
          {t('Shown from {{link}}', {
            description: 'Where a linked presentation comes from',
            link: presentation.link,
          })}
        </Text>
      )}
      {panel && (
        <Box $gap="xs" $css={panelCss}>
          {panel === 'link' && (
            <LinkForm
              label={t('Show it', {
                description: 'Button adding a presentation from a link',
              })}
              initial={presentation.link}
              disabled={change.isPending}
              onLink={(link) =>
                change.mutate({ link }, { onSuccess: () => setPanel(null) })
              }
            />
          )}
          {panel === 'rename' && (
            <Box
              as="form"
              $direction="row"
              $gap="xs"
              $align="flex-end"
              onSubmit={(event: FormEvent) => {
                event.preventDefault();
                change.mutate({ title }, { onSuccess: () => setPanel(null) });
              }}
            >
              <Box $flex={1}>
                <Input
                  fullWidth
                  label={t('Title', { description: 'Title of a presentation' })}
                  value={title}
                  maxLength={255}
                  onChange={(event) => setTitle(event.target.value)}
                />
              </Box>
              <Button size="small" type="submit" disabled={change.isPending}>
                {t('Rename', {
                  description: 'Menu item renaming a presentation',
                })}
              </Button>
            </Box>
          )}
          {panel === 'versions' && (
            <VersionsPanel presentation={presentation} />
          )}
          {panel === 'remove' && (
            <Box $direction="row" $gap="xs" $align="center" $wrap="wrap">
              <Text $size="sm" $flex={1}>
                {t(
                  'Remove this presentation and its stored files? Its addresses and its PDF will stop working.',
                  {
                    description: 'Confirmation before removing a presentation',
                  },
                )}
              </Text>
              <Button
                size="small"
                color="error"
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(presentation.id, { onSuccess: onRemoved })
                }
              >
                {t('Remove', {
                  description:
                    'Button confirming the removal of a presentation',
                })}
              </Button>
            </Box>
          )}
          <Box $direction="row" $justify="space-between" $align="center">
            <StorageLine />
            <Button
              size="small"
              variant="tertiary"
              onClick={() => setPanel(null)}
            >
              {t('Close', { description: 'Button closing a panel' })}
            </Button>
          </Box>
        </Box>
      )}
      {error && (
        <Text $size="sm" $css={errorCss}>
          {error.message}
        </Text>
      )}
    </Box>
  );
};

/** A presentation block whose presentation exists (or is being read). */
const PresentationView = ({
  presentationId,
  aspectRatio,
  title,
  onAspectRatio,
  onTitle,
  onRemoved,
}: {
  presentationId: string;
  aspectRatio: AspectRatio;
  title: string;
  onAspectRatio: (ratio: AspectRatio) => void;
  onTitle: (title: string) => void;
  onRemoved: () => void;
}) => {
  const { t } = useTranslation();
  const { data: presentation, error } = usePresentation(presentationId);
  const frame = useRef<HTMLDivElement>(null);

  // the block keeps the title, for exports and search
  useEffect(() => {
    if (presentation?.abilities.edit && presentation.title !== title) {
      onTitle(presentation.title);
    }
  }, [presentation, title, onTitle]);

  if (error) {
    return (
      <Box $css={panelCss}>
        <Text $variation="secondary">
          {error.status === 404
            ? t('This presentation was removed, or you can’t see it.', {
                description:
                  'Shown in a presentation block whose presentation is gone',
              })
            : error.message}
        </Text>
      </Box>
    );
  }
  if (!presentation) {
    return (
      <PresentationFrame
        presentation={{
          id: presentationId,
          title,
          source: 'file',
          link: '',
          page: { id: '', title: '' },
          size: null,
          has_content: false,
          updated_at: '',
          view_url: '',
          pdf_url: '',
          abilities: { edit: false, remove: false },
        }}
        aspectRatio={aspectRatio}
      />
    );
  }
  return (
    <Box>
      <PresentationFrame
        ref={frame}
        presentation={presentation}
        aspectRatio={aspectRatio}
      />
      <PresentationBar
        presentation={presentation}
        aspectRatio={aspectRatio}
        onAspectRatio={onAspectRatio}
        onRemoved={onRemoved}
        onFullScreen={() => void frame.current?.requestFullscreen?.()}
      />
    </Box>
  );
};

export const PresentationBlock = createReactBlockSpec(
  {
    type: 'presentation',
    content: 'none',
    propSchema: {
      presentationId: { default: '' as const },
      // kept with the block for what can't ask the backend (exports, search)
      title: { default: '' as const },
      aspectRatio: {
        default: '16:9' as const,
        values: ['16:9', '4:3', '1:1'] as const,
      },
    },
  },
  {
    render: ({ block, editor }) => {
      const update = (props: Partial<typeof block.props>) =>
        editor.updateBlock(block, { props });
      return (
        <Box
          $width="100%"
          contentEditable={false}
          draggable={false}
          data-testid="presentation-block"
        >
          {block.props.presentationId ? (
            <PresentationView
              presentationId={block.props.presentationId}
              aspectRatio={block.props.aspectRatio}
              title={block.props.title}
              onAspectRatio={(aspectRatio) => update({ aspectRatio })}
              onTitle={(title) => update({ title })}
              onRemoved={() => editor.removeBlocks([block])}
            />
          ) : editor.isEditable ? (
            <PresentationSetup
              onCreated={(presentation) =>
                update({
                  presentationId: presentation.id,
                  title: presentation.title,
                })
              }
            />
          ) : null}
        </Box>
      );
    },
  },
);

export const getPresentationReactSlashMenuItems = (
  editor: DocsBlockNoteEditor,
  t: TFunction<'translation', undefined>,
  group: string,
) => [
  {
    title: t('Presentation', { description: 'Name of the presentation block' }),
    onItemClick: () => {
      insertOrUpdateBlockForSlashMenu(editor, { type: 'presentation' });
    },
    aliases: [
      t('presentation', {
        description: 'Search keyword for the presentation block',
      }),
      t('slides', { description: 'Search keyword for the presentation block' }),
      t('deck', { description: 'Search keyword for the presentation block' }),
      'html',
      t('embed', { description: 'Search keyword for the presentation block' }),
    ],
    group,
    icon: <Icon iconName="slideshow" $size="18px" />,
    subtext: t('An HTML presentation readers click through', {
      description: 'Description of the presentation block in the slash menu',
    }),
  },
];

/**
 * The presentation a pasted address shows (`<this site>/presentation/<id>/`),
 * or null: pasting it in a page puts the presentation there.
 */
export const presentationIdFromUrl = (text: string, origin: string) => {
  const match = new RegExp(
    `^${origin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/presentation/([0-9a-f-]{36})/?$`,
    'i',
  ).exec(text.trim());
  return match ? match[1].toLowerCase() : null;
};
