import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import fetchMock from 'fetch-mock';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import InvitePage from '@/pages/invite';
import { AppWrapper } from '@/tests/utils';

import { InvitationBundleInfo } from '../api';

const API = 'http://test.jest/api/v1.0';

vi.mock('next/router', async () => ({
  ...(await vi.importActual('next/router')),
  useRouter: () => ({
    pathname: '/invite',
    query: { token: 'tok' },
    replace: vi.fn(),
    push: vi.fn(),
  }),
}));

const waiting: InvitationBundleInfo = {
  is_bundle: true,
  issuer: 'Ada',
  email: 'me@example.com',
  invitations: [
    {
      token: 'tok-w',
      is_accepted: false,
      kind: 'workspace',
      name: 'Acme',
      description: 'Rockets',
      role: 'member',
      has_logo: true,
      is_expired: false,
    },
    {
      token: 'tok-s',
      is_accepted: false,
      kind: 'space',
      name: 'Launches',
      description: '',
      role: 'editor',
      has_logo: false,
      is_expired: false,
    },
  ],
};

const joined: InvitationBundleInfo = {
  ...waiting,
  invitations: waiting.invitations.map(({ token: _token, ...invitation }) => ({
    ...invitation,
    id: `id-${invitation.kind}`,
    is_accepted: true,
    role: '',
    has_logo: false,
  })),
};

describe('Invite page of invitations sent together', () => {
  let answer: InvitationBundleInfo;

  beforeEach(() => {
    answer = waiting;
    fetchMock.hardReset();
    fetchMock.mockGlobal();
    fetchMock.get(`${API}/config/`, {
      COLLABORATORS_SIGNIN_PROVIDERS: ['google'],
    });
    fetchMock.get(`${API}/invitations/tok/`, () => answer);
  });

  test('signed out: each invitation with its logo and role, then the providers', async () => {
    fetchMock.get(`${API}/users/me/`, 401);

    render(<InvitePage />, { wrapper: AppWrapper });

    expect(
      await screen.findByRole('heading', { name: 'Ada invited you to join' }),
    ).toBeInTheDocument();
    const rows = screen.getAllByTestId('bundled-invitation');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Acme');
    expect(rows[0]).toHaveTextContent('Workspace · as member');
    expect(rows[0].querySelector('img')).toHaveAttribute(
      'src',
      `${API}/invitations/tok-w/logo/`,
    );
    expect(rows[1]).toHaveTextContent('Space · as editor');
    expect(rows[1].querySelector('img')).toBeNull();
    expect(screen.getByTestId('invite-google')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Accept' })).toBeNull();
  });

  test('signed in: accepting all of them, then each opens', async () => {
    fetchMock.get(`${API}/users/me/`, {
      id: 'u-1',
      email: 'me@example.com',
      full_name: 'Me',
      registration_status: 'approved',
    });
    fetchMock.post(`${API}/invitations/tok/accept/`, () => {
      answer = joined;
      return { kind: 'bundle', accepted: 2 };
    });

    render(<InvitePage />, { wrapper: AppWrapper });

    fireEvent.click(
      await screen.findByRole('button', { name: 'Accept all and join' }),
    );

    await waitFor(() =>
      expect(screen.getAllByRole('button', { name: 'Open' })).toHaveLength(2),
    );
    expect(fetchMock.callHistory.called(`${API}/invitations/tok/accept/`)).toBe(
      true,
    );
    expect(screen.queryByTestId('invitation-other-email')).toBeNull();
  });

  test('signed in: one of them accepted alone, with its own token', async () => {
    fetchMock.get(`${API}/users/me/`, {
      id: 'u-2',
      email: 'other@example.com',
      full_name: 'Other',
      registration_status: 'approved',
    });
    fetchMock.post(`${API}/invitations/tok-s/accept/`, {
      kind: 'space',
      id: 'id-space',
    });

    render(<InvitePage />, { wrapper: AppWrapper });

    const accepts = await screen.findAllByRole('button', { name: 'Accept' });
    expect(accepts).toHaveLength(2);
    fireEvent.click(accepts[1]);

    await waitFor(() =>
      expect(
        fetchMock.callHistory.called(`${API}/invitations/tok-s/accept/`),
      ).toBe(true),
    );
    // Signed in as someone else than the one invited: told so
    expect(screen.getByTestId('invitation-other-email')).toHaveTextContent(
      'These invitations were sent to me@example.com.',
    );
  });
});
