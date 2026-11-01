import {
  Button,
  Checkbox,
  Input,
  Select,
  VariantType,
  useToastProvider,
} from '@gouvfr-lasuite/ui-components';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { css } from 'styled-components';
import { useDebounce } from 'use-debounce';

import { Box, Loading, Text } from '@/components';
import { Role, useTrans } from '@/features/docs/doc-management';
import { WorkspaceRole } from '@/features/workspaces/types';

import {
  PlatformPerson,
  PlatformPlace,
  useAddToPlaces,
  usePlatformPeople,
  usePlatformPlaces,
} from './api';

/** People offered under the search, at most */
const PEOPLE_SHOWN = 8;

const rowCss = css`
  border-top: 1px solid var(--c--contextuals--border--surface--primary);
  padding-top: var(--c--globals--spacings--xs);
  flex-wrap: wrap;
`;

const errorCss = css`
  color: var(--c--contextuals--content--semantic--error--primary);
`;

type ChosenPlace = PlatformPlace & { role: string };

/** The roles each kind of place gives, and the one chosen first. */
const useRoles = () => {
  const { t } = useTranslation();
  const { translatedRoles } = useTrans();
  const workspace = [
    {
      value: WorkspaceRole.MEMBER,
      label: t('Member', { description: 'Workspace role' }),
    },
    {
      value: WorkspaceRole.ADMIN,
      label: t('Administrator', { description: 'Workspace role' }),
    },
    {
      value: WorkspaceRole.OWNER,
      label: t('Owner', { description: 'Workspace role' }),
    },
  ];
  const document = [Role.READER, Role.EDITOR, Role.ADMIN, Role.OWNER].map(
    (role) => ({ value: role, label: translatedRoles[role] }),
  );
  return {
    rolesOf: (kind: PlatformPlace['kind']) =>
      kind === 'workspace' ? workspace : document,
    firstRole: (kind: PlatformPlace['kind']) =>
      kind === 'workspace' ? WorkspaceRole.MEMBER : Role.EDITOR,
  };
};

const useKindLabels = () => {
  const { t } = useTranslation();
  const kinds: Record<PlatformPlace['kind'], string> = {
    workspace: t('Workspace', { description: 'Kind of a place' }),
    space: t('Space', { description: 'Kind of a place' }),
    page: t('Page', { description: 'Kind of a place' }),
  };
  return kinds;
};

/** "Workspace · Acme", "Page · Budget (in Plans)" */
const PlaceName = ({ place }: { place: PlatformPlace }) => {
  const { t } = useTranslation();
  const kinds = useKindLabels();
  return (
    <Box $flex={1} $css="min-width: 200px;" $gap="4xs">
      <Text $weight="600">{place.name}</Text>
      <Text $size="xs" $variation="secondary">
        {[
          kinds[place.kind],
          place.inside &&
            t('in {{space}}', {
              description: 'The space a page is in',
              space: place.inside,
            }),
        ]
          .filter(Boolean)
          .join(' · ')}
      </Text>
    </Box>
  );
};

/** Find people by name or email and pick them. */
const PickPeople = ({
  chosen,
  onChange,
}: {
  chosen: PlatformPerson[];
  onChange: (people: PlatformPerson[]) => void;
}) => {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [debounced] = useDebounce(query.trim(), 250);
  const { data, isLoading } = usePlatformPeople({
    q: debounced,
    role: '',
    status: '',
    account: 'active',
  });
  const found = (data?.pages.flatMap((page) => page.results) ?? [])
    .filter((person) => !chosen.some((other) => other.id === person.id))
    .slice(0, PEOPLE_SHOWN);

  return (
    <Box $gap="xs" data-testid="add-to-places-people">
      <Text $weight="600">
        {t('1. The people to add', {
          description: 'Heading of the people chosen in Add to places',
        })}
      </Text>
      {chosen.map((person) => (
        <Box
          key={person.id}
          $direction="row"
          $align="center"
          $gap="sm"
          $css={rowCss}
        >
          <Box $flex={1} $css="min-width: 200px;">
            <Text $weight="600">{person.full_name || person.email}</Text>
            <Text $size="xs" $variation="secondary">
              {person.email}
            </Text>
          </Box>
          <Button
            size="small"
            variant="tertiary"
            onClick={() =>
              onChange(chosen.filter((other) => other.id !== person.id))
            }
          >
            {t('Remove', { description: 'Button taking a choice back' })}
          </Button>
        </Box>
      ))}
      <Input
        fullWidth
        label={t('Find someone by name or email', {
          description: 'Label of the search in Manage Collaborators',
        })}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      {isLoading && <Loading />}
      {debounced &&
        found.map((person) => (
          <Box
            key={person.id}
            $direction="row"
            $align="center"
            $gap="sm"
            $css={rowCss}
          >
            <Box $flex={1} $css="min-width: 200px;">
              <Text>{person.full_name || person.email}</Text>
              <Text $size="xs" $variation="secondary">
                {person.email}
              </Text>
            </Box>
            <Button
              size="small"
              variant="secondary"
              onClick={() => onChange([...chosen, person])}
            >
              {t('Choose', { description: 'Button picking a result' })}
            </Button>
          </Box>
        ))}
    </Box>
  );
};

