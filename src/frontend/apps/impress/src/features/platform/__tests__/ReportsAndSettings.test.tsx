import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import fetchMock from 'fetch-mock';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import { User } from '@/features/auth/api';
import { AppWrapper } from '@/tests/utils';

import { CollaboratorsTabs } from '../CollaboratorsTabs';
import { PlatformSettings } from '../PlatformSettings';
import { ReportPageModal } from '../ReportPageModal';
import { Reports } from '../Reports';

const API = 'http://test.jest/api/v1.0';

const me: { current: Partial<User> } = { current: {} };

vi.mock('@/features/auth/hooks/useAuth', () => ({
  useAuth: () => ({ user: me.current, authenticated: true }),
}));

const lastBody = (url: string, method = 'POST') =>
  JSON.parse(
    (fetchMock.callHistory
      .calls()
      .filter(
        (call) =>
          call.url === url && call.options.method?.toUpperCase() === method,
      )
      .pop()?.options.body as string) || '{}',
  ) as Record<string, unknown>;

const report = {
  id: 'r-1',
  document: {
    id: 'd-1',
    title: 'Offers',
    deleted: false,
    taken_down: false,
    owners: ['Otto <otto@example.org>'],
  },
  document_title: 'Offers',
  excerpt: 'Buy cheap pills',
  reporter: 'Rita <rita@example.org>',
  reason: 'spam',
  details: 'Ads everywhere',
  status: 'open',
  resolved_by: '',
  resolved_at: null,
  resolution_note: '',
  created_at: '2026-10-26T10:00:00Z',
};

