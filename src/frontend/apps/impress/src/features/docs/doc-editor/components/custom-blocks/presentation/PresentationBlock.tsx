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
import { SlidesView } from './SlidesView';
import {
  NO_PDF,
  Presentation,
  fetchPresentationGuide,
  megabytes,
  pdfWithZone,
  useChangePresentation,
  useChangePresentationPdf,
  useCreatePresentation,
  usePresentation,
  usePresentationStorage,
  usePresentationVersions,
  useRemovePresentation,
  useRestorePresentation,
} from './api';

// an HTML file, and its PDF twin with it or not
const ACCEPT = '.html,.htm,text/html,.pdf,application/pdf';
const ACCEPT_PDF = '.pdf,application/pdf';

export type View = 'live' | 'slides';

const isPdf = (file: File) =>
  file.type === 'application/pdf' || /\.pdf$/i.test(file.name);

/** The HTML file and its PDF among the files picked. */
export const pairOf = (files: File[]) => ({
  file: files.find((file) => !isPdf(file)),
  pdf: files.find(isPdf),
});

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

/** Files to send, picked from the computer: an HTML file and its PDF. */
const FileButton = ({
  label,
  disabled,
  onFiles,
}: {
  label: string;
  disabled?: boolean;
  onFiles: (files: File[]) => void;
}) => {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = '';
          if (files.length) {
            onFiles(files);
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
  fieldLabel,
  disabled,
  initial = '',
  onLink,
}: {
  label: string;
  /** What the link is of (else an HTML file) */
  fieldLabel?: string;
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
          label={
            fieldLabel ??
            t('Link to an HTML file (https://…)', {
              description:
                'Label of the link of a presentation hosted elsewhere',
            })
          }
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
  const [missing, setMissing] = useState(false);

  if (!page) {
    return null;
  }
  const add = (fields: { file?: File; pdf?: File; link?: string }) =>
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
          label={t('Upload an HTML file (and its PDF)', {
            description: 'Button adding a presentation from a file',
          })}
          disabled={create.isPending}
          onFiles={(files) => {
            const { file, pdf } = pairOf(files);
            setMissing(!file);
            if (file) {
              add({ file, pdf });
            }
          }}
        />
        <StorageLine />
      </Box>
      {missing && (
        <Text $size="sm" $css={errorCss}>
          {t('Choose the HTML file too: the PDF goes with it.', {
            description: 'Shown when only a PDF was picked for a presentation',
          })}
        </Text>
      )}
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
      <GuideButton />
    </Box>
  );
};

/**
 * "Making it with an AI?": copies the instructions for making presentations
 * that work best here (the backend's guide), to give to one's AI.
 */
const GuideButton = () => {
  const { t } = useTranslation();
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  return (
    <Box $direction="row" $gap="xs" $align="center" $wrap="wrap">
      <Text $size="xs" $variation="secondary">
        {t('Making it with an AI?', {
          description: 'Before the button copying instructions for AIs',
        })}
      </Text>
      <Button
        size="small"
        variant="tertiary"
        icon={<Icon iconName="content_copy" $size="16px" $color="inherit" />}
        onClick={() => {
          void fetchPresentationGuide()
            .then((guide) => navigator.clipboard.writeText(guide))
            .then(
              () => setState('copied'),
              () => setState('failed'),
            );
        }}
      >
        {state === 'copied'
          ? t('Copied: paste them to your AI', {
              description: 'Once the instructions for AIs are copied',
            })
          : t('Copy these instructions', {
              description: 'Button copying instructions for AIs',
            })}
      </Button>
      {state === 'failed' && (
        <Text $size="xs" $css={errorCss}>
          {t('They couldn’t be copied.', {
            description: 'When copying instructions for AIs fails',
          })}
        </Text>
      )}
    </Box>
  );
};

type Panel =
  'link' | 'pdf-link' | 'pdf-remove' | 'rename' | 'versions' | 'remove' | null;

