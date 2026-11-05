import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { Box, BoxButton, Icon, Text } from '@/components';
import { CardFloatingBar } from '@/components/FloatingBar';
import {
  Doc,
  DocViewMode,
  useDocViewMode,
  useDocViewModeStore,
} from '@/docs/doc-management';
import { useResponsiveStore } from '@/stores';

/**
 * Reading or editing a page, for those who may edit it: a page opens in
 * reading view, so nothing changes by mistake.
 */
export const DocViewModeSwitch = ({ doc }: { doc: Doc }) => {
  const { t } = useTranslation();
  const { isSmallMobile } = useResponsiveStore();
  const mode = useDocViewMode(doc.id);
  const setMode = useDocViewModeStore((state) => state.setMode);

  const options: {
    value: DocViewMode;
    icon: string;
    label: string;
    hint: string;
  }[] = [
    {
      value: 'reading',
      icon: 'chrome_reader_mode',
      label: t('Reading', { description: 'Page view switch: read only' }),
      hint: t('Reading: just read the page, nothing changes by mistake', {
        description: 'Tooltip of the reading view of the page view switch',
      }),
    },
    {
      value: 'editing',
      icon: 'edit',
      label: t('Editing', { description: 'Page view switch: can change it' }),
      hint: t('Editing: click in the page and type to change it', {
        description: 'Tooltip of the editing view of the page view switch',
      }),
    },
  ];

  return (
    <CardFloatingBar>
      <Box
        role="radiogroup"
        aria-label={t('Page view', {
          description: 'Accessible name of the reading/editing switch',
        })}
        $direction="row"
        $gap="4xs"
        $padding="4xs"
        className="--collaborators--view-mode-switch"
      >
        {options.map((option) => {
          const isSelected = mode === option.value;
          return (
            <BoxButton
              key={option.value}
              role="radio"
              aria-checked={isSelected}
              aria-label={option.label}
              title={option.hint}
              onClick={() => setMode(doc.id, option.value)}
              $direction="row"
              $align="center"
              $gap="3xs"
              $padding={{ horizontal: 'xs', vertical: '3xs' }}
              $css={css`
                border-radius: var(--c--globals--spacings--3xs);
                color: ${
                  isSelected
                    ? 'var(--c--contextuals--content--semantic--brand--tertiary)'
                    : 'var(--c--contextuals--content--semantic--neutral--secondary)'
                };
                background: ${
                  isSelected
                    ? 'var(--c--contextuals--background--semantic--brand--tertiary)'
                    : 'transparent'
                };
                font-weight: ${isSelected ? 600 : 400};
                &:hover {
                  background: var(
                    --c--contextuals--background--semantic--contextual--primary
                  );
                }
              `}
            >
              <Icon iconName={option.icon} $size="18px" $color="inherit" />
              {!isSmallMobile && (
                <Text $size="sm" $color="inherit" $weight="inherit">
                  {option.label}
                </Text>
              )}
            </BoxButton>
          );
        })}
      </Box>
    </CardFloatingBar>
  );
};
