import { fireEvent, render, screen } from '@testing-library/react';
import fetchMock from 'fetch-mock';
import { beforeEach, describe, expect, test } from 'vitest';

import { AppWrapper } from '@/tests/utils';

import { PersonHoverCard } from '../PersonHoverCard';

const API = 'http://test.jest/api/v1.0';

describe('PersonHoverCard', () => {
  beforeEach(() => {
    fetchMock.hardReset();
    fetchMock.mockGlobal();
  });

  test('shows the card of someone one works with on hover', async () => {
    fetchMock.get(`${API}/people/u-1/`, {
      id: 'u-1',
      full_name: 'Ada Lovelace',
      short_name: 'Ada',
      is_me: false,
      known: true,
      email: 'ada@acme.org',
      workspaces: [{ id: 'w-1', name: 'Acme' }],
      groups: [{ id: 'g-1', name: 'Q4' }],
    });

    render(
      <PersonHoverCard userId="u-1" name="Ada">
        <span>@Ada</span>
      </PersonHoverCard>,
      { wrapper: AppWrapper },
    );
    expect(screen.queryByTestId('person-hover-card')).not.toBeInTheDocument();

    fireEvent.mouseEnter(screen.getByText('@Ada').parentElement as Element);

    const card = await screen.findByTestId('person-hover-card');
    expect(await screen.findByText('ada@acme.org')).toBeInTheDocument();
    expect(card).toHaveTextContent('Ada Lovelace');
    expect(screen.getByText('Workspaces: Acme')).toBeInTheDocument();
    expect(screen.getByText('User groups: Q4')).toBeInTheDocument();
  });

  test('a stranger shows only their name', async () => {
    fetchMock.get(`${API}/people/u-2/`, {
      id: 'u-2',
      full_name: 'Zed',
      short_name: '',
      is_me: false,
      known: false,
      email: '',
      workspaces: [],
      groups: [],
    });

    render(
      <PersonHoverCard userId="u-2" name="Zed">
        <span>@Zed</span>
      </PersonHoverCard>,
      { wrapper: AppWrapper },
    );
    fireEvent.mouseEnter(screen.getByText('@Zed').parentElement as Element);

    expect(
      await screen.findByText(
        'You don’t share a workspace or page with this person yet.',
      ),
    ).toBeInTheDocument();
  });
});
