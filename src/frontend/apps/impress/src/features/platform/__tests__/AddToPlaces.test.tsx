import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import fetchMock from 'fetch-mock';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import { User } from '@/features/auth/api';
import { AppWrapper } from '@/tests/utils';

import { AddToPlaces } from '../AddToPlaces';
import { CollaboratorsTabs } from '../CollaboratorsTabs';

const API = 'http://test.jest/api/v1.0';

const me: { current: Partial<User> } = { current: {} };

vi.mock('@/features/auth/hooks/useAuth', () => ({
  useAuth: () => ({ user: me.current, authenticated: true }),
}));

const person = {
  id: 'u-1',
  full_name: 'Muhammet',
  email: 'muhammet@example.org',
  email_verified: true,
  platform_role: 'collaborator',
  registration_status: 'approved',
  created_at: '2026-10-26T10:00:00Z',
  last_login: null,
  workspaces: 0,
  pages: 0,
  suspended: false,
  can_manage: true,
  levels_you_may_give: [],
};

describe('Add to places', () => {
  beforeEach(() => {
    fetchMock.hardReset();
    fetchMock.mockGlobal();
    fetchMock.get(`begin:${API}/people/directory/`, []);
    fetchMock.get(`begin:${API}/platform/people/`, {
      count: 1,
      next: null,
      previous: null,
      results: [person],
    });
    fetchMock.get(`begin:${API}/platform/places/`, [
      { kind: 'workspace', id: 'w-1', name: 'Acme' },
      { kind: 'page', id: 'd-1', name: 'Budget', inside: 'Plans' },
    ]);
  });

  test('only platform owners see the tab', () => {
    me.current = { platform_role: 'administrator' };
    const { unmount } = render(<CollaboratorsTabs />, { wrapper: AppWrapper });
    expect(screen.queryByRole('tab', { name: 'Add to places' })).toBeNull();
    unmount();

    me.current = { platform_role: 'owner' };
    render(<CollaboratorsTabs />, { wrapper: AppWrapper });
    expect(screen.getByRole('tab', { name: 'Add to places' })).toBeVisible();
  });

  test('an owner picks people and places, each with a role', async () => {
    fetchMock.post(`${API}/platform/add-to-places/`, [
      {
        id: 'u-1',
        places: [
          {
            kind: 'workspace',
            id: 'w-1',
            name: 'Acme',
            role: 'member',
            result: 'added',
          },
          {
            kind: 'page',
            id: 'd-1',
            name: 'Budget',
            role: 'editor',
            result: 'already',
          },
        ],
      },
    ]);
    render(<AddToPlaces />, { wrapper: AppWrapper });

    const add = screen.getByRole('button', { name: /Add 0 people/ });
    expect(add).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Find someone by name or email'), {
      target: { value: 'muh' },
    });
    const people = screen.getByTestId('add-to-places-people');
    await waitFor(() => expect(people).toHaveTextContent('Muhammet'));
    fireEvent.click(screen.getAllByRole('button', { name: 'Choose' })[0]);

    fireEvent.change(
      screen.getByLabelText('Find a workspace, space or page by name'),
      { target: { value: 'a' } },
    );
    const places = screen.getByTestId('add-to-places-places');
    await waitFor(() => expect(places).toHaveTextContent('Budget'));
    expect(places).toHaveTextContent('Page · in Plans');
    const choose = () => places.querySelectorAll<HTMLButtonElement>('button');
    fireEvent.click(
      [...choose()].find((button) => button.textContent === 'Choose')!,
    );
    await waitFor(() =>
      expect(
        [...choose()].filter((button) => button.textContent === 'Choose'),
      ).toHaveLength(1),
    );
    fireEvent.click(
      [...choose()].find((button) => button.textContent === 'Choose')!,
    );

    fireEvent.click(
      screen.getByRole('checkbox', { name: /Tell them by email/ }),
    );
    fireEvent.click(
      await screen.findByRole('button', { name: 'Add 1 people to 2 places' }),
    );

    await waitFor(() => {
      const call = fetchMock.callHistory
        .calls()
        .find((entry) => entry.url === `${API}/platform/add-to-places/`);
      expect(JSON.parse(call?.options.body as string)).toEqual({
        people: ['u-1'],
        places: [
          { kind: 'workspace', id: 'w-1', role: 'member' },
          { kind: 'page', id: 'd-1', role: 'editor' },
        ],
        notify: false,
      });
    });
    expect(
      await screen.findByText(/1 already had that role or a higher one/),
    ).toBeInTheDocument();
  });
});
