import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import fetchMock from 'fetch-mock';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import { AppWrapper } from '@/tests/utils';

import { Group, GroupKind } from '../../types';
import { MoveMembersModal } from '../MoveMembersModal';

const API = 'http://test.jest/api/v1.0';

const group = (id: string, name: string): Group => ({
  id,
  workspace: 'ws-1',
  document: null,
  name,
  kind: GroupKind.TEAM,
  description: '',
  team: `group:${id}`,
  nb_members: 1,
  created_by: null,
  abilities: {
    destroy: true,
    manage_managers: true,
    manage_members: true,
    partial_update: true,
    retrieve: true,
    update: true,
  },
  created_at: '',
});

describe('MoveMembersModal', () => {
  beforeEach(() => {
    fetchMock.hardReset();
    fetchMock.mockGlobal();
  });

  test('copies the chosen people into the chosen group', async () => {
    fetchMock.post(`${API}/groups/g-1/members/transfer/`, { count: 2 });
    const onDone = vi.fn();
    const onClose = vi.fn();

    render(
      <MoveMembersModal
        group={group('g-1', 'First')}
        targets={[group('g-2', 'Second')]}
        userIds={['u-1', 'u-2']}
        onDone={onDone}
        onClose={onClose}
      />,
      { wrapper: AppWrapper },
    );

    await userEvent.click(screen.getByRole('combobox'));
    await userEvent.click(await screen.findByText('Second'));
    await userEvent.click(
      screen.getByLabelText('Copy: they stay in First too'),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Copy' }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(
      JSON.parse(
        fetchMock.callHistory.lastCall(`${API}/groups/g-1/members/transfer/`)
          ?.options.body as string,
      ),
    ).toEqual({ user_ids: ['u-1', 'u-2'], to_group_id: 'g-2', mode: 'copy' });
    expect(onClose).toHaveBeenCalled();
  });
});