/** Find workspaces, spaces and pages by name and pick them, with a role. */
const PickPlaces = ({
  chosen,
  onChange,
}: {
  chosen: ChosenPlace[];
  onChange: (places: ChosenPlace[]) => void;
}) => {
  const { t } = useTranslation();
  const { rolesOf, firstRole } = useRoles();
  const [query, setQuery] = useState('');
  const [debounced] = useDebounce(query.trim(), 250);
  const { data, isLoading } = usePlatformPlaces(debounced);
  const found = (data ?? []).filter(
    (place) => !chosen.some((other) => other.id === place.id),
  );

  return (
    <Box $gap="xs" data-testid="add-to-places-places">
      <Text $weight="600">
        {t('2. The places, with the role in each', {
          description: 'Heading of the places chosen in Add to places',
        })}
      </Text>
      {chosen.map((place) => (
        <Box
          key={place.id}
          $direction="row"
          $align="center"
          $gap="sm"
          $css={rowCss}
        >
          <PlaceName place={place} />
          <Box $width="170px">
            <Select
              fullWidth
              label={t('Role in {{place}}', {
                description: 'Label of the role given on a place',
                place: place.name,
              })}
              hideLabel
              clearable={false}
              options={rolesOf(place.kind)}
              value={place.role}
              onChange={(event) =>
                onChange(
                  chosen.map((other) =>
                    other.id === place.id
                      ? { ...other, role: String(event.target.value) }
                      : other,
                  ),
                )
              }
            />
          </Box>
          <Button
            size="small"
            variant="tertiary"
            onClick={() =>
              onChange(chosen.filter((other) => other.id !== place.id))
            }
          >
            {t('Remove', { description: 'Button taking a choice back' })}
          </Button>
        </Box>
      ))}
      <Input
        fullWidth
        label={t('Find a workspace, space or page by name', {
          description: 'Label of the search of places in Add to places',
        })}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      {isLoading && <Loading />}
      {debounced && data?.length === 0 && (
        <Text $size="sm" $variation="secondary">
          {t('Nothing has this name.', {
            description: 'No place found in Add to places',
          })}
        </Text>
      )}
      {debounced &&
        found.map((place) => (
          <Box
            key={place.id}
            $direction="row"
            $align="center"
            $gap="sm"
            $css={rowCss}
          >
            <PlaceName place={place} />
            <Button
              size="small"
              variant="secondary"
              onClick={() =>
                onChange([...chosen, { ...place, role: firstRole(place.kind) }])
              }
            >
              {t('Choose', { description: 'Button picking a result' })}
            </Button>
          </Box>
        ))}
    </Box>
  );
};

/**
 * "Add to places", for platform owners: put people straight into any
 * workspace, space or page of the platform, with a role in each, apart
 * from invitations (nothing to accept). They are told by one email each,
 * unless the owner unchecks it; a role already higher is kept.
 */
export const AddToPlaces = () => {
  const { t } = useTranslation();
  const { toast } = useToastProvider();
  const [people, setPeople] = useState<PlatformPerson[]>([]);
  const [places, setPlaces] = useState<ChosenPlace[]>([]);
  const [notify, setNotify] = useState(true);
  const add = useAddToPlaces();

  const submit = () =>
    add.mutate(
      {
        people: people.map((person) => person.id),
        places: places.map(({ kind, id, role }) => ({ kind, id, role })),
        notify,
      },
      {
        onSuccess: (outcomes) => {
          const kept = outcomes
            .flatMap((outcome) => outcome.places)
            .filter((place) => place.result === 'already').length;
          toast(
            [
              t('Done: they are in these places now.', {
                description: 'People were added in Add to places',
              }),
              kept > 0 &&
                t(
                  '{{count}} already had that role or a higher one, kept as it was.',
                  {
                    description: 'Additions that changed nothing',
                    count: kept,
                  },
                ),
            ]
              .filter(Boolean)
              .join(' '),
            VariantType.SUCCESS,
          );
          setPeople([]);
          setPlaces([]);
        },
      },
    );

  return (
    <Box $gap="md" data-testid="add-to-places">
      <Text $variation="secondary">
        {t(
          'Put people straight into any workspace, space or page of the platform, with the role you choose in each. This is not an invitation: there is nothing for them to accept. Nobody loses a higher role they already have.',
          { description: 'Introduction of the Add to places tab' },
        )}
      </Text>
      <PickPeople chosen={people} onChange={setPeople} />
      <PickPlaces chosen={places} onChange={setPlaces} />
      <Checkbox
        label={t('Tell them by email where they were added', {
          description: 'Checkbox sending the email of Add to places',
        })}
        checked={notify}
        onChange={(event) => setNotify(event.target.checked)}
      />
      {add.error && (
        <Text $size="sm" $css={errorCss}>
          {add.error.cause?.[0]}
        </Text>
      )}
      <Box $direction="row">
        <Button
          disabled={!people.length || !places.length || add.isPending}
          onClick={submit}
        >
          {t('Add {{people}} people to {{places}} places', {
            description: 'Button of Add to places',
            people: people.length,
            places: places.length,
          })}
        </Button>
      </Box>
    </Box>
  );
};
