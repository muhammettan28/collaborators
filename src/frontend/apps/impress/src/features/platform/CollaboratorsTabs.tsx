import { Button } from '@gouvfr-lasuite/ui-components';
import { useSearchParams } from 'next/navigation';
import { ReactNode, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Box } from '@/components';
import { PlatformRole, hasPlatformLevel, useAuth } from '@/features/auth';
import { PeopleDirectory } from '@/features/people/PeopleDirectory';

import { AddToPlaces } from './AddToPlaces';
import { BlockedEmails } from './BlockedEmails';
import { ManageCollaborators } from './ManageCollaborators';
import { PlatformSettings } from './PlatformSettings';
import { Reports } from './Reports';

type Tab = 'mine' | 'manage' | 'reports' | 'places' | 'blocked' | 'settings';

interface TabItem {
  id: Tab;
  /** The lowest level that sees it */
  level: PlatformRole;
  label: string;
  screen: ReactNode;
}

/**
 * Collaborators: the screen of "My CO✍️✍️ABORATORS" (its heading spells the
 * logo; the tabs are plain words). Platform managers and the levels above
 * them also find "Manage" there: everyone on the platform
 * (administrators and owners suspend and remove accounts there);
 * administrators and owners find "Reports"; owners "Add to places" (people
 * put straight into workspaces, spaces and pages), "Blocked accounts" and
 * "Settings". `?tab=` opens one (a report's notification opens Reports).
 */
export const CollaboratorsTabs = () => {
  const { t } = useTranslation();
  const { user } = useAuth();
  const searchParams = useSearchParams();
  const all: TabItem[] = [
    {
      id: 'mine',
      level: 'collaborator',
      label: t('My Collaborators', {
        description: 'Tab of the people one works with',
      }),
      screen: <PeopleDirectory />,
    },
    {
      id: 'manage',
      level: 'manager',
      label: t('Manage', {
        description:
          'Tab listing everyone on the platform, for platform managers',
      }),
      screen: <ManageCollaborators />,
    },
    {
      id: 'reports',
      level: 'administrator',
      label: t('Reports', {
        description: 'Tab of the reported pages, for platform administrators',
      }),
      screen: <Reports />,
    },
    {
      id: 'places',
      level: 'owner',
      label: t('Add to places', {
        description:
          'Tab adding people to workspaces, spaces and pages, for platform owners',
      }),
      screen: <AddToPlaces />,
    },
    {
      id: 'blocked',
      level: 'owner',
      label: t('Blocked accounts', {
        description: 'Tab of the blocked emails, for platform owners',
      }),
      screen: <BlockedEmails />,
    },
    {
      id: 'settings',
      level: 'owner',
      label: t('Settings', {
        description: 'Tab of the platform settings, for platform owners',
      }),
      screen: <PlatformSettings />,
    },
  ];
  const tabs = all.filter((item) => hasPlatformLevel(user, item.level));
  const asked = searchParams?.get('tab');
  const [tab, setTab] = useState<Tab>(
    tabs.find((item) => item.id === asked)?.id ?? 'mine',
  );

  if (tabs.length === 1) {
    return <PeopleDirectory />;
  }

  return (
    <Box $gap="md">
      <Box $direction="row" $gap="xs" $wrap="wrap" role="tablist">
        {tabs.map((item) => (
          <Button
            key={item.id}
            size="small"
            role="tab"
            aria-selected={tab === item.id}
            variant={tab === item.id ? 'primary' : 'tertiary'}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </Button>
        ))}
      </Box>
      {tabs.find((item) => item.id === tab)?.screen}
    </Box>
  );
};
