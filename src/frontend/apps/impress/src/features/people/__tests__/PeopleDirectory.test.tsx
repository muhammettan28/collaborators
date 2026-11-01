import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import fetchMock from 'fetch-mock';
import { beforeEach, describe, expect, test } from 'vitest';

import { AppWrapper } from '@/tests/utils';

import { DirectoryPerson, PeopleDirectory } from '../PeopleDirectory';

const API = 'http://test.jest/api/v1.0';

const ada: DirectoryPerson = {
  id: 'u-1',
  full_name: 'Ada Lovelace',
  email: 'ada@acme.org',
  headline: '',
  organization: '',
  is_colleague: true,
  workspaces: ['Acme', 'Beta'],
};

const olga: DirectoryPerson = {
  id: 'u-2',
  full_name: 'Olga Open',
  email: '',
  headline: 'Grant writer',
  organization: '',
  is_colleague: false,
  workspaces: [],
};

describe('My Collaborators', () => {
  beforeEach(() => {
    fetchMock.hardReset();
    fetchMock.mockGlobal();
  });

  test('lists the people one works with, with the workspaces shared', async () => {
    fetchMock.get(`${API}/people/directory/?q=`, [ada, olga]);
    render(<PeopleDirectory />, { wrapper: AppWrapper });

    const row = await screen.findByTestId('person-u-1');
    expect(row).toHaveTextContent('Ada Lovelace');
    expect(row).toHaveTextContent('In Acme, Beta');
    expect(row).toHaveAttribute('href', expect.stringContaining('u-1'));
    expect(screen.getByText('People I work with')).toBeInTheDocument();
    expect(screen.getByTestId('person-u-2')).toHaveTextContent('Grant writer');
    expect(screen.getByText('Open to everyone')).toBeInTheDocument();
    expect(screen.queryByTestId('people-directory-empty')).toBeNull();
  });

  test('says plainly when one shares nothing with anybody', async () => {
    fetchMock.get(`${API}/people/directory/?q=`, []);
    render(<PeopleDirectory />, { wrapper: AppWrapper });

    const empty = await screen.findByTestId('people-directory-empty');
    expect(empty).toHaveTextContent('Nobody here yet');
    expect(
      screen.getByRole('link', { name: 'Find a workspace to join' }),
    ).toHaveAttribute(
      'href',
      expect.stringMatching(/^\/workspaces\/discover\/?$/),
    );
  });

  test('without colleagues, says so above the people open to everyone', async () => {
    fetchMock.get(`${API}/people/directory/?q=`, [olga]);
    render(<PeopleDirectory />, { wrapper: AppWrapper });

    expect(
      await screen.findByTestId('people-directory-empty'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('person-u-2')).toBeInTheDocument();
    expect(screen.queryByText('People I work with')).toBeNull();
  });

  test('a search that finds nobody says so, without the empty panel', async () => {
    fetchMock.get(`${API}/people/directory/?q=`, [ada]);
    fetchMock.get(`${API}/people/directory/?q=zz`, []);
    render(<PeopleDirectory />, { wrapper: AppWrapper });
    await screen.findByTestId('person-u-1');

    await userEvent.type(screen.getByLabelText('Find someone'), 'zz');

    expect(await screen.findByText('Nobody found.')).toBeInTheDocument();
    expect(screen.queryByTestId('people-directory-empty')).toBeNull();
  });

  test('a list that fails to load says so, and can be asked again', async () => {
    fetchMock.get(`${API}/people/directory/?q=`, 500);
    render(<PeopleDirectory />, { wrapper: AppWrapper });

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The list could not be loaded.',
    );
    expect(screen.queryByTestId('people-directory-empty')).toBeNull();

    fetchMock.removeRoutes();
    fetchMock.get(`${API}/people/directory/?q=`, [ada]);
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }));

    expect(await screen.findByTestId('person-u-1')).toBeInTheDocument();
  });
});
