import { combineByGroup } from '@blocknote/core';
import { filterSuggestionItems } from '@blocknote/core/extensions';
import { getDiagramSlashMenuItems } from '@blocknote/diagram-block';
import { getMathSlashMenuItems } from '@blocknote/math-block';
import {
  DefaultReactSuggestionItem,
  SuggestionMenuController,
  getDefaultReactSlashMenuItems,
  getPageBreakReactSlashMenuItems,
  useBlockNoteEditor,
  useDictionary,
} from '@blocknote/react';
import React, { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import {
  DocsBlockSchema,
  DocsInlineContentSchema,
  DocsStyleSchema,
} from '../types';
import { arrangeSlashMenu } from '../utils';

import BlockNoteAI from './AI';
import {
  getCalloutReactSlashMenuItems,
  getPdfReactSlashMenuItems,
  getPresentationReactSlashMenuItems,
} from './custom-blocks';
import { getLoopTableReactSlashMenuItems } from './custom-blocks/loop-table/LoopTableBlock';
import { useGetInterlinkingMenuItems } from './custom-inline-content';
import XLMultiColumn from './xl-multi-column';

const getMultiColumnSlashMenuItems =
  XLMultiColumn?.getMultiColumnSlashMenuItems;

const getAISlashMenuItems = BlockNoteAI?.getAISlashMenuItems;

export const BlockNoteSuggestionMenu = ({
  aiAllowed,
}: {
  aiAllowed: boolean;
}) => {
  const editor = useBlockNoteEditor<
    DocsBlockSchema,
    DocsInlineContentSchema,
    DocsStyleSchema
  >();
  const { t } = useTranslation();
  const dictionaryDate = useDictionary();
  const basicBlocksName = dictionaryDate.slash_menu.page_break.group;
  const fileBlocksName = dictionaryDate.slash_menu.file.group;

  const getInterlinkingMenuItems = useGetInterlinkingMenuItems();

  const getSlashMenuItems = useMemo(() => {
    // We insert it after the "Code Block" item to have the interlinking block displayed after the basic blocks
    // Collaborators: "Table" is our table; BlockNote's keeps its own name
    const defaultMenu = getDefaultReactSlashMenuItems(editor).map((item) =>
      (item as DefaultReactSuggestionItem & { key?: string }).key === 'table'
        ? {
            ...item,
            title: t('Table - BlockNote.js Original', {
              description: 'Name of the editor block type: BlockNote table',
            }),
          }
        : item,
    );

    const combinedMenu = combineByGroup(
      defaultMenu,
      getPageBreakReactSlashMenuItems(editor),
      getMultiColumnSlashMenuItems?.(editor) || [],
      getPdfReactSlashMenuItems(editor, t, fileBlocksName),
      getCalloutReactSlashMenuItems(editor, t, basicBlocksName),
      getLoopTableReactSlashMenuItems(editor, t, basicBlocksName),
      getMathSlashMenuItems(editor),
      getDiagramSlashMenuItems(editor),
      aiAllowed && getAISlashMenuItems ? getAISlashMenuItems(editor) : [],
    );

    // Collaborators: the presentation first, above every group; "Links" go
    // after "Callout", keeping the basic blocks (and their heading) together
    const groupedItems = arrangeSlashMenu<DefaultReactSuggestionItem>({
      first: getPresentationReactSlashMenuItems(editor, t),
      menu: combinedMenu,
      links: getInterlinkingMenuItems(editor, t),
    });

    return async (query: string) =>
      Promise.resolve(filterSuggestionItems(groupedItems, query));
  }, [
    editor,
    t,
    fileBlocksName,
    basicBlocksName,
    aiAllowed,
    getInterlinkingMenuItems,
  ]);

  return (
    <SuggestionMenuController
      triggerCharacter="/"
      getItems={getSlashMenuItems}
    />
  );
};
