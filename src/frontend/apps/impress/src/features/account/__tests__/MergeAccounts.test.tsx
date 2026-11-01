import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import fetchMock from 'fetch-mock';
import { beforeEach, describe, expect, test } from 'vitest';

import { AppWrapper } from '@/tests/utils';

import { MergeProposal } from '../MergeAccounts';

const API = 'http://test.jest/api/v1.0';

describe('Merging an account added that has its own', () => {
  beforeEach(() => {
    fetchMock.hardReset();
    fetchMock.mockGlobal();
  });

  test('nothing shows without a merge offered', async () => {
    fetchMock.get(`${API}/users/me/merge/`, { proposal: null });
    render(<MergeProposal />, { wrapper: AppWrapper });
    await waitFor(() =>
      expect(fetchMock.callHistory.called(`${API}/users/me/merge/`)).toBe(true),
    );
    expect(screen.queryByTestId('merge-proposal')).toBeNull();
  });

  test('the merge offered is shown, then confirmed', async () => {
    fetchMock.get(`${API}/users/me/merge/`, {
      proposal: {
        id: 'u-2',
        full_name: 'Ada Work',
        email: 'ada@work.example',
        pages: 3,
        shared_with_it: 2,
        workspaces: 1,
        groups: 0,
      },
    });
    fetchMock.post(`${API}/users/me/merge/`, { merged: 'Ada Work' });
    render(<MergeProposal />, { wrapper: AppWrapper });

    const proposal = await screen.findByTestId('merge-proposal');
    expect(proposal).toHaveTextContent(
      'ada@work.example already has its own Collaborators account. Merge it into this one?',
    );
    expect(proposal).toHaveTextContent(
      'Pages it owns: 3 · shared with it: 2 · workspaces: 1 · user groups: 0.',
    );
    expect(screen.getByRole('button', { name: 'Not now' })).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole('button', { name: 'Merge into this account' }),
    );

    await waitFor(() =>
      expect(
        fetchMock.callHistory
          .calls()
          .some(
            (call) =>
              call.url === `${API}/users/me/merge/` &&
              call.options.method?.toUpperCase() === 'POST',
          ),
      ).toBe(true),
    );
  });
});
