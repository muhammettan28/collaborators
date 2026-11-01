import { baseKeymap, toggleMark } from '@tiptap/pm/commands';
import { keymap } from '@tiptap/pm/keymap';
import { MarkType } from '@tiptap/pm/model';
import {
  EditorState,
  Selection,
  TextSelection,
  Transaction,
} from '@tiptap/pm/state';
import { EditorView } from '@tiptap/pm/view';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import * as Y from 'yjs';

import { EmojiPicker, Icon } from '@/components';
import { getEmojidata } from '@/components/Emoji/initEmojiCallout';
import { useUploadImage } from '@/docs/doc-editor/hook/useUploadImage';

import { PersonPicker } from './PersonPicker';
import { Popover } from './Popover';
import { InlineRef, cellAnchor, notifyCell } from './mentions';
import { Column, getTextCell } from './model';
import {
  RichRun,
  TEXT_COLORS,
  docToRuns,
  readRuns,
  richSchema,
  runsToDoc,
  safeLink,
  writeRuns,
} from './richText';
import { LABEL_COLORS } from './styles';

export type EditorMove = 'up' | 'down' | 'left' | 'right' | 'next' | 'prev';

type Panel =
  'mention' | 'slash' | 'date' | 'label' | 'emoji' | 'image' | 'link' | 'color';

interface RichCellEditorProps {
  table: Y.Map<unknown>;
  tableId: string;
  docId: string;
  rowId: string;
  column: Column;
  /** Leave editing, optionally moving the active cell. */
  onStopEdit: (move?: EditorMove) => void;
}

const sameRuns = (a: RichRun[], b: RichRun[]) =>
  JSON.stringify(a) === JSON.stringify(b);

const { marks } = richSchema;

/** Whether a mark covers the whole selection (or the caret). */
const isMarkActive = (state: EditorState, type: MarkType) => {
  const { from, to, empty, $from } = state.selection;
  if (empty) {
    return !!type.isInSet(state.storedMarks || $from.marks());
  }
  return state.doc.rangeHasMark(from, to, type);
};

/** "@" and "/" open their menus at the start of a word only. */
const isWordStart = (state: EditorState, at: number) => {
  const before = state.doc.textBetween(Math.max(0, at - 1), at, '\n', '￼');
  return !before || /\s/.test(before);
};

/**
 * The editor of a Text cell: rich text (bold, italic, underline, strike,
 * code, colours, links) with line breaks (Shift+Enter), "@" for people,
 * groups and pages, and "/" for inline elements (person, page, date, label,
 * emoji, image). Every change is written to the cell's Y.Text right away,
 * and the changes other people make to it show while editing.
 */