/** Earlier stored versions, to show one again. */
const VersionsPanel = ({ presentation }: { presentation: Presentation }) => {
  const { t, i18n } = useTranslation();
  const { data } = usePresentationVersions(presentation.id, true);
  const restore = useRestorePresentation(presentation.id);
  return (
    <Box $gap="xs">
      {data?.length === 0 && (
        <Text $size="sm" $variation="secondary">
          {t('No file of it is stored here.', {
            description: 'Versions panel of a presentation with no stored file',
          })}
        </Text>
      )}
      {data?.map((version) => (
        <Box key={version.id} $direction="row" $gap="xs" $align="center">
          <Text $size="sm" $flex={1}>
            {new Date(version.created_at).toLocaleString(i18n.language)} ·{' '}
            {megabytes(version.size)}
            {version.has_pdf &&
              ` · ${t('with its PDF', {
                description: 'A stored version of a presentation with its PDF',
              })}`}
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
  view,
  timeBar,
  measured,
  onFullScreen,
  onAspectRatio,
  onView,
  onTimeBar,
  onRemoved,
}: {
  presentation: Presentation;
  aspectRatio: AspectRatio;
  /** The tab it opens on, for readers */
  view: View;
  timeBar: boolean;
  /** How long its animation lasts; 0 when it can't be measured */
  measured: number;
  onFullScreen: () => void;
  onAspectRatio: (ratio: AspectRatio) => void;
  onView: (view: View) => void;
  onTimeBar: (timeBar: boolean) => void;
  onRemoved: () => void;
}) => {
  const { t } = useTranslation();
  const [panel, setPanel] = useState<Panel>(null);
  const change = useChangePresentation(presentation.id);
  const changePdf = useChangePresentationPdf(presentation.id);
  const remove = useRemovePresentation();
  const fileInput = useRef<HTMLInputElement>(null);
  const pdfInput = useRef<HTMLInputElement>(null);
  const hasPdf = presentation.pdf.state === 'current';
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
      label: hasPdf
        ? t('Replace its PDF', {
            description: 'Menu item replacing the PDF of a presentation',
          })
        : t('Add its PDF', {
            description: 'Menu item adding the PDF of a presentation',
          }),
      icon: <Icon iconName="picture_as_pdf" $size="18px" />,
      callback: () => pdfInput.current?.click(),
      show: editable && presentation.has_content,
    },
    {
      label: t('Link to its PDF', {
        description: 'Menu item giving the link of a presentation’s PDF',
      }),
      icon: <Icon iconName="add_link" $size="18px" />,
      callback: () => setPanel('pdf-link'),
      show: editable && presentation.has_content,
    },
    {
      label: t('Remove its PDF', {
        description: 'Menu item removing the PDF of a presentation',
      }),
      icon: <Icon iconName="hide_source" $size="18px" />,
      callback: () => setPanel('pdf-remove'),
      show: editable && hasPdf,
    },
    {
      label:
        view === 'slides'
          ? t('Open on the Motion tab', {
              description: 'Menu item: readers first see the Motion tab',
            })
          : t('Open on the Slides tab', {
              description: 'Menu item: readers first see the Slides tab',
            }),
      icon: <Icon iconName="tab" $size="18px" />,
      callback: () => onView(view === 'slides' ? 'live' : 'slides'),
      show: editable && hasPdf,
    },
    {
      label: timeBar
        ? t('Hide the time bar', {
            description: 'Menu item hiding the time bar of an animation',
          })
        : t('Show the time bar', {
            description: 'Menu item showing the time bar of an animation',
          }),
      icon: <Icon iconName="timer" $size="18px" />,
      callback: () => onTimeBar(!timeBar),
      show: editable && (measured > 0 || timeBar),
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
      // also for a linked one: its files from before stay, and count
      show: editable,
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

  const error = change.error ?? changePdf.error ?? remove.error;

  return (
    <Box $gap="xs" $margin={{ top: 'xs' }}>
      <input
        ref={fileInput}
        type="file"
        accept={ACCEPT}
        multiple
        hidden
        onChange={(event) => {
          const { file, pdf } = pairOf(Array.from(event.target.files ?? []));
          event.target.value = '';
          if (file) {
            change.mutate({ file, pdf });
          } else if (pdf) {
            changePdf.mutate({ file: pdf });
          }
        }}
      />
      <input
        ref={pdfInput}
        type="file"
        accept={ACCEPT_PDF}
        hidden
        onChange={(event) => {
          const pdf = event.target.files?.[0];
          event.target.value = '';
          if (pdf) {
            changePdf.mutate({ file: pdf });
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
      {editable && presentation.pdf.state === 'outdated' && (
        <Box
          $direction="row"
          $gap="xs"
          $align="center"
          $wrap="wrap"
          data-testid="presentation-pdf-outdated"
        >
          <Icon iconName="warning" $size="16px" $variation="secondary" />
          <Text $size="xs" $variation="secondary" $flex={1}>
            {t(
              'Its PDF is out of date: it was made for an earlier file. Until you add the new one, “Export to PDF” photographs the slides.',
              {
                description:
                  'Shown to editors when a presentation’s PDF is out of date',
              },
            )}
          </Text>
          <Button
            size="small"
            variant="tertiary"
            disabled={changePdf.isPending}
            onClick={() => pdfInput.current?.click()}
          >
            {t('Add its PDF', {
              description: 'Menu item adding the PDF of a presentation',
            })}
          </Button>
        </Box>
      )}
      {panel && (
        <Box $gap="xs" $css={panelCss}>
          {panel === 'pdf-link' && (
            <LinkForm
              label={t('Use this PDF', {
                description: 'Button giving the link of a presentation’s PDF',
              })}
              fieldLabel={t('Link to its PDF (https://…)', {
                description: 'Label of the link of a presentation’s PDF',
              })}
              initial={presentation.pdf.link}
              disabled={changePdf.isPending}
              onLink={(link) =>
                changePdf.mutate({ link }, { onSuccess: () => setPanel(null) })
              }
            />
          )}
          {panel === 'pdf-remove' && (
            <Box $direction="row" $gap="xs" $align="center" $wrap="wrap">
              <Text $size="sm" $flex={1}>
                {t(
                  'Remove its PDF? “Export to PDF” will photograph the slides instead, and the Slides tab goes.',
                  {
                    description:
                      'Confirmation before removing the PDF of a presentation',
                  },
                )}
              </Text>
              <Button
                size="small"
                color="error"
                disabled={changePdf.isPending}
                onClick={() =>
                  changePdf.mutate(
                    { remove: true },
                    { onSuccess: () => setPanel(null) },
                  )
                }
              >
                {t('Remove its PDF', {
                  description: 'Menu item removing the PDF of a presentation',
                })}
              </Button>
            </Box>
          )}
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
  view,
  timeBar,
  onAspectRatio,
  onTitle,
  onView,
  onTimeBar,
  onRemoved,
}: {
  presentationId: string;
  aspectRatio: AspectRatio;
  title: string;
  view: View;
  timeBar: boolean;
  onAspectRatio: (ratio: AspectRatio) => void;
  onTitle: (title: string) => void;
  onView: (view: View) => void;
  onTimeBar: (timeBar: boolean) => void;
  onRemoved: () => void;
}) => {
  const { t } = useTranslation();
  const { data: presentation, error } = usePresentation(presentationId);
  const frame = useRef<HTMLDivElement>(null);
  // the tab shown: the one the editor chose, until the reader picks another
  const [shown, setShown] = useState<View>(view);
  const [measured, setMeasured] = useState(0);
  useEffect(() => setShown(view), [view]);

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
          pdf: NO_PDF,
          abilities: { edit: false, remove: false },
        }}
        aspectRatio={aspectRatio}
      />
    );
  }
  const hasSlides = presentation.pdf.state === 'current';
  const slides = hasSlides && shown === 'slides';
  return (
    <Box>
      {hasSlides && (
        <Box
          $direction="row"
          $gap="2xs"
          $margin={{ bottom: 'xs' }}
          role="tablist"
          aria-label={t('How to show the presentation', {
            description: 'Label of the Motion / Slides tabs of a presentation',
          })}
        >
          {(['live', 'slides'] as const).map((tab) => (
            <Button
              key={tab}
              size="small"
              variant={shown === tab ? 'secondary' : 'tertiary'}
              role="tab"
              aria-selected={shown === tab}
              onClick={() => setShown(tab)}
            >
              {tab === 'live'
                ? t('Motion', {
                    description:
                      'Tab showing the presentation itself, as it moves',
                  })
                : t('Slides', {
                    description:
                      'Tab showing the PDF of a presentation page by page',
                  })}
            </Button>
          ))}
        </Box>
      )}
      {slides ? (
        <SlidesView
          ref={frame}
          presentation={presentation}
          aspectRatio={aspectRatio}
        />
      ) : (
        <PresentationFrame
          ref={frame}
          presentation={presentation}
          aspectRatio={aspectRatio}
          timeBar={timeBar}
          onMeasured={setMeasured}
        />
      )}
      <PresentationBar
        presentation={presentation}
        aspectRatio={aspectRatio}
        view={view}
        timeBar={timeBar}
        measured={measured}
        onAspectRatio={onAspectRatio}
        onView={onView}
        onTimeBar={onTimeBar}
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
      // the tab readers see first, when it has its PDF
      view: { default: 'live' as const, values: ['live', 'slides'] as const },
      // the time bar of an animation, off unless the editor turns it on
      timeBar: { default: false },
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
              view={block.props.view}
              timeBar={block.props.timeBar}
              onAspectRatio={(aspectRatio) => update({ aspectRatio })}
              onTitle={(title) => update({ title })}
              onView={(view) => update({ view })}
              onTimeBar={(timeBar) => update({ timeBar })}
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
