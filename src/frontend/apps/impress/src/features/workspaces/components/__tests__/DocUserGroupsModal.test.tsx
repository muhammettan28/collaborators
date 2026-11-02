import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import fetchMock from 'fetch-mock';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import { Doc, Role } from '@/features/docs/doc-management';
import { AppWrapper } from '@/tests/utils';

import { Group, GroupKind } from '../../types';
import { DocUserGroupsModal } from '../DocUserGroupsModal';

const API = 'http://test.jest/api/v1.0';

const page = (userRole: Role) =>
  ({
    id: 'd-1',
    title: 'Introduction',
    kind: 'page',
    user_role: userRole,
  }) as unknown as Doc;

const group = (id: string, name: string, canManage: boolean): Group => ({
  id,
  workspace: null,
  document: 'd-1',
  name,
  kind: GroupKind.TEAM,
  description: '',
  team: `group:${id}`,
  nb_members: 2,
  created_by: { id: 'u-1', full_name: 'Ada Lovelace' },
  abilities: {
    destroy: canManage,
    manage_managers: canManage,
    manage_members: canManage,
    partial_update: canManage,
    retrieve: true,
    update: canManage,
  },
  created_at: '',
});

describe('DocUserGroupsModal', () => {
  beforeEach(() => {
    fetchMock.hardReset();
    fetchMock.mockGlobal();
  });

  test('the owner of an independent page creates a user group', async () => {
    fetchMock.get(`${API}/documents/d-1/user-groups/`, []);
    fetchMock.post(
      `${API}/documents/d-1/user-groups/`,
      group('g-1', 'Reviewers', true),
    );

    render(<DocUserGroupsModal doc={page(Role.OWNER)} onClose={vi.fn()} />, {
      wrapper: AppWrapper,
    });

    expect(await screen.findByText('No user group yet.')).toBeInTheDocument();
    await userEvent.type(
      screen.getByLabelText('New user group name'),
      'Reviewers',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));

    await waitFor(() => {
      const created = fetchMock.callHistory
        .calls()
        .find((call) => call.options.method?.toUpperCase() === 'POST');
      expect(created?.options.body).toBe(JSON.stringify({ name: 'Reviewers' }));
    });
  });

  test('an editor sees the groups and their members, without managing them', async () => {
    fetchMock.get(`${API}/documents/d-1/user-groups/`, [
      group('g-1', 'Reviewers', false),
    ]);
    fetchMock.get(`${API}/groups/g-1/members/`, [
      {
        id: 'm-1',
        user: { id: 'u-2', email: 'bo@example.com', full_name: 'Bo Martin' },
        is_manager: false,
        created_at: '',
      },
    ]);

    render(<DocUserGroupsModal doc={page(Role.EDITOR)} onClose={vi.fn()} />, {
      wrapper: AppWrapper,
    });

    await userEvent.click(await screen.findByText('Reviewers'));
    expect(await screen.findByText('Bo Martin')).toBeInTheDocument();
    expect(
      screen.getByText(/2 members · created by Ada Lovelace/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText('New user group name')).toBeNull();
    expect(
      screen.queryByRole('button', { name: 'Delete Reviewers' }),
    ).toBeNull();
    expect(screen.queryByLabelText('Add someone to Reviewers')).toBeNull();
  });
});