export const RichCellEditor = ({
  table,
  tableId,
  docId,
  rowId,
  column,
  onStopEdit,
}: RichCellEditorProps) => {
  const { t } = useTranslation();
  const hostRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const [panel, setPanel] = useState<Panel | null>(null);
  const panelRef = useRef<Panel | null>(null);
  panelRef.current = panel;
  const stopRef = useRef(onStopEdit);
  stopRef.current = onStopEdit;
  // The selection's place on screen, for the formatting bar
  const [bar, setBar] = useState<{ top: number; left: number } | null>(null);
  const [, setTick] = useState(0);

  const openPanel = (next: Panel) => {
    panelRef.current = next;
    setPanel(next);
  };

  /** Close a menu; back to typing unless the click went somewhere else. */
  const closePanel = () => {
    panelRef.current = null;
    setPanel(null);
    requestAnimationFrame(() => {
      const view = viewRef.current;
      const focused = document.activeElement;
      if (
        view &&
        !view.isDestroyed &&
        (!focused || focused === document.body)
      ) {
        view.focus();
      }
    });
  };

  const run = (command: (view: EditorView) => void) => {
    const view = viewRef.current;
    if (view && !view.isDestroyed) {
      command(view);
    }
  };

  const toggle = (type: MarkType) =>
    run((view) => {
      toggleMark(type)(view.state, view.dispatch);
      view.focus();
    });

  /** Set (or with no value, clear) a colour or background on the selection. */
  const setColorMark = (type: MarkType, value: string | null) =>
    run((view) => {
      const { from, to, empty } = view.state.selection;
      let tr = view.state.tr;
      if (empty) {
        tr = value
          ? tr.addStoredMark(type.create({ value }))
          : tr.removeStoredMark(type);
      } else {
        tr = tr.removeMark(from, to, type);
        if (value) {
          tr = tr.addMark(from, to, type.create({ value }));
        }
      }
      view.dispatch(tr);
    });

  const insertToken = (ref: InlineRef) => {
    run((view) => {
      const node = richSchema.nodes.token.create(ref);
      view.dispatch(
        view.state.tr.replaceSelectionWith(node, true).insertText(' '),
      );
    });
    // People and groups are notified; other elements have no one to tell
    if (docId && (ref.kind === 'user' || ref.kind === 'group')) {
      void notifyCell(
        docId,
        cellAnchor(tableId, rowId, column.id),
        { kind: ref.kind, id: ref.id, label: ref.label },
        'mention',
      ).catch(() => undefined);
    }
    closePanel();
  };

  const insertText = (text: string) => {
    run((view) => view.dispatch(view.state.tr.insertText(text)));
    closePanel();
  };

  useEffect(() => {
    const host = hostRef.current;
    const ytext = getTextCell(table, rowId, column.id);
    if (!host || !ytext) {
      return;
    }
    let writing = false;

    const placeBar = (view: EditorView) => {
      const { from, to, empty } = view.state.selection;
      if (empty || !view.hasFocus()) {
        setBar(null);
        return;
      }
      const start = view.coordsAtPos(from);
      const end = view.coordsAtPos(to);
      setBar({ top: Math.min(start.top, end.top), left: start.left });
    };

    const stop = (move?: EditorMove) => () => {
      stopRef.current(move);
      return true;
    };
    const view: EditorView = new EditorView(host, {
      state: EditorState.create({
        doc: runsToDoc(readRuns(ytext)),
        plugins: [
          keymap({
            'Mod-b': toggleMark(marks.bold),
            'Mod-i': toggleMark(marks.italic),
            'Mod-u': toggleMark(marks.underline),
            'Mod-Shift-x': toggleMark(marks.strike),
            'Mod-Shift-s': toggleMark(marks.strike),
            'Mod-e': toggleMark(marks.code),
            'Mod-k': () => {
              openPanel('link');
              return true;
            },
            'Shift-Enter': (state, dispatch) => {
              dispatch?.(
                state.tr
                  .replaceSelectionWith(richSchema.nodes.hard_break.create())
                  .scrollIntoView(),
              );
              return true;
            },
            Enter: stop('down'),
            Tab: stop('next'),
            'Shift-Tab': stop('prev'),
            Escape: stop(),
          }),
          keymap(baseKeymap),
        ],
      }),
      attributes: {
        class: 'loop-table__input loop-table__rich-input',
        role: 'textbox',
        'aria-multiline': 'true',
        'aria-label': t('Cell text', {
          description: 'Accessible name of a text cell being edited',
        }),
      },
      handleTextInput: (editor, from, to, text) => {
        // The text typed may come in one piece (input methods): only its
        // last character is the trigger
        const trigger = text.slice(-1);
        if (trigger !== '@' && trigger !== '/') {
          return false;
        }
        const head = text.slice(0, -1);
        if (
          head ? !/\s/.test(head.slice(-1)) : !isWordStart(editor.state, from)
        ) {
          return false;
        }
        if (head || from !== to) {
          editor.dispatch(editor.state.tr.insertText(head, from, to));
        }
        openPanel(trigger === '@' ? 'mention' : 'slash');
        return true;
      },
      handleDOMEvents: {
        blur: (_editor, event) => {
          const next = event.relatedTarget as Element | null;
          // Into one of the cell's own menus: still editing
          if (panelRef.current || next?.closest('.loop-table__popover')) {
            return false;
          }
          setBar(null);
          stopRef.current();
          return false;
        },
      },
      handleClickOn: (_editor, _pos, _node, _nodePos, event) => {
        // Links open from a cell being edited with Ctrl or Cmd
        const link = (event.target as Element).closest('a');
        if (link && (event.metaKey || event.ctrlKey)) {
          window.open(link.getAttribute('href') ?? '', '_blank', 'noopener');
          return true;
        }
        return false;
      },
      dispatchTransaction: (tr: Transaction) => {
        const state = view.state.apply(tr);
        view.updateState(state);
        if (tr.docChanged) {
          writing = true;
          writeRuns(ytext, docToRuns(state.doc));
          writing = false;
        }
        placeBar(view);
        setTick((tick) => tick + 1);
      },
    });
    viewRef.current = view;

    // The caret goes to the end, as when typing into a cell
    view.dispatch(view.state.tr.setSelection(Selection.atEnd(view.state.doc)));
    view.focus();

    // Edits from other people (and undo) show in the editor
    const onRemote = () => {
      if (writing || view.isDestroyed) {
        return;
      }
      const runs = readRuns(ytext);
      if (sameRuns(runs, docToRuns(view.state.doc))) {
        return;
      }
      const doc = runsToDoc(runs);
      const { from, to } = view.state.selection;
      const tr = view.state.tr.replaceWith(
        0,
        view.state.doc.content.size,
        doc.content,
      );
      const size = tr.doc.content.size;
      tr.setSelection(
        TextSelection.create(tr.doc, Math.min(from, size), Math.min(to, size)),
      );
      view.updateState(view.state.apply(tr));
    };
    ytext.observe(onRemote);
    return () => {
      ytext.unobserve(onRemote);
      viewRef.current = null;
      view.destroy();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [table, rowId, column.id]);

  const state = viewRef.current?.state;
  const active = (type: MarkType) => !!state && isMarkActive(state, type);
  const linkHref = (() => {
    if (!state) {
      return '';
    }
    const { $from } = state.selection;
    const mark = marks.link.isInSet($from.marks());
    return mark ? String(mark.attrs.href) : '';
  })();

  return (
    <div className="loop-table__rich-editor">
      <div ref={hostRef} />
      {bar &&
        !panel &&
        createPortal(
          <FormatBar
            top={bar.top}
            left={bar.left}
            isActive={active}
            onToggle={toggle}
            onColor={() => openPanel('color')}
            onLink={() => openPanel('link')}
          />,
          document.body,
        )}
      {panel === 'color' && (
        <Popover
          onClose={closePanel}
          label={t('Text colour', {
            description: 'Accessible name of the colour menu of a text cell',
          })}
        >
          <ColorMenu
            onPick={(type, value) => {
              setColorMark(
                type === 'text' ? marks.color : marks.background,
                value,
              );
              closePanel();
            }}
          />
        </Popover>
      )}
      {panel === 'link' && (
        <LinkPanel
          initial={linkHref}
          onApply={(href) => {
            run((view) => {
              const { from, to, empty } = view.state.selection;
              let tr = view.state.tr;
              if (!href) {
                // Remove the link around the caret or in the selection
                const $pos = view.state.selection.$from;
                const start = empty ? $pos.start() : from;
                const end = empty ? $pos.end() : to;
                tr = tr.removeMark(start, end, marks.link);
              } else if (empty) {
                tr = tr.insert(
                  from,
                  richSchema.text(href, [marks.link.create({ href })]),
                );
              } else {
                tr = tr.addMark(from, to, marks.link.create({ href }));
              }
              view.dispatch(tr);
            });
            closePanel();
          }}
          onClose={closePanel}
        />
      )}
      {panel === 'mention' && (
        <PersonPicker
          docId={docId}
          value={[]}
          onChange={(people) => people[0] && insertToken(people[0])}
          onPickPage={insertToken}
          onClose={closePanel}
        />
      )}
      {panel === 'slash' && (
        <SlashMenu
          onPick={(next) => openPanel(next)}
          onClose={() => {
            // Escape keeps the "/" that was typed
            insertText('/');
          }}
        />
      )}
      {panel === 'date' && (
        <DatePanel
          onPick={(iso) => insertToken({ kind: 'date', id: iso, label: iso })}
          onClose={closePanel}
        />
      )}
      {panel === 'label' && (
        <LabelPanel
          onPick={(label, color) =>
            insertToken({ kind: 'label', id: color, label })
          }
          onClose={closePanel}
        />
      )}
      {panel === 'emoji' && (
        <Popover
          onClose={closePanel}
          label={t('Emoji', {
            description: 'Accessible name of the emoji picker of a text cell',
          })}
        >
          <div className="loop-table__emoji">
            <EmojiPicker
              emojiData={getEmojidata()}
              onClickOutside={closePanel}
              onEmojiSelect={({ native }) => insertText(native)}
            />
          </div>
        </Popover>
      )}
      {panel === 'image' && (
        <ImagePanel
          docId={docId}
          onPick={(address, name) =>
            insertToken({ kind: 'image', id: address, label: name })
          }
          onClose={closePanel}
        />
      )}
    </div>
  );
};

// -- The formatting bar, above a selection

const FormatBar = ({
  top,
  left,
  isActive,
  onToggle,
  onColor,
  onLink,
}: {
  top: number;
  left: number;
  isActive: (type: MarkType) => boolean;
  onToggle: (type: MarkType) => void;
  onColor: () => void;
  onLink: () => void;
}) => {
  const { t } = useTranslation();
  const buttons: {
    type?: MarkType;
    icon: string;
    label: string;
    onClick: () => void;
  }[] = [
    {
      type: marks.bold,
      icon: 'format_bold',
      label: t('Bold', { description: 'Text cell formatting' }),
      onClick: () => onToggle(marks.bold),
    },
    {
      type: marks.italic,
      icon: 'format_italic',
      label: t('Italic', { description: 'Text cell formatting' }),
      onClick: () => onToggle(marks.italic),
    },
    {
      type: marks.underline,
      icon: 'format_underlined',
      label: t('Underline', { description: 'Text cell formatting' }),
      onClick: () => onToggle(marks.underline),
    },
    {
      type: marks.strike,
      icon: 'strikethrough_s',
      label: t('Strikethrough', { description: 'Text cell formatting' }),
      onClick: () => onToggle(marks.strike),
    },
    {
      type: marks.code,
      icon: 'code',
      label: t('Code', { description: 'Text cell formatting' }),
      onClick: () => onToggle(marks.code),
    },
    {
      icon: 'format_color_text',
      label: t('Colour', { description: 'Text cell formatting' }),
      onClick: onColor,
    },
    {
      type: marks.link,
      icon: 'link',
      label: t('Link', { description: 'Text cell formatting' }),
      onClick: onLink,
    },
  ];
  return (
    <div
      className="loop-table__popover loop-table__format-bar"
      role="toolbar"
      aria-label={t('Text formatting', {
        description: 'Accessible name of the formatting bar of a text cell',
      })}
      style={{
        position: 'fixed',
        top: Math.max(8, top - 44),
        left: Math.max(8, Math.min(left, window.innerWidth - 300)),
      }}
    >
      {buttons.map((button) => (
        <button
          key={button.icon}
          type="button"
          className={`loop-table__format-button ${
            button.type && isActive(button.type) ? 'is-active' : ''
          }`}
          aria-label={button.label}
          aria-pressed={button.type ? isActive(button.type) : undefined}
          title={button.label}
          // Keep the selection in the cell
          onMouseDown={(event) => event.preventDefault()}
          onClick={button.onClick}
        >
          <Icon iconName={button.icon} $size="18px" />
        </button>
      ))}
    </div>
  );
};

const ColorMenu = ({
  onPick,
}: {
  onPick: (type: 'text' | 'background', value: string | null) => void;
}) => {
  const { t } = useTranslation();
  const names = Object.keys(TEXT_COLORS);
  return (
    <div className="loop-table__color-menu">
      <div className="loop-table__popover-heading">
        {t('Text colour', { description: 'Text cell colour menu section' })}
      </div>
      <div className="loop-table__swatches">
        <button
          type="button"
          className="loop-table__swatch"
          aria-label={t('Default', { description: 'Default text colour' })}
          title={t('Default', { description: 'Default text colour' })}
          onClick={() => onPick('text', null)}
        >
          A
        </button>
        {names.map((name) => (
          <button
            key={name}
            type="button"
            className="loop-table__swatch"
            style={{ color: TEXT_COLORS[name].text }}
            aria-label={name}
            title={name}
            onClick={() => onPick('text', name)}
          >
            A
          </button>
        ))}
      </div>
      <div className="loop-table__popover-heading">
        {t('Highlight', { description: 'Text cell colour menu section' })}
      </div>
      <div className="loop-table__swatches">
        <button
          type="button"
          className="loop-table__swatch"
          aria-label={t('None', { description: 'No highlight colour' })}
          title={t('None', { description: 'No highlight colour' })}
          onClick={() => onPick('background', null)}
        >
          <Icon iconName="format_color_reset" $size="16px" />
        </button>
        {names.map((name) => (
          <button
            key={name}
            type="button"
            className="loop-table__swatch"
            style={{ background: TEXT_COLORS[name].background }}
            aria-label={name}
            title={name}
            onClick={() => onPick('background', name)}
          />
        ))}
      </div>
    </div>
  );
};

const LinkPanel = ({
  initial,
  onApply,
  onClose,
}: {
  initial: string;
  onApply: (href: string) => void;
  onClose: () => void;
}) => {
  const { t } = useTranslation();
  const [value, setValue] = useState(initial);
  const href = safeLink(value);
  return (
    <Popover
      onClose={onClose}
      label={t('Link', { description: 'Accessible name of the link panel' })}
    >
      <form
        className="loop-table__panel-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (href) {
            onApply(href);
          }
        }}
      >
        <input
          autoFocus
          type="text"
          inputMode="url"
          placeholder={t('Paste or type a link', {
            description: 'Placeholder of the link field of a text cell',
          })}
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <button
          type="submit"
          className="loop-table__panel-button"
          disabled={!href}
        >
          {t('Apply', { description: 'Applies a link in a text cell' })}
        </button>
        {initial && (
          <button
            type="button"
            className="loop-table__panel-button is-secondary"
            onClick={() => onApply('')}
          >
            {t('Remove', { description: 'Removes a link in a text cell' })}
          </button>
        )}
      </form>
    </Popover>
  );
};

