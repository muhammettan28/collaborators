import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import fetchMock from 'fetch-mock';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import { Role } from '@/features/docs/doc-management';
import { AppWrapper } from '@/tests/utils';

import { Space, Workspace, WorkspaceRole } from '../../types';
import { AlsoInSpaces, rolesAbove } from '../AlsoInSpaces';
import { WorkspaceSettings } from '../WorkspaceSettings';

const API = 'http://test.jest/api/v1.0';

vi.mock('next/router', async () => ({
  ...(await vi.importActual('next/router')),
  useRouter: () => ({ pathname: '/workspace/ws-1/settings', push: vi.fn() }),
}));

const space = (
  id: string,
  title: string,
  members_role: string | null,
  accesses_manage = true,
) =>
  ({
    id,
    title,
    members_role,
    linked_workspaces: [],
    abilities: { accesses_manage },
  }) as unknown as Space;

const workspace: Workspace = {
  id: 'ws-1',
  name: 'Acme',
  slug: 'acme',
  description: '',
  visibility: 'hidden',
  publishing_policy: 'space_admins',
  join_domains: [],
  join_group: null,
  join_organizations: [],
  join_organization_choices: [],
  join_approval: true,
  join_token: null,
  pending_join_requests: 0,
  user_role: WorkspaceRole.OWNER,
  abilities: {
    destroy: true,
    manage_accesses: true,
    create_groups: true,
    manage_groups: true,
    partial_update: true,
    retrieve: true,
    spaces_create: true,
    update: true,
  },
  created_at: '',
  updated_at: '',
};

describe('AlsoInSpaces', () => {
  test('offers only the roles above what members already get', () => {
    expect(rolesAbove(space('s', 'S', null))).toEqual([
      Role.READER,
      Role.EDITOR,
      Role.ADMIN,
    ]);
    expect(rolesAbove(space('s', 'S', 'reader'))).toEqual([
      Role.EDITOR,
      Role.ADMIN,
    ]);
    expect(rolesAbove(space('s', 'S', 'commenter'))).toEqual([
      Role.EDITOR,
      Role.ADMIN,
    ]);
    expect(rolesAbove(space('s', 'S', 'administrator'))).toEqual([]);
  });

  test('checking a space gives it the lowest role worth giving', async () => {
    const onChange = vi.fn();
    render(
      <AlsoInSpaces
        spaces={[
          space('s-1', 'Launches', 'reader'),
          space('s-2', 'Board', 'administrator'),
        ]}
        value={{}}
        onChange={onChange}
      />,
      { wrapper: AppWrapper },
    );

    expect(
      screen.getByText('Members already get it as reader'),
    ).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Board' })).toBeDisabled();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Launches' }));
    expect(onChange).toHaveBeenCalledWith({ 's-1': Role.EDITOR });
  });
});

describe('Workspace settings: adding a member to spaces too', () => {
  beforeEach(() => {
    fetchMock.hardReset();
    fetchMock.mockGlobal();
    fetchMock.get(`${API}/config/`, { API_USERS_SEARCH_QUERY_MIN_LENGTH: 3 });
    fetchMock.get(`${API}/users/me/`, {
      id: 'u-0',
      email: 'ada@example.com',
      full_name: 'Ada',
    });
    fetchMock.get(`begin:${API}/workspaces/?`, [workspace]);
    fetchMock.get(`${API}/workspaces/`, [workspace]);
    fetchMock.get(`${API}/spaces/?workspace=ws-1`, [
      space('s-1', 'Launches', null),
      space('s-2', 'Elsewhere', null, false),
    ]);
    fetchMock.get(`begin:${API}/users/`, []);
    fetchMock.post(`${API}/workspaces/ws-1/invitations/`, {
      id: 'i-1',
      email: 'new@example.com',
      role: 'member',
      created_at: '',
      is_expired: false,
    });
    fetchMock.post(`${API}/documents/s-1/invitations/`, { id: 'i-2' });
    // Everything else the page reads: nothing
    fetchMock.catch({ status: 200, body: [] });
  });

  test('an email invited to the workspace is invited to the spaces checked', async () => {
    render(<WorkspaceSettings workspaceId="ws-1" />, { wrapper: AppWrapper });

    const choices = await screen.findByTestId('also-in-spaces');
    // Only the spaces one may share
    expect(within(choices).queryByText('Elsewhere')).toBeNull();
    await userEvent.click(
      within(choices).getByRole('checkbox', { name: 'Launches' }),
    );

    await userEvent.type(
      screen.getByLabelText('Add a collaborator by name or email'),
      'new@example.com',
    );
    await userEvent.click(
      await screen.findByRole('option', {
        name: 'Invite new@example.com by email',
      }),
    );

    await waitFor(() =>
      expect(
        fetchMock.callHistory.called(`${API}/documents/s-1/invitations/`),
      ).toBe(true),
    );
    const [call] = fetchMock.callHistory.calls(
      `${API}/documents/s-1/invitations/`,
    );
    expect(JSON.parse(call.options.body as string)).toEqual({
      email: 'new@example.com',
      role: 'reader',
    });
    // The choices are cleared for the next one
    expect(
      within(screen.getByTestId('also-in-spaces')).getByRole('checkbox', {
        name: 'Launches',
      }),
    ).not.toBeChecked();
  });
});
