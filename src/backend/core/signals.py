"""
Declare and configure the signals for the impress core application
"""

from functools import partial

from django.core.cache import cache
from django.db import transaction
from django.db.models import signals
from django.dispatch import receiver

from core import models
from core.tasks.access import reset_service_connections_on_commit
from core.tasks.search import trigger_batch_document_indexer
from core.utils.users import (
    forget_all_people,
    get_users_sharing_documents_with_cache_key,
)


def forget_people_around(document_id, user_id):
    """
    The people sharing a document changed: the "people I work with" of each
    of them (listed by "@" and the user search) are computed again.
    """
    user_ids = models.DocumentAccess.objects.filter(
        document_id=document_id, user__isnull=False
    ).values_list("user_id", flat=True)
    cache.delete_many(
        [
            get_users_sharing_documents_with_cache_key(other_id)
            for other_id in {user_id, *user_ids}
            if other_id
        ]
    )
    forget_all_people()


@receiver(signals.post_save, sender=models.Document)
def document_post_save(sender, instance, created, **kwargs):  # pylint: disable=unused-argument
    """
    Asynchronous call to the document indexer at the end of the transaction.
    Note : Within the transaction we can have an empty content and a serialization
    error.

    A change of the link definition changes who may open the document and its
    descendants, from wherever it was saved: the collaboration server is told
    to re-check their connections.
    """
    transaction.on_commit(
        partial(trigger_batch_document_indexer, instance.pk, instance.updated_at)
    )

    if not created and instance.link_definition_changed():
        reset_service_connections_on_commit(instance.pk)
    # Collaborators: a space's link (or its going to the trashbin) reaches the
    # pages linked into it
    if not created and instance.is_space:
        refresh_linked_pages(
            models.PageSpaceLink.objects.filter(space=instance).values_list(
                "page_id", flat=True
            )
        )
    # Collaborators: put in the trashbin (saved with its date) or taken out
    # of it (saved without): the others lose it, or get it back
    if not created and (
        instance.deleted_at is not None
        or "deleted_at" in (kwargs.get("update_fields") or ())
    ):
        forget_all_people()
    # once committed: taken now, a save rolled back with its savepoint would
    # leave the snapshot of a value the database never got, and saving that
    # value again would report no change
    transaction.on_commit(instance.remember_link_definition)


@receiver(signals.post_save, sender=models.DocumentAccess)
def document_access_post_save(sender, instance, created, **kwargs):  # pylint: disable=unused-argument
    """
    Asynchronous call to the document indexer at the end of the transaction.
    Clear cache for the affected user.

    Every change of an access, wherever it comes from (API, admin, an accepted
    access request...), is reported to the collaboration server so that the
    connections of the user, or of everybody for a team, are re-checked.
    """
    if not created:
        document = instance.document
        transaction.on_commit(
            partial(trigger_batch_document_indexer, document.pk, document.updated_at)
        )

    # Invalidate the cache of the user, and of the others on the document
    forget_people_around(instance.document_id, instance.user_id)

    reset_service_connections_on_commit(instance.document_id, instance.user_id)


@receiver(signals.post_delete, sender=models.DocumentAccess)
def document_access_post_delete(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """
    Clear cache for the affected user when document access is deleted, and
    have the collaboration server re-check their connections: they may have
    lost their access, or an inherited one.
    """
    forget_people_around(instance.document_id, instance.user_id)

    reset_service_connections_on_commit(instance.document_id, instance.user_id)


@receiver(signals.post_save, sender=models.WorkspaceAccess)
@receiver(signals.post_delete, sender=models.WorkspaceAccess)
@receiver(signals.post_save, sender=models.GroupMembership)
@receiver(signals.post_delete, sender=models.GroupMembership)
def membership_changed(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """
    A workspace or group membership changed: recompute the teams of its user,
    which decide the roles they get through team accesses on documents.
    """
    models.User.refresh_teams(instance.user_id)

    # Workspace members are found by name in each other's user searches
    if isinstance(instance, models.WorkspaceAccess):
        member_ids = models.WorkspaceAccess.objects.filter(
            workspace_id=instance.workspace_id
        ).values_list("user_id", flat=True)
        cache.delete_many(
            [
                get_users_sharing_documents_with_cache_key(member_id)
                for member_id in [instance.user_id, *member_ids]
            ]
        )
    forget_all_people()


def refresh_linked_pages(page_ids):
    """
    Collaborators: pages linked into spaces take their widest link, and the
    collaboration server re-checks who may read those whose link changed.
    """
    for page_id in models.refresh_linked_reach(page_ids):
        reset_service_connections_on_commit(page_id)


@receiver(signals.post_save, sender=models.PageSpaceLink)
@receiver(signals.post_delete, sender=models.PageSpaceLink)
def page_space_link_changed(sender, instance, **kwargs):  # pylint: disable=unused-argument
    """
    Collaborators: a page linked into a space, or no longer, takes its link,
    and the people of that space share the page with its own people, or no
    longer.
    """
    refresh_linked_pages([instance.page_id])
    forget_all_people()