const SlashMenu = ({
  onPick,
  onClose,
}: {
  onPick: (panel: Panel) => void;
  onClose: () => void;
}) => {
  const { t } = useTranslation();
  const items: { panel: Panel; icon: string; label: string }[] = [
    {
      panel: 'mention',
      icon: 'person',
      label: t('Person, user group or page', {
        description: 'Text cell "/" menu',
      }),
    },
    {
      panel: 'date',
      icon: 'calendar_today',
      label: t('Date', { description: 'Text cell "/" menu' }),
    },
    {
      panel: 'label',
      icon: 'label',
      label: t('Label', { description: 'Text cell "/" menu' }),
    },
    {
      panel: 'emoji',
      icon: 'mood',
      label: t('Emoji', { description: 'Text cell "/" menu' }),
    },
    {
      panel: 'image',
      icon: 'image',
      label: t('Image', { description: 'Text cell "/" menu' }),
    },
  ];
  return (
    <Popover
      onClose={onClose}
      label={t('Insert', { description: 'Accessible name of the "/" menu' })}
    >
      <div
        role="menu"
        onKeyDown={(event) => {
          if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') {
            return;
          }
          event.preventDefault();
          const buttons = Array.from(
            event.currentTarget.querySelectorAll<HTMLButtonElement>('button'),
          );
          const index = buttons.indexOf(
            document.activeElement as HTMLButtonElement,
          );
          const next =
            event.key === 'ArrowDown'
              ? (index + 1) % buttons.length
              : (index - 1 + buttons.length) % buttons.length;
          buttons[next]?.focus();
        }}
      >
        {items.map((item, index) => (
          <button
            key={item.panel}
            type="button"
            role="menuitem"
            autoFocus={index === 0}
            className="loop-table__popover-item"
            onClick={() => onPick(item.panel)}
          >
            <Icon iconName={item.icon} $size="18px" />
            <span>{item.label}</span>
          </button>
        ))}
      </div>
    </Popover>
  );
};