describe('Reports and platform settings', () => {
  beforeEach(() => {
    fetchMock.hardReset();
    fetchMock.mockGlobal();
    fetchMock.get(`begin:${API}/people/directory/`, []);
  });

  test('a reader reports a page with a reason', async () => {
    fetchMock.post(`${API}/documents/d-1/report/`, 201);
    render(<ReportPageModal docId="d-1" onClose={() => {}} />, {
      wrapper: AppWrapper,
    });

    const send = screen.getByRole('button', { name: 'Report' });
    expect(send).toBeDisabled();
    fireEvent.click(screen.getByRole('radio', { name: 'Abuse or harassment' }));
    fireEvent.change(screen.getByLabelText(/What is wrong/), {
      target: { value: 'Insults' },
    });
    fireEvent.click(send);

    await waitFor(() =>
      expect(lastBody(`${API}/documents/d-1/report/`)).toEqual({
        reason: 'abuse',
        details: 'Insults',
      }),
    );
  });

  test('administrators see what was reported, and dismiss it', async () => {
    fetchMock.get(`${API}/platform/reports/?status=open`, [report]);
    fetchMock.post(`${API}/platform/reports/r-1/dismiss/`, {
      ...report,
      status: 'dismissed',
    });
    render(<Reports />, { wrapper: AppWrapper });

    const card = await screen.findByTestId('report-r-1');
    expect(card).toHaveTextContent('Offers');
    expect(card).toHaveTextContent('Spam or advertising');
    expect(card).toHaveTextContent('Reported by Rita <rita@example.org>');
    expect(card).toHaveTextContent('owned by Otto <otto@example.org>');
    expect(card).toHaveTextContent('“Ads everywhere”');
    expect(card).toHaveTextContent('Buy cheap pills');
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }));

    await waitFor(() =>
      expect(
        fetchMock.callHistory.called(`${API}/platform/reports/r-1/dismiss/`),
      ).toBe(true),
    );
  });

  test('taking a page down asks first, with a reason for its owners', async () => {
    fetchMock.get(`${API}/platform/reports/?status=open`, [report]);
    fetchMock.post(`${API}/platform/reports/r-1/take-down/`, {
      ...report,
      status: 'taken_down',
    });
    render(<Reports />, { wrapper: AppWrapper });

    fireEvent.click(
      await screen.findByRole('button', { name: 'Take the page down' }),
    );
    fireEvent.change(await screen.findByLabelText(/Reason/), {
      target: { value: 'Spam' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Take it down' }));

    await waitFor(() =>
      expect(lastBody(`${API}/platform/reports/r-1/take-down/`)).toEqual({
        note: 'Spam',
      }),
    );
  });

  test('a page taken down can be put back', async () => {
    fetchMock.get(`${API}/platform/reports/?status=open`, []);
    fetchMock.get(`${API}/platform/reports/?status=decided`, [
      {
        ...report,
        status: 'taken_down',
        resolved_by: 'Ada <ada@example.org>',
        resolved_at: '2026-10-26T11:00:00Z',
        document: { ...report.document, deleted: true, taken_down: true },
      },
    ]);
    render(<Reports />, { wrapper: AppWrapper });
    await screen.findByText('No report to decide on.');

    fireEvent.click(screen.getByRole('button', { name: 'Decided' }));

    expect(
      await screen.findByText(/Taken down by Ada <ada@example.org>/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Put the page back' }),
    ).toBeInTheDocument();
  });

  test('owners change a setting, or let it follow the server', async () => {
    fetchMock.get(`${API}/platform/settings/`, {
      signup_approval: { value: true, server_default: true, set_here: false },
      email_invitations: { value: false, server_default: true, set_here: true },
    });
    fetchMock.patch(`${API}/platform/settings/`, {
      signup_approval: { value: false, server_default: true, set_here: true },
      email_invitations: { value: false, server_default: true, set_here: true },
    });
    render(<PlatformSettings />, { wrapper: AppWrapper });

    fireEvent.click(
      await screen.findByRole('checkbox', {
        name: 'New registrations wait for approval',
      }),
    );
    await waitFor(() =>
      expect(lastBody(`${API}/platform/settings/`, 'PATCH')).toEqual({
        signup_approval: false,
      }),
    );

    // Both are set here by now: the second is that of invitations
    await waitFor(() =>
      expect(
        screen.getAllByRole('button', { name: 'Follow the server’s own' }),
      ).toHaveLength(2),
    );
    fireEvent.click(
      screen.getAllByRole('button', { name: 'Follow the server’s own' })[1],
    );
    await waitFor(() =>
      expect(lastBody(`${API}/platform/settings/`, 'PATCH')).toEqual({
        email_invitations: null,
      }),
    );
  });

  test('owners set the storage for presentations, a number', async () => {
    const off = { value: true, server_default: true, set_here: false };
    fetchMock.get(`${API}/platform/settings/`, {
      signup_approval: off,
      email_invitations: off,
      presentation_storage_mb: {
        value: 25,
        server_default: 25,
        set_here: false,
      },
      presentation_versions: { value: 5, server_default: 5, set_here: false },
    });
    fetchMock.patch(`${API}/platform/settings/`, {
      signup_approval: off,
      email_invitations: off,
      presentation_storage_mb: {
        value: 50,
        server_default: 25,
        set_here: true,
      },
      presentation_versions: { value: 5, server_default: 5, set_here: false },
    });
    render(<PlatformSettings />, { wrapper: AppWrapper });

    const storage = await screen.findByLabelText(
      'Storage for presentations, per person (MB)',
    );
    const save = () => screen.getAllByRole('button', { name: 'Save' })[0];
    expect(save()).toBeDisabled();
    fireEvent.change(storage, { target: { value: '-3' } });
    expect(save()).toBeDisabled();
    fireEvent.change(storage, { target: { value: '50' } });
    fireEvent.click(save());
    await waitFor(() =>
      expect(lastBody(`${API}/platform/settings/`, 'PATCH')).toEqual({
        presentation_storage_mb: 50,
      }),
    );
    expect(
      await screen.findByRole('button', { name: 'Follow the server’s own' }),
    ).toBeInTheDocument();
  });

  test('each level finds its tabs', () => {
    me.current = { platform_role: 'administrator' };
    const { unmount } = render(<CollaboratorsTabs />, { wrapper: AppWrapper });
    expect(screen.getByRole('tab', { name: 'Reports' })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Settings' })).toBeNull();
    unmount();

    me.current = { platform_role: 'owner' };
    render(<CollaboratorsTabs />, { wrapper: AppWrapper });
    expect(screen.getByRole('tab', { name: 'Settings' })).toBeInTheDocument();
    expect(
      screen.getByRole('tab', { name: 'Blocked accounts' }),
    ).toBeInTheDocument();
  });
});
