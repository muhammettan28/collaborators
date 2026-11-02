import { fireEvent, render, screen, within } from '@testing-library/react';
import fetchMock from 'fetch-mock';
import { beforeEach, describe, expect, test } from 'vitest';

import { AppWrapper } from '@/tests/utils';

import { GroupHoverCard } from '../GroupHoverCard';

const API = 'http://test.jest/api/v1.0';

describe('GroupHoverCard', () => {
  beforeEach(() => {
    fetchMock.hardReset();
    fetchMock.mockGlobal();
  });

  test('lists who is in a group on hover', async () => {
    fetchMock.get(`${API}/teams/group%3Ag-1/`, {
      team: 'group:g-1',
      kind: 'team',
      name: 'Q4 Launch',
      known: true,
      workspace: { id: 'w-1', name: 'Acme' },
      place: { kind: 'workspace', id: 'w-1', name: 'Acme' },
      member_count: 3,
      members: [
        {
          id: 'u-1',
          full_name: 'Ada Lovelace',
          short_name: 'Ada',
          is_me: false,
          is_manager: true,
        },
        {
          id: 'u-2',
          full_name: 'Bob Martin',
          short_name: 'Bob',
          is_me: true,
          is_manager: false,
        },
      ],
    });

    render(
      <GroupHoverCard team="group:g-1" name="Q4 Launch">
        <span>@Q4 Launch</span>
      </GroupHoverCard>,
      { wrapper: AppWrapper },
    );
    expect(screen.queryByTestId('group-hover-card')).not.toBeInTheDocument();

    fireEvent.mouseEnter(
      screen.getByText('@Q4 Launch').parentElement as Element,
    );

    const card = await screen.findByTestId('group-hover-card');
    expect(await within(card).findByText('3 members')).toBeInTheDocument();
    expect(card).toHaveTextContent('Team · Acme');
    const members = within(card).getByTestId('group-hover-card-members');
    expect(members).toHaveTextContent('Ada Lovelace');
    expect(members).toHaveTextContent('Manager');
    expect(members).toHaveTextContent('Bob Martin (you)');
    expect(within(card).getByText('and 1 more')).toBeInTheDocument();
    expect(
      within(card).getByRole('link', { name: /Ada Lovelace/ }),
    ).toHaveAttribute('href', expect.stringContaining('u-1'));
  });

  test('outside the workspace shows only the name', async () => {
    fetchMock.get(`${API}/teams/group%3Ag-2/`, {
      team: 'group:g-2',
      kind: 'organization',
      name: 'Partners',
      known: false,
      workspace: null,
      member_count: 0,
      members: [],
    });

    render(
      <GroupHoverCard team="group:g-2" name="Partners">
        <span>@Partners</span>
      </GroupHoverCard>,
      { wrapper: AppWrapper },
    );
    fireEvent.mouseEnter(
      screen.getByText('@Partners').parentElement as Element,
    );

    expect(
      await screen.findByText(
        'Only people of this user group’s workspace see who is in it.',
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByTestId('group-hover-card-members'),
    ).not.toBeInTheDocument();
  });
});
