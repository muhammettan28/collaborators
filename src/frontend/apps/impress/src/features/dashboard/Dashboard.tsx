import {
  CollisionDetection,
  DndContext,
  DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  UniqueIdentifier,
  closestCenter,
  pointerWithin,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import { DropdownMenu, DropdownMenuItem } from '@gouvfr-lasuite/ui-components';
import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';

import { Box, BoxButton, Icon, SCREEN_MAX_WIDTH, Text } from '@/components';
import { AccountHints } from '@/features/account/AccountHints';
import { useAuth } from '@/features/auth';
import { useResponsiveStore } from '@/stores';

import { CARD_ICON_GAP, CARD_ICON_SIZE } from './CardParts';
import { HierarchyNote } from './HierarchyNote';
import { CardLayout, useDashboardLayout } from './api';
import { CARDS, DEFAULT_LAYOUT, mergeLayout } from './cards';

const IconButton = ({
  icon,
  label,
  onClick,
  disabled,
  ...rest
}: {
  icon: string;
  label: string;
  onClick?: () => void;
  disabled?: boolean;
} & Record<string, unknown>) => (
  <BoxButton
    aria-label={label}
    title={label}
    onClick={onClick}
    disabled={disabled}
    $padding="3xs"
    $css="border-radius: 4px; touch-action: none;"
    {...rest}
  >
    <Icon iconName={icon} $size="20px" $variation="secondary" />
  </BoxButton>
);

interface DashboardCardProps {
  card: CardLayout;
  index: number;
  count: number;
  onChange: (changes: Partial<CardLayout>) => void;
  onMove: (to: number) => void;
  /** The edge dragged to change the width: the outer one of its column */
  edge: 'left' | 'right';
}

/** A card's handle, menu and resize edge show on hover (or focus) only. */
const cardCss = css`
  .--collaborators--card-tool {
    visibility: hidden;
  }
  &:hover .--collaborators--card-tool,
  &:focus-within .--collaborators--card-tool,
  .--collaborators--card-tool[aria-expanded='true'] {
    visibility: visible;
  }
  .--collaborators--card-resize {
    position: absolute;
    top: 8px;
    bottom: 8px;
    width: 12px;
    &.is-right {
      right: -6px;
    }
    &.is-left {
      left: -6px;
    }
    cursor: col-resize;
    touch-action: none;
    z-index: 2;
    &::after {
      content: '';
      position: absolute;
      top: 0;
      bottom: 0;
      left: 5px;
      width: 2px;
      border-radius: 2px;
      background: var(--c--globals--colors--brand-400);
      opacity: 0;
      transition: opacity 0.15s;
    }
    &:hover::after,
    &:focus-visible::after {
      opacity: 1;
    }
  }
  .--collaborators--card-resize-preview {
    position: absolute;
    top: -1px;
    bottom: -1px;
    border: 2px dashed var(--c--globals--colors--brand-400);
    border-radius: var(--c--globals--spacings--xs);
    background: color-mix(
      in srgb,
      var(--c--globals--colors--brand-400) 6%,
      transparent
    );
    pointer-events: none;
    z-index: 3;
    transition: width 0.12s ease-out;
    span {
      position: absolute;
      top: 8px;
      right: 10px;
      font-size: 12px;
      font-weight: 600;
      color: var(--c--globals--colors--brand-500, #4f46e5);
      background: var(--c--contextuals--background--surface--primary, #fff);
      padding: 2px 8px;
      border-radius: 999px;
    }
  }
`;

/**
 * The card a dragged one is dropped on: the one under the pointer, else
 * (in the space around the cards) the nearest other one.
 */
const cardNearPointer: CollisionDetection = (args) => {
  const under = pointerWithin(args);
  if (under.length) {
    return under;
  }
  const others = args.droppableContainers.filter(
    (container) => container.id !== args.active.id,
  );
  const pointer = args.pointerCoordinates;
  if (!pointer) {
    return closestCenter({ ...args, droppableContainers: others });
  }
  let nearest: { id: UniqueIdentifier; distance: number } | null = null;
  for (const container of others) {
    const rect = args.droppableRects.get(container.id);
    if (!rect) {
      continue;
    }
    const dx = Math.max(rect.left - pointer.x, 0, pointer.x - rect.right);
    const dy = Math.max(rect.top - pointer.y, 0, pointer.y - rect.bottom);
    const distance = Math.hypot(dx, dy);
    if (!nearest || distance < nearest.distance) {
      nearest = { id: container.id, distance };
    }
  }
  return nearest ? [{ id: nearest.id }] : [];
};

/**
 * The cards shown, cut into runs of cards side by side and wide cards; each
 * keeps its place in the whole order (for moving it up or down).
 */
export const sections = (cards: CardLayout[], isMobile: boolean) =>
  cards.reduce<
    { wide: boolean; items: { card: CardLayout; index: number }[] }[]
  >((result, card, index) => {
    const wide = !!card.wide && !isMobile;
    const last = result[result.length - 1];
    if (!wide && last && !last.wide) {
      last.items.push({ card, index });
    } else {
      result.push({ wide, items: [{ card, index }] });
    }
    return result;
  }, []);

const DashboardCard = ({
  card,
  index,
  count,
  onChange,
  onMove,
  edge,
}: DashboardCardProps) => {
  const { t } = useTranslation();
  const { isMobile } = useResponsiveStore();
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const sectionRef = useRef<HTMLElement | null>(null);
  // While its edge is dragged: where the card would end, and whether it
  // would then go across both columns
  const [resize, setResize] = useState<{
    /** The card, and the area of both columns, when the drag began */
    box: DOMRect;
    area: DOMRect;
    column: number;
    pointer: number;
  } | null>(null);
  // Past halfway between one and two columns, it goes across both
  const resizeWide = resize
    ? (edge === 'right'
        ? resize.pointer - resize.box.left
        : resize.box.right - resize.pointer) >
      (resize.column + resize.area.width) / 2
    : !!card.wide;
  const definition = CARDS.find((item) => item.id === card.id);
  const drag = useDraggable({ id: card.id });
  const drop = useDroppable({ id: card.id });
  if (!definition) {
    return null;
  }
  const title = definition.title(t);
  const Body = definition.Body;
  const menu: DropdownMenuItem[] = [
    {
      label: t('Move up', { description: 'Dashboard card action' }),
      icon: <Icon iconName="arrow_upward" $size="18px" />,
      isDisabled: index === 0,
      callback: () => onMove(index - 1),
    },
    {
      label: t('Move down', { description: 'Dashboard card action' }),
      icon: <Icon iconName="arrow_downward" $size="18px" />,
      isDisabled: index === count - 1,
      callback: () => onMove(index + 1),
    },
    { type: 'separator' },
    {
      label: t('Hide this card', { description: 'Dashboard card action' }),
      icon: <Icon iconName="visibility_off" $size="18px" />,
      callback: () => onChange({ hidden: true }),
    },
  ];

  return (
    <Box
      as="section"
      ref={(node: HTMLElement | null) => {
        drop.setNodeRef(node);
        sectionRef.current = node;
      }}
      aria-label={title}
      $css={css`
        border: 1px solid var(--c--contextuals--border--surface--primary);
        border-radius: var(--c--globals--spacings--xs);
        background: var(--c--contextuals--background--surface--primary);
        /* The inner alignment of the dashboard's notes: everything starts
           on one left edge, the drag handle sitting in the margin */
        padding: var(--c--globals--spacings--xs) var(--c--globals--spacings--sm);
        opacity: ${drag.isDragging ? 0.5 : 1};
        box-shadow: ${
          drop.isOver && !drag.isDragging
            ? '0 0 0 2px var(--c--globals--colors--brand-400)'
            : 'none'
        };
        transform: ${
          drag.transform
            ? `translate(${drag.transform.x}px, ${drag.transform.y}px)`
            : 'none'
        };
        z-index: ${drag.isDragging ? 10 : 'auto'};
        position: relative;
        ${cardCss}
      `}
    >
      <Box
        $direction="row"
        $align="center"
        $gap={CARD_ICON_GAP}
        $position="relative"
      >
        <span
          ref={drag.setNodeRef}
          {...drag.listeners}
          {...drag.attributes}
          className="--collaborators--card-tool"
          aria-label={t('Move the {{name}} card', {
            description: 'Accessible name of a dashboard card drag handle',
            name: title,
          })}
          title={t('Drag to move', {
            description: 'Tooltip of a dashboard card drag handle',
          })}
          style={{
            cursor: 'grab',
            display: 'inline-flex',
            touchAction: 'none',
            position: 'absolute',
            left: 'calc(-1 * var(--c--globals--spacings--sm))',
          }}
        >
          <Icon iconName="drag_indicator" $size="16px" $variation="secondary" />
        </span>
        <Icon
          iconName={definition.icon}
          $size={CARD_ICON_SIZE}
          $variation="secondary"
        />
        <Text as="h2" $size="md" $weight="700" $margin="none" $css="flex: 1;">
          {title}
        </Text>
        <DropdownMenu
          options={menu}
          isOpen={isMenuOpen}
          onOpenChange={setIsMenuOpen}
        >
          <IconButton
            icon="more_horiz"
            label={t('{{name}} options', {
              description: 'Dashboard card menu button',
              name: title,
            })}
            className="--collaborators--card-tool"
            aria-expanded={isMenuOpen}
            onClick={() => setIsMenuOpen(!isMenuOpen)}
          />
        </DropdownMenu>
        <IconButton
          icon={card.collapsed ? 'expand_more' : 'expand_less'}
          label={
            card.collapsed
              ? t('Expand {{name}}', {
                  description: 'Dashboard card action',
                  name: title,
                })
              : t('Collapse {{name}}', {
                  description: 'Dashboard card action',
                  name: title,
                })
          }
          aria-expanded={!card.collapsed}
          onClick={() => onChange({ collapsed: !card.collapsed })}
        />
      </Box>
      {!card.collapsed && (
        // Rows keep their own padding (for their hover): pulled back by it,
        // their icons line up under the card's icon, their text under its title
        <Box
          $margin={{ top: 'xs' }}
          $gap="4xs"
          $css={css`
            margin-inline: calc(-1 * var(--c--globals--spacings--xs));
          `}
        >
          <Body wide={!!card.wide && !isMobile} />
        </Box>
      )}
      {!isMobile && (
        // The right edge: drag it to make the card one or two columns wide,
        // like the border of a table cell
        <div
          className={`--collaborators--card-resize is-${edge}`}
          role="separator"
          aria-orientation="vertical"
          aria-valuenow={card.wide ? 2 : 1}
          aria-valuemin={1}
          aria-valuemax={2}
          aria-label={t('Width of the {{name}} card', {
            description: 'Accessible name of a dashboard card resize edge',
            name: title,
          })}
          title={t('Drag to make it one or two columns wide', {
            description: 'Tooltip of a dashboard card resize edge',
          })}
          tabIndex={0}
          onKeyDown={(event) => {
            // Outward makes it wide, inward narrow
            const outward = edge === 'right' ? 'ArrowRight' : 'ArrowLeft';
            const inward = edge === 'right' ? 'ArrowLeft' : 'ArrowRight';
            if (event.key === outward && !card.wide) {
              event.preventDefault();
              onChange({ wide: true });
            }
            if (event.key === inward && card.wide) {
              event.preventDefault();
              onChange({ wide: false });
            }
          }}
          onPointerDown={(event) => {
            const section = sectionRef.current;
            const columns = section?.closest(
              '.--collaborators--dashboard-columns',
            );
            if (!section || !columns) {
              return;
            }
            event.preventDefault();
            event.currentTarget.setPointerCapture(event.pointerId);
            const area = columns.getBoundingClientRect();
            const gap = 16;
            setResize({
              box: section.getBoundingClientRect(),
              area,
              column: (area.width - gap) / 2,
              pointer: event.clientX,
            });
          }}
          onPointerMove={(event) => {
            if (resize) {
              setResize({ ...resize, pointer: event.clientX });
            }
          }}
          onPointerUp={() => {
            if (resize && resizeWide !== !!card.wide) {
              onChange({ wide: resizeWide });
            }
            setResize(null);
          }}
          onPointerCancel={() => setResize(null)}
        />
      )}
      {resize && (
        // Where the card would end, snapped to one or two columns
        <div
          className="--collaborators--card-resize-preview"
          style={
            resizeWide
              ? {
                  left: resize.area.left - resize.box.left - 1,
                  width: resize.area.width,
                }
              : {
                  left:
                    edge === 'right'
                      ? -1
                      : resize.box.width - resize.column - 1,
                  width: resize.column,
                }
          }
        >
          <span>
            {resizeWide
              ? t('Two columns', { description: 'Dashboard card width' })
              : t('One column', { description: 'Dashboard card width' })}
          </span>
        </div>
      )}
    </Box>
  );
};

/**
 * The landing screen after sign-in: lean by default (search and three
 * cards). Each collaborator collapses, hides, shows and reorders cards right
 * there: drag a card by its handle, or use its "⋯" menu; drag its right edge
 * to make it one or two columns wide.
 */
export const Dashboard = () => {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { isMobile } = useResponsiveStore();
  const [isAddMenuOpen, setIsAddMenuOpen] = useState(false);
  const { query, save } = useDashboardLayout();
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor),
  );

  if (!query.isFetched) {
    return null;
  }
  const layout = mergeLayout(query.data ?? []);
  const visible = layout.filter((card) => !card.hidden);
  const hidden = layout.filter((card) => card.hidden);

  const update = (next: CardLayout[]) => save.mutate(next);
  const change = (id: string, changes: Partial<CardLayout>) =>
    update(
      layout.map((card) => (card.id === id ? { ...card, ...changes } : card)),
    );
  /** Move a visible card to another place among the visible cards. */
  /** Put a card just before or just after another one. */
  const place = (id: string, targetId: string, side: 'before' | 'after') => {
    const moving = layout.find((card) => card.id === id);
    if (!moving || id === targetId) {
      return;
    }
    const rest = layout.filter((card) => card.id !== id);
    const at = rest.findIndex((card) => card.id === targetId);
    rest.splice(side === 'after' ? at + 1 : at, 0, moving);
    update(rest);
  };
  /** Move a card to another place among the shown cards (its menu). */
  const move = (id: string, toVisibleIndex: number) => {
    const target = visible[toVisibleIndex];
    const from = visible.findIndex((card) => card.id === id);
    if (target) {
      place(id, target.id, from < toVisibleIndex ? 'after' : 'before');
    }
  };
  const onDragEnd = (event: DragEndEvent) => {
    const { active, over, delta, activatorEvent } = event;
    if (!over || over.id === active.id) {
      return;
    }
    const from = visible.findIndex((card) => card.id === active.id);
    const to = visible.findIndex((card) => card.id === over.id);
    // Dropped on a card: it takes that card's place
    let side: 'before' | 'after' = from < to ? 'after' : 'before';
    // Dropped in the space around (e.g. below the last card): it goes on the
    // side of the nearest card where it was dropped
    const start = activatorEvent as Partial<PointerEvent> | null;
    if (start?.clientX !== undefined && start.clientY !== undefined) {
      const x = start.clientX + delta.x;
      const y = start.clientY + delta.y;
      const { top, bottom, left, right } = over.rect;
      if (y > bottom || (y >= top && x > right)) {
        side = 'after';
      } else if (y < top || (y <= bottom && x < left)) {
        side = 'before';
      }
    }
    place(String(active.id), String(over.id), side);
  };

  const firstName = user?.short_name || user?.full_name?.split(' ')[0];
  const renderCard = (
    { card, index }: { card: CardLayout; index: number },
    edge: 'left' | 'right' = 'right',
  ) => (
    <DashboardCard
      key={card.id}
      card={card}
      index={index}
      count={visible.length}
      onChange={(changes) => change(card.id, changes)}
      onMove={(to) => move(card.id, to)}
      edge={edge}
    />
  );

  return (
    <Box
      $width="100%"
      $maxWidth={SCREEN_MAX_WIDTH}
      $margin={{ horizontal: 'auto' }}
      $padding={{ horizontal: isMobile ? 'sm' : 'lg', vertical: 'lg' }}
      $gap="md"
      className="--collaborators--dashboard"
    >
      <Box
        $direction="row"
        $align="center"
        $justify="space-between"
        $gap="sm"
        $css="flex-wrap: wrap;"
      >
        <Text as="h1" $size="h4" $margin="none">
          {firstName
            ? t('Welcome back, {{name}}', {
                description: 'Dashboard greeting',
                name: firstName,
              })
            : t('Welcome back', { description: 'Dashboard greeting' })}
        </Text>
        {/* Hidden cards come back from here; the layout can be reset too */}
        <DropdownMenu
          options={[
            // In the order of the cards (Starred, Owned by me, Shared...)
            ...CARDS.filter((definition) =>
              hidden.some((card) => card.id === definition.id),
            ).map((definition) => ({
              label: definition.title(t),
              icon: <Icon iconName={definition.icon} $size="18px" />,
              callback: () => change(definition.id, { hidden: false }),
            })),
            ...(hidden.length ? [{ type: 'separator' as const }] : []),
            {
              label: t('Reset the dashboard', {
                description: 'Dashboard action putting the default cards back',
              }),
              icon: <Icon iconName="restart_alt" $size="18px" />,
              callback: () => update(DEFAULT_LAYOUT),
            },
          ]}
          isOpen={isAddMenuOpen}
          onOpenChange={setIsAddMenuOpen}
        >
          <BoxButton
            onClick={() => setIsAddMenuOpen(!isAddMenuOpen)}
            aria-expanded={isAddMenuOpen}
            $direction="row"
            $align="center"
            $gap="3xs"
            $padding={{ horizontal: 'xs', vertical: '3xs' }}
            $css={css`
              border-radius: var(--c--globals--spacings--3xs);
              color: var(
                --c--contextuals--content--semantic--neutral--secondary
              );
              &:hover {
                background: var(
                  --c--contextuals--background--semantic--contextual--primary
                );
              }
            `}
          >
            <Icon iconName="add" $size="18px" $color="inherit" />
            <Text $size="sm" $color="inherit">
              {t('Add a card', { description: 'Dashboard hidden cards menu' })}
            </Text>
          </BoxButton>
        </DropdownMenu>
      </Box>

      <AccountHints />

      <HierarchyNote />

      <BoxButton
        onClick={() =>
          document.dispatchEvent(
            new KeyboardEvent('keydown', {
              key: 'k',
              metaKey: true,
              ctrlKey: true,
              bubbles: true,
            }),
          )
        }
        $direction="row"
        $align="center"
        $gap="xs"
        $width="100%"
        $padding={{ horizontal: 'sm', vertical: 'xs' }}
        $css={css`
          border: 1px solid var(--c--contextuals--border--surface--primary);
          border-radius: var(--c--globals--spacings--xs);
          color: var(--c--contextuals--content--semantic--neutral--secondary);
          text-align: left;
          &:hover {
            border-color: var(--c--globals--colors--brand-400);
          }
        `}
      >
        <Icon iconName="search" $size="20px" $variation="secondary" />
        <Text $size="sm" $variation="secondary" $css="flex: 1;">
          {t('Search', { description: 'Dashboard search box' })}
        </Text>
        <Text $size="xs" $variation="secondary">
          ⌘K
        </Text>
      </BoxButton>

      <DndContext
        sensors={sensors}
        collisionDetection={cardNearPointer}
        onDragEnd={onDragEnd}
      >
        <Box $gap="sm" className="--collaborators--dashboard-columns">
          {/* Runs of cards in two columns that stack independently (cards
              in turn left and right), a wide card across both; one column
              on phones */}
          {sections(visible, isMobile).map((section) =>
            section.wide ? (
              renderCard(section.items[0])
            ) : (
              <Box
                key={section.items[0].card.id}
                $direction="row"
                $gap="sm"
                $align="flex-start"
              >
                {(isMobile ? [0] : [0, 1]).map((column) => (
                  <Box key={column} $flex={1} $gap="sm" $css="min-width: 0;">
                    {section.items
                      .filter(
                        (_item, position) =>
                          isMobile || position % 2 === column,
                      )
                      .map((item) =>
                        // A card on the right widens from its left edge
                        renderCard(item, column === 1 ? 'left' : 'right'),
                      )}
                  </Box>
                ))}
              </Box>
            ),
          )}
        </Box>
      </DndContext>
    </Box>
  );
};
