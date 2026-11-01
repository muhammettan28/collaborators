import type { TFunction } from 'i18next';

import { ColumnType, NumberFormat, SummaryKind } from './model';

export const columnTypeIcon: Record<ColumnType, string> = {
  [ColumnType.TEXT]: 'notes',
  [ColumnType.NUMBER]: 'tag',
  [ColumnType.DATE]: 'calendar_today',
  [ColumnType.PERSON]: 'person',
  [ColumnType.LABEL]: 'label',
  [ColumnType.VOTING]: 'thumb_up',
};

export const columnTypeLabel = (
  t: TFunction<'translation', undefined>,
  type: ColumnType,
) =>
  ({
    [ColumnType.TEXT]: t('Text', { description: 'Loop table column type' }),
    [ColumnType.NUMBER]: t('Number', { description: 'Loop table column type' }),
    [ColumnType.DATE]: t('Date', { description: 'Loop table column type' }),
    [ColumnType.PERSON]: t('Person', { description: 'Loop table column type' }),
    [ColumnType.LABEL]: t('Label', { description: 'Loop table column type' }),
    [ColumnType.VOTING]: t('Voting', { description: 'Loop table column type' }),
  })[type];

export const numberFormatLabel = (
  t: TFunction<'translation', undefined>,
  format: NumberFormat,
) =>
  ({
    [NumberFormat.PLAIN]: t('Plain', { description: 'Number format' }),
    [NumberFormat.DECIMAL]: t('Two decimals', { description: 'Number format' }),
    [NumberFormat.PERCENT]: t('Percent', { description: 'Number format' }),
    [NumberFormat.CURRENCY]: t('Currency', { description: 'Number format' }),
  })[format];

export const summaryLabel = (
  t: TFunction<'translation', undefined>,
  kind: SummaryKind,
) =>
  ({
    [SummaryKind.NONE]: t('None', { description: 'Loop table summary' }),
    [SummaryKind.SUM]: t('Sum', { description: 'Loop table summary' }),
    [SummaryKind.AVERAGE]: t('Average', { description: 'Loop table summary' }),
    [SummaryKind.COUNT]: t('Count', { description: 'Loop table summary' }),
    [SummaryKind.MIN]: t('Min', { description: 'Loop table summary' }),
    [SummaryKind.MAX]: t('Max', { description: 'Loop table summary' }),
  })[kind];

export const operatorLabel = (
  t: TFunction<'translation', undefined>,
  operator: string,
) =>
  ({
    contains: t('contains', { description: 'Filter condition' }),
    not_contains: t('does not contain', { description: 'Filter condition' }),
    is: t('is', { description: 'Filter condition' }),
    is_not: t('is not', { description: 'Filter condition' }),
    empty: t('is empty', { description: 'Filter condition' }),
    not_empty: t('is not empty', { description: 'Filter condition' }),
    gt: t('is greater than', { description: 'Filter condition' }),
    lt: t('is less than', { description: 'Filter condition' }),
    before: t('is before', { description: 'Filter condition' }),
    after: t('is after', { description: 'Filter condition' }),
    includes_me: t('includes me or my user groups', {
      description: 'Filter condition',
    }),
  })[operator] ?? operator;

export const operatorNeedsValue = (operator: string) =>
  !['empty', 'not_empty', 'includes_me'].includes(operator);
