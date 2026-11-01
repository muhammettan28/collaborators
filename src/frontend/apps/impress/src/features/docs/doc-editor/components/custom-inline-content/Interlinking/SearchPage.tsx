import { StyleSchema } from '@blocknote/core';
import { ReactCustomInlineContentRenderProps } from '@blocknote/react';
import {
  Button,
  VariantType,
  useTreeContext,
} from '@gouvfr-lasuite/ui-components';
import { Popover } from '@mantine/core';
import type { KeyboardEvent } from 'react';
import { useEffect, useId, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { APIError } from '@/api';
import DocIcon from '@/assets/icons/ui-kit/doc.svg';
import ArrowIcon from '@/assets/icons/ui-kit/keyboard_return.svg';
import {
  Box,
  Card,
  QuickSearch,
  QuickSearchItemContent,
  Text,
} from '@/components';
import { useEditorStore } from '@/docs/doc-editor/stores';
import { DocsBlockNoteEditor } from '@/docs/doc-editor/types';
import {
  Doc,
  getEmojiAndTitle,
  useDocStore,
  useTrans,
} from '@/docs/doc-management';
import { DocSearchContent } from '@/docs/doc-search';
import { useDocSearchFilterStore } from '@/docs/doc-search/stores/useDocSearchFilterStore';
import { postMention } from '@/features/notifications/api';
import { useToast } from '@/hooks';
import { useResponsiveStore } from '@/stores';

import {
  LARGE_GROUP,
  MentionCandidate,
  MentionSearchGroup,
} from '../Mention/MentionSearchGroup';

import { InterlinkingLinkInlineContentType } from './InterlinkingLinkInlineContent';

const inputStyle = css`
  background-color: transparent;
  border: none;
  outline: none;
  color: var(--c--globals--colors--gray-700);
  font-size: var(--c--globals--font--sizes--md);
  width: 100%;
  font-family: 'Inter';
`;

type ReactInterlinkingSearch = ReactCustomInlineContentRenderProps<
  InterlinkingLinkInlineContentType,
  StyleSchema
>;

export const SearchPage = ({
  contentRef,
  updateInlineContent,
  editor,
  inlineContent,
}: ReactInterlinkingSearch) => {
  const trigger = inlineContent.props.trigger;
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const [search, setSearch] = useState('');
  const { isDesktop } = useResponsiveStore();
  const { untitledDocument } = useTrans();
  const isEditable = editor.isEditable;
  const treeContext = useTreeContext<Doc>();
  const modalRef = useRef<HTMLDivElement>(null);
  const dropdownId = useId();
  const [popoverOpened, setPopoverOpened] = useState(false);
  const { setFilter } = useDocSearchFilterStore();
  const { currentDoc } = useDocStore();
  const { editor: mainEditor } = useEditorStore();
  const { toast } = useToast();
  const [pendingGroup, setPendingGroup] = useState<MentionCandidate | null>(
    null,
  );

  /**
   * Replace the search by a mention chip. In the page, report it so the
   * people concerned are notified; comments are read by the server.
   */
  const insertMention = (candidate: MentionCandidate) => {
    if (!isEditable) {
      return;
    }
    updateInlineContent({
      type: 'interlinkingLinkInline',
      props: { disabled: true },
    });
    contentRef(null);
    editor.focus();
    const isPage = mainEditor === (editor as unknown);
    // In a to-do item of a page, mentioning someone assigns it to them
    const assign =
      isPage &&
      (editor as DocsBlockNoteEditor).getTextCursorPosition().block.type ===
        'checkListItem';
    (editor as DocsBlockNoteEditor).insertInlineContent([
      {
        type: 'mention',
        props: {
          kind: candidate.kind,
          targetId: candidate.id,
          label: candidate.label,
          assign,
        },
      },
      ' ',
    ]);

    // An assignment notifies them itself (usePageAssignments)
    if (isPage && currentDoc && !assign) {
      const anchorId = (editor as DocsBlockNoteEditor).getTextCursorPosition()
        .block.id;
      postMention({
        docId: currentDoc.id,
        anchorId,
        target: { kind: candidate.kind, id: candidate.id },
      }).catch((error: APIError) => {
        const noAccess = (error.cause ?? []).some((cause) =>
          cause.includes('access'),
        );
        toast(
          noAccess
            ? t(
                "{{name}} was not notified: they can't see this page yet. Share it with them first.",
                {
                  description: 'Toast when a mentioned person has no access',
                  name: candidate.label,
                },
              )
            : t('{{name}} could not be notified.', {
                description: 'Toast when a mention notification failed',
                name: candidate.label,
              }),
          VariantType.WARNING,
        );
      });
    }
  };

  const onSelectCandidate = (candidate: MentionCandidate) => {
    if (
      candidate.kind === 'group' &&
      (candidate.memberCount ?? 0) > LARGE_GROUP &&
      pendingGroup?.id !== candidate.id
    ) {
      setPendingGroup(candidate);
      return;
    }
    setPendingGroup(null);
    insertMention(candidate);
  };

  /**
   * When the search page is opened, we set the search
   * target to 'current' to limit the search to the current
   * document and its sub-documents. "@" lists every page one can read.
   */
  useEffect(() => {
    setFilter(trigger === '@' ? 'all' : 'current');
  }, [setFilter, trigger]);

  /**
   * createReactInlineContentSpec add automatically the focus after
   * the inline content, so we need to set the focus on the input
   * after the component is mounted.
   * We also defer opening the popover to after mount so that
   * floating-ui attaches scroll/resize listeners correctly.
   */
  useEffect(() => {
    const timeoutId = setTimeout(() => {
      if (inputRef.current) {
        inputRef.current.focus();
      }
      setPopoverOpened(true);
    }, 100);

    return () => clearTimeout(timeoutId);
  }, []);

  const closeSearch = (insertContent: string) => {
    if (!isEditable) {
      return;
    }

    updateInlineContent({
      type: 'interlinkingLinkInline',
      props: {
        disabled: true,
      },
    });

    editor.focus();

    if (insertContent) {
      contentRef(null);
      editor.focus();
      (editor as DocsBlockNoteEditor).insertInlineContent([insertContent]);
    }
  };

  /**
   * A click anywhere else on the screen closes the menu: with nothing typed
   * after the trigger, the trigger goes away; what was typed stays as text.
   */
  const dismissRef = useRef(() => {});
  dismissRef.current = () => closeSearch(search ? `${trigger}${search}` : '');
  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (
        !target ||
        modalRef.current?.contains(target) ||
        inputRef.current?.parentElement?.contains(target)
      ) {
        return;
      }
      dismissRef.current();
    };
    document.addEventListener('pointerdown', onPointerDown, true);
    return () =>
      document.removeEventListener('pointerdown', onPointerDown, true);
  }, []);

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      // Keep the trigger character and typed text in the editor when closing with Escape
      closeSearch(`${trigger}${search}`);
    } else if (e.key === 'Backspace' && search.length === 0) {
      e.preventDefault();
      closeSearch('');
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      // Allow arrow keys to be handled by the command menu for navigation
      const commandList = modalRef.current?.querySelector('[cmdk-list]');

      // Create a synthetic keyboard event for the command menu
      const syntheticEvent = new KeyboardEvent('keydown', {
        key: e.key,
        bubbles: true,
        cancelable: true,
      });
      commandList?.dispatchEvent(syntheticEvent);
      e.preventDefault();
    } else if (e.key === 'Enter') {
      // Handle Enter key to select the currently highlighted item
      const selectedItem = modalRef.current?.querySelector(
        '[cmdk-item][data-selected="true"]',
      ) as HTMLElement;

      selectedItem?.click();
      e.preventDefault();
    }
  };

  return (
    <Box as="span" $position="relative">
      <Popover
        position="bottom"
        opened={popoverOpened}
        withinPortal={true}
        hideDetached={false}
      >
        <Popover.Target>
          <Box
            as="span"
            className="inline-content"
            $background="var(--c--contextuals--background--semantic--overlay--primary)"
            $color="var(--c--contextuals--content--semantic--neutral--primary)"
            $direction="row"
            $radius="3px"
            $padding="2px"
            $display="inline-flex"
            tabIndex={-1} // Ensure the span is focusable
          >
            {' '}
            <Box as="span" aria-hidden="true" $height="25px">
              {trigger}
            </Box>
            <Box
              as="input"
              name="doc-search-input"
              role="combobox"
              aria-label={t('Search for a page', {
                description:
                  'Accessible name or placeholder of a document search field',
              })}
              aria-expanded={popoverOpened}
              aria-haspopup="listbox"
              aria-autocomplete="list"
              aria-controls={dropdownId}
              $padding={{ left: '3px' }}
              placeholder={
                trigger === '@'
                  ? t('mention someone, a user group or a page...', {
                      description:
                        'Placeholder of the @ search for people, groups and pages',
                    })
                  : t('mention a sub-page...', {
                      description:
                        'Placeholder of the field to search a doc to link in the editor',
                    })
              }
              $css={inputStyle}
              ref={inputRef}
              $display="inline-flex"
              onInput={(e) => {
                const value = (e.target as HTMLInputElement).value;
                setSearch(value);
              }}
              onKeyDown={handleKeyDown}
              autoComplete="off"
            />
          </Box>
        </Popover.Target>
        <Popover.Dropdown>
          <Box
            ref={modalRef}
            id={dropdownId}
            role="listbox"
            aria-label={t('Search results', {
              description:
                'Accessible name or heading of the list of search results',
            })}
            $minWidth={isDesktop ? '330px' : '220px'}
            $width="fit-content"
            $zIndex="10"
            $css={css`
              position: relative;

              .mantine-Popover-dropdown[data-position='bottom'] & {
                top: -10px;
              }
              .mantine-Popover-dropdown[data-position='top'] & {
                top: 10px;
              }

              & .quick-search-container [cmdk-root] {
                border-radius: inherit;
                background: transparent;
              }

              /* Everyone, every group and every page are listed: it scrolls */
              & [cmdk-list] {
                max-height: min(420px, 50vh);
                overflow-y: auto;
              }
            `}
          >
            <QuickSearch showInput={false} isSelectByDefault>
              <Card
                $css={css`
                  box-shadow: 0 0 6px 0 rgba(0, 0, 145, 0.1);
                  border: 1px solid
                    var(--c--contextuals--border--surface--primary);
                  background: var(
                    --c--contextuals--background--surface--primary
                  );
                  .quick-search-container & [cmdk-group] {
                    margin-top: 0 !important;
                  }
                  & h2 {
                    padding: var(--c--globals--spacings--sm);
                  }
                  & > div {
                    margin-top: var(--c--globals--spacings--0);
                    & [cmdk-group-heading] {
                      padding: 0.4rem;
                      margin: 0;
                    }

                    & [cmdk-group-items] .ml-b {
                      margin-left: 0rem;
                      padding: 0.5rem;
                      font-size: 14px;
                      display: block;
                    }

                    & [cmdk-item] {
                      border-radius: 0;
                    }

                    & .--docs--doc-search-item > div {
                      gap: 0.8rem;
                    }

                    & .--docs--quick-search-group-title {
                      font-size: 12px;
                      margin: var(--c--globals--spacings--sm);
                      margin-bottom: var(--c--globals--spacings--xxs);
                    }

                    & .--docs--quick-search-group-empty {
                      margin: var(--c--globals--spacings--sm);
                    }
                  }
                `}
                $margin="sm"
                $padding="none"
              >
                {trigger === '@' && pendingGroup && (
                  <Box
                    $padding="sm"
                    $gap="xs"
                    role="alert"
                    $css={css`
                      border-bottom: 1px solid
                        var(--c--contextuals--border--surface--primary);
                    `}
                  >
                    <Text $size="sm">
                      {t('Notify {{count}} people in {{name}}?', {
                        description:
                          'Confirmation before mentioning a large group',
                        count: pendingGroup.memberCount,
                        name: pendingGroup.label,
                      })}
                    </Text>
                    <Box $direction="row" $gap="xs">
                      <Button
                        size="small"
                        onClick={() => onSelectCandidate(pendingGroup)}
                      >
                        {t('Notify them', {
                          description: 'Confirms mentioning a large group',
                        })}
                      </Button>
                      <Button
                        size="small"
                        variant="secondary"
                        onClick={() => setPendingGroup(null)}
                      >
                        {t('Cancel', {
                          description:
                            'Button to dismiss a dialog without confirming',
                        })}
                      </Button>
                    </Box>
                  </Box>
                )}
                {trigger === '@' && currentDoc && (
                  <MentionSearchGroup
                    docId={currentDoc.id}
                    search={search}
                    onSelect={onSelectCandidate}
                  />
                )}
                <DocSearchContent
                  groupName={t('Link a page', {
                    description:
                      'Editor menu entry to insert a link to another doc',
                  })}
                  search={search}
                  parentDocId={treeContext?.root?.id}
                  isSearchNotMandatory
                  onSelect={(doc) => {
                    if (!isEditable) {
                      return;
                    }

                    updateInlineContent({
                      type: 'interlinkingLinkInline',
                      props: {
                        docId: doc.id,
                      },
                    });

                    contentRef(null);
                    editor.focus();
                  }}
                  renderSearchElement={(doc) => {
                    const { emoji, titleWithoutEmoji } = getEmojiAndTitle(
                      doc.title || untitledDocument,
                    );

                    return (
                      <QuickSearchItemContent
                        left={
                          <Box
                            $direction="row"
                            $gap="0.2rem"
                            $align="center"
                            $padding={{
                              vertical: '0.5rem',
                              horizontal: '0.2rem',
                            }}
                            $width="100%"
                          >
                            <Box
                              $css={css`
                                width: 24px;
                                flex-shrink: 0;
                              `}
                            >
                              {emoji ? (
                                <Text $size="18px">{emoji}</Text>
                              ) : (
                                <DocIcon
                                  aria-hidden="true"
                                  width="24px"
                                  height="24px"
                                  color="var(--c--contextuals--content--semantic--neutral--primary)"
                                />
                              )}
                            </Box>

                            <Text
                              $size="sm"
                              $color="var(--c--contextuals--content--semantic--neutral--primary)"
                              spellCheck="false"
                              $weight="500"
                            >
                              {titleWithoutEmoji}
                            </Text>
                          </Box>
                        }
                        right={
                          <ArrowIcon
                            aria-hidden="true"
                            width="24px"
                            height="24px"
                            color="var(--c--contextuals--content--semantic--neutral--tertiary)"
                          />
                        }
                      />
                    );
                  }}
                />
              </Card>
            </QuickSearch>
          </Box>
        </Popover.Dropdown>
      </Popover>
    </Box>
  );
};
