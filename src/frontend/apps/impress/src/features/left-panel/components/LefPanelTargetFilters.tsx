import {
  DndContext,
  DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import { usePathname, useSearchParams } from 'next/navigation';
import { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import SearchIcon from '@/assets/icons/ui-kit/zoom-rounded.svg';
import { Box, BoxButton, Icon, StyledLink, Text } from '@/components';
import { useCunninghamTheme } from '@/cunningham';
import { DocDefaultFilter, readTarget, useTrans } from '@/docs/doc-management';
import { orderItems, useSidebarOrder } from '@/features/dashboard/api';
import { useLeftPanelStore } from '@/features/left-panel';
import { MyCollaboratorsName } from '@/features/people/BrandName';
import { SEARCH_PATH } from '@/features/search/api';
import ClockIcon from '@/icons/clock.svg';
import SharedIcon from '@/icons/shared.svg';
import StarIcon from '@/icons/star.svg';
import TrashIcon from '@/icons/trash.svg';
import UserIcon from '@/icons/user.svg';
import { useResponsiveStore } from '@/stores/useResponsiveStore';

/**
 * An item one can drag above or below the others, by its handle only: a
 * click on the item opens it, the handle (shown on hover) moves it.
 */
const SortableItem = ({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: ReactNode;
}) => {
  const { t } = useTranslation();
  const drag = useDraggable({ id });
  const drop = useDroppable({ id });
  return (
    <Box
      ref={(node: HTMLDivElement | null) => {
        drag.setNodeRef(node);
        drop.setNodeRef(node);
      }}
      $position="relative"
      $css={css`
        border-radius: 4px;
        opacity: ${drag.isDragging ? 0.5 : 1};
        z-index: ${drag.isDragging ? 10 : 'auto'};
        transform: ${
          drag.transform ? `translate(0, ${drag.transform.y}px)` : 'none'
        };
        box-shadow: ${
          drop.isOver && !drag.isDragging
            ? 'inset 0 2px 0 var(--c--globals--colors--brand-400)'
            : 'none'
        };
        & > .--collaborators--drag-handle {
          opacity: ${drag.isDragging ? 1 : 0};
        }
        &:hover > .--collaborators--drag-handle,
        & > .--collaborators--drag-handle:focus-visible {
          opacity: 1;
        }
        @media (hover: none) {
          & > .--collaborators--drag-handle {
            opacity: 1;
          }
        }
      `}
    >
      {children}
      <Box
        ref={drag.setActivatorNodeRef}
        {...drag.listeners}
        {...drag.attributes}
        className="--collaborators--drag-handle"
        aria-label={t('Move {{item}}', {
          description: 'Handle reordering an item of the left panel',
          item: label,
        })}
        title={t('Drag to reorder', {
          description: 'Tooltip of the handle reordering left panel items',
        })}
        $position="absolute"
        $align="center"
        $justify="center"
        $css={css`
          top: 50%;
          inset-inline-end: 2px;
          width: 22px;
          height: 26px;
          margin-top: -13px;
          border-radius: 4px;
          cursor: ${drag.isDragging ? 'grabbing' : 'grab'};
          touch-action: none;
          transition: opacity 0.15s;
          &:hover {
            background-color: var(
              --c--contextuals--background--semantic--contextual--secondary
            );
          }
          &:focus-visible {
            outline: 2px solid var(--c--globals--colors--brand-400);
          }
        `}
      >
        <Icon
          iconName="drag_indicator"
          $size="18px"
          $variation="tertiary"
          aria-hidden="true"
        />
      </Box>
    </Box>
  );
};

export const LeftPanelTargetFilters = () => {
  const { t } = useTranslation();
  const { transFilter } = useTrans();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { isMobile } = useResponsiveStore();
  const { closePanel } = useLeftPanelStore();
  const { colorsTokens, spacingsTokens } = useCunninghamTheme();

  // No list is highlighted on the dashboard (no target)
  const target = readTarget(searchParams.get('target'));

  // "My collaborations": what one is involved in, then the trash
  const defaultQueries: {
    id: string;
    icon: ReactNode;
    label: string;
    /** What the item shows, when not just its label */
    display?: ReactNode;
    /** A few words on what the item holds, as its tooltip */
    hint?: string;
    targetQuery?: DocDefaultFilter;
    href?: string;
  }[] = [
    {
      icon: (
        <Icon
          icon={<ClockIcon width={20} height={20} aria-hidden="true" />}
          $padding="4xs"
          $variation="tertiary"
        />
      ),
      id: 'recent',
      label: transFilter(DocDefaultFilter.ALL_DOCS),
      targetQuery: DocDefaultFilter.ALL_DOCS,
    },
    {
      icon: (
        <Icon
          iconName="notifications"
          $size="20px"
          $padding="4xs"
          $variation="tertiary"
        />
      ),
      id: 'notifications',
      label: transFilter(DocDefaultFilter.NOTIFICATIONS),
      targetQuery: DocDefaultFilter.NOTIFICATIONS,
    },
    // The one search, with what is open to join and the labels
    {
      icon: (
        <Icon
          icon={<SearchIcon width={20} height={20} aria-hidden="true" />}
          $padding="4xs"
          $variation="tertiary"
        />
      ),
      // The id it had as "Explore", so saved orders keep its place
      id: 'explore',
      label: t('Search', {
        description: 'Left panel entry opening the Search screen',
      }),
      href: SEARCH_PATH,
    },
    {
      icon: (
        <Icon
          icon={<StarIcon width={20} height={20} aria-hidden="true" />}
          $padding="4xs"
          $variation="tertiary"
        />
      ),
      id: 'starred',
      label: transFilter(DocDefaultFilter.STARRED),
      targetQuery: DocDefaultFilter.STARRED,
    },
    {
      icon: (
        <Icon
          icon={<UserIcon width={20} height={20} aria-hidden="true" />}
          $padding="4xs"
          $variation="tertiary"
        />
      ),
      id: 'owned',
      label: transFilter(DocDefaultFilter.MY_DOCS),
      targetQuery: DocDefaultFilter.MY_DOCS,
    },
    {
      icon: (
        <Icon
          icon={<SharedIcon width={20} height={20} aria-hidden="true" />}
          $padding="4xs"
          $variation="tertiary"
        />
      ),
      id: 'shared',
      label: transFilter(DocDefaultFilter.SHARED_WITH_ME),
      targetQuery: DocDefaultFilter.SHARED_WITH_ME,
    },
    // The people one may see, named in the style of the logo
    {
      icon: (
        <Icon
          iconName="contacts"
          $size="20px"
          $padding="4xs"
          $variation="tertiary"
        />
      ),
      id: 'people',
      label: transFilter(DocDefaultFilter.PEOPLE),
      display: <MyCollaboratorsName size="0.95em" />,
      hint: t('The people you work with, and the platform settings', {
        description: 'Tooltip of the "My Collaborators" sidebar item',
      }),
      targetQuery: DocDefaultFilter.PEOPLE,
    },
    {
      icon: (
        <Icon
          icon={<TrashIcon width={20} height={20} aria-hidden="true" />}
          $padding="4xs"
          $variation="tertiary"
        />
      ),
      id: 'trashbin',
      label: transFilter(DocDefaultFilter.TRASHBIN),
      targetQuery: DocDefaultFilter.TRASHBIN,
    },
  ];

  // The order the collaborator chose, kept on the server
  const { query: savedOrder, save } = useSidebarOrder();
  // The trash is the last item, and stays there
  const movable = defaultQueries.filter((query) => query.id !== 'trashbin');
  const trash = defaultQueries[defaultQueries.length - 1];
  const ordered = orderItems(movable, savedOrder.data ?? []);
  // Moved from the default order: a quiet link puts it back
  const isReordered = ordered.some(
    (query, index) => query.id !== movable[index].id,
  );
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor),
  );
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) {
      return;
    }
    const ids = ordered.map((query) => query.id);
    const from = ids.indexOf(String(active.id));
    const to = ids.indexOf(String(over.id));
    if (from < 0 || to < 0) {
      return;
    }
    ids.splice(to, 0, ids.splice(from, 1)[0]);
    save.mutate(ids);
  };

  // Collaborators: the lists are screens of the home, from wherever one is
  // (not the current address plus a target: from Search, that kept ?q=…)
  const buildHref = (query: DocDefaultFilter) =>
    `/?${new URLSearchParams({ target: query }).toString()}`;

  const handleFilterClick = () => {
    if (isMobile) {
      closePanel();
    }
  };

  return (
    <Box
      $justify="center"
      $padding={{ horizontal: 'sm' }}
      $gap={spacingsTokens['2xs']}
      className="--docs--left-panel-target-filters"
    >
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={onDragEnd}
      >
        {[...ordered, trash].map((query) => {
          const isActive = query.href
            ? pathname?.startsWith(query.href.replace(/\/$/, ''))
            : target === query.targetQuery;
          const href =
            query.href ??
            buildHref(query.targetQuery ?? DocDefaultFilter.ALL_DOCS);

          const link = (
            <StyledLink
              key={query.label}
              href={href}
              aria-label={query.label}
              title={query.hint}
              aria-current={isActive ? 'page' : undefined}
              onClick={handleFilterClick}
              $css={css`
                align-items: center;
                justify-content: flex-start;
                gap: var(--c--globals--spacings--3xs);
                padding: var(--c--globals--spacings--2xs);
                border-radius: var(--c--globals--spacings--3xs);
                background-color: ${
                  isActive
                    ? 'var(--c--contextuals--background--semantic--contextual--primary)'
                    : 'transparent'
                };
                font-weight: 500;
                color: inherit;
                text-decoration: none;
                &:hover {
                  background-color: var(
                    --c--contextuals--background--semantic--contextual--primary
                  );
                }
                &:focus-visible {
                  outline: none !important;
                  box-shadow: 0 0 0 2px ${colorsTokens['brand-400']} !important;
                  border-radius: var(--c--globals--spacings--st);
                }
              `}
            >
              {query.icon}
              <Text $size="sm">{query.display ?? query.label}</Text>
            </StyledLink>
          );
          // The trash stays last; the others can be dragged into any order
          return query.id === 'trashbin' ? (
            <Box key={query.id}>{link}</Box>
          ) : (
            <SortableItem key={query.id} id={query.id} label={query.label}>
              {link}
            </SortableItem>
          );
        })}
      </DndContext>
      {isReordered && (
        <BoxButton
          onClick={() => save.mutate([])}
          data-testid="sidebar-order-reset"
          $direction="row"
          $align="center"
          $gap="3xs"
          $padding={{ horizontal: '2xs', vertical: '4xs' }}
          $css={css`
            align-self: flex-start;
            border-radius: var(--c--globals--spacings--3xs);
            color: var(--c--contextuals--content--semantic--neutral--tertiary);
            &:hover {
              color: var(
                --c--contextuals--content--semantic--neutral--secondary
              );
              background-color: var(
                --c--contextuals--background--semantic--contextual--primary
              );
            }
          `}
        >
          <Icon iconName="restart_alt" $size="16px" $color="inherit" />
          <Text $size="xs" $color="inherit">
            {t('Reset the order', {
              description: 'Button putting the left panel items back in order',
            })}
          </Text>
        </BoxButton>
      )}
    </Box>
  );
};