const DatePanel = ({
  onPick,
  onClose,
}: {
  onPick: (iso: string) => void;
  onClose: () => void;
}) => {
  const { t } = useTranslation();
  const [value, setValue] = useState(() =>
    new Date().toLocaleDateString('sv-SE'),
  );
  return (
    <Popover
      onClose={onClose}
      label={t('Date', { description: 'Accessible name of the date panel' })}
    >
      <form
        className="loop-table__panel-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
            onPick(value);
          }
        }}
      >
        <input
          autoFocus
          type="date"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <button type="submit" className="loop-table__panel-button">
          {t('Insert', { description: 'Inserts an element in a text cell' })}
        </button>
      </form>
    </Popover>
  );
};

const LabelPanel = ({
  onPick,
  onClose,
}: {
  onPick: (label: string, color: string) => void;
  onClose: () => void;
}) => {
  const { t } = useTranslation();
  const [label, setLabel] = useState('');
  const [color, setColor] = useState('blue');
  return (
    <Popover
      onClose={onClose}
      label={t('Label', { description: 'Accessible name of the label panel' })}
    >
      <form
        className="loop-table__panel-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (label.trim()) {
            onPick(label.trim(), color);
          }
        }}
      >
        <input
          autoFocus
          type="text"
          maxLength={40}
          placeholder={t('Label text', {
            description: 'Placeholder of the label field of a text cell',
          })}
          value={label}
          onChange={(event) => setLabel(event.target.value)}
        />
        <div className="loop-table__swatches">
          {Object.entries(LABEL_COLORS).map(([name, colors]) => (
            <button
              key={name}
              type="button"
              className={`loop-table__swatch ${color === name ? 'is-active' : ''}`}
              style={{ background: colors.bg, color: colors.fg }}
              aria-label={name}
              aria-pressed={color === name}
              title={name}
              onClick={() => setColor(name)}
            >
              {color === name ? '✓' : ''}
            </button>
          ))}
        </div>
        <button
          type="submit"
          className="loop-table__panel-button"
          disabled={!label.trim()}
        >
          {t('Insert', { description: 'Inserts an element in a text cell' })}
        </button>
      </form>
    </Popover>
  );
};

