import { VariantType, useToastProvider } from '@gouvfr-lasuite/ui-components';
import { useRouter } from 'next/router';
import { useTranslation } from 'react-i18next';

import { Doc } from '@/features/docs/doc-management';

import { useMakeSpaceIndependent, usePageMoves } from '../api';
import { useWorkspaceStore } from '../stores/useWorkspaceStore';

import { ConfirmModal } from './ConfirmModal';

/**
 * Take a page out of its space (or a space out of its workspaces): it
 * becomes independent, owned by whoever does it, and is found under
 * "My spaces & pages".
 */
export const MakeIndependentModal = ({
  doc,
  onClose,
}: {
  doc: Doc;
  onClose: () => void;
}) => {
  const { t } = useTranslation();
  const router = useRouter();
  const { toast } = useToastProvider();
  const { setCurrentWorkspaceId } = useWorkspaceStore();
  const isSpace = doc.kind === 'space';
  const { makeIndependent: makePage } = usePageMoves(doc.id);
  const makeSpace = useMakeSpaceIndependent(doc.id);

  const onSuccess = () => {
    setCurrentWorkspaceId(null);
    void router.replace(`/page/${doc.id}/`);
  };
  const onError = () =>
    toast(
      t('Something went wrong.', { description: 'Generic error message' }),
      VariantType.ERROR,
    );

  return (
    <ConfirmModal
      title={t('Make independent', {
        description: 'Action taking a page or space out of where it belongs',
      })}
      message={
        isSpace
          ? t(
              'This space leaves its workspaces: their members, admins and user groups lose the access they had through them. You become its owner, and can share it again or move it into a workspace later.',
              { description: 'Confirmation of making a space independent' },
            )
          : t(
              'This page and its subpages leave their space: the space members lose access to them. You become the owner, and can share it again, show it in spaces or move it into one later.',
              { description: 'Confirmation of making a page independent' },
            )
      }
      confirmLabel={t('Make independent', {
        description: 'Action taking a page or space out of where it belongs',
      })}
      onConfirm={() =>
        isSpace
          ? makeSpace.mutate(undefined, { onSuccess, onError })
          : makePage.mutate(undefined, { onSuccess, onError })
      }
      onClose={onClose}
    />
  );
};