const ImagePanel = ({
  docId,
  onPick,
  onClose,
}: {
  docId: string;
  onPick: (address: string, name: string) => void;
  onClose: () => void;
}) => {
  const { t } = useTranslation();
  const uploadImage = useUploadImage(docId);
  const [address, setAddress] = useState('');
  const [isUploading, setIsUploading] = useState(false);
  const href = safeLink(address);
  return (
    <Popover
      onClose={onClose}
      label={t('Image', { description: 'Accessible name of the image panel' })}
    >
      <form
        className="loop-table__panel-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (href) {
            onPick(href, href.split('/').pop() || 'image');
          }
        }}
      >
        <label className="loop-table__panel-button">
          <Icon iconName="upload" $size="16px" />
          {isUploading
            ? t('Uploading…', { description: 'Image being uploaded' })
            : t('Upload an image', {
                description: 'Button to upload an image into a text cell',
              })}
          <input
            type="file"
            accept="image/*"
            hidden
            disabled={isUploading || !docId}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file) {
                return;
              }
              setIsUploading(true);
              uploadImage(file)
                .then((url) => onPick(url, file.name))
                .catch(() => setIsUploading(false));
            }}
          />
        </label>
        <input
          autoFocus
          type="text"
          inputMode="url"
          placeholder={t('or paste an image address', {
            description: 'Placeholder of the image address field',
          })}
          value={address}
          onChange={(event) => setAddress(event.target.value)}
        />
        <button
          type="submit"
          className="loop-table__panel-button"
          disabled={!href}
        >
          {t('Insert', { description: 'Inserts an element in a text cell' })}
        </button>
      </form>
    </Popover>
  );
};
