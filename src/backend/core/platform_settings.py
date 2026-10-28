"""
Collaborators: the settings platform owners change in the app. Each one not
set here follows the server's own (its environment):

- signup_approval: newcomers wait for a manager to let them in
  (COLLABORATORS_SIGNUP_APPROVAL, see core.registrations);
- email_invitations: workspaces, spaces and pages invite people by email
  (COLLABORATORS_EMAIL_INVITATIONS);
- presentation_storage_mb: what each person may store of presentations, in
  MB (COLLABORATORS_PRESENTATION_STORAGE_MB, see core.presentations);
- presentation_versions: how many versions of each are kept
  (COLLABORATORS_PRESENTATION_VERSIONS).

Every change goes to the platform log.
"""

from django.conf import settings

from core import models, platform_roles
from core.choices import PlatformLogActionChoices

# Each setting, and the server setting it overrides
SETTINGS = {
    "signup_approval": "COLLABORATORS_SIGNUP_APPROVAL",
    "email_invitations": "COLLABORATORS_EMAIL_INVITATIONS",
    "presentation_storage_mb": "COLLABORATORS_PRESENTATION_STORAGE_MB",
    "presentation_versions": "COLLABORATORS_PRESENTATION_VERSIONS",
}

# The settings that are numbers (the others are on or off), and their bounds
NUMBERS = {
    "presentation_storage_mb": (0, 100_000),
    "presentation_versions": (1, 100),
}


def _check(name, value):
    """Refuse a value of the wrong kind (null always goes)."""
    if value is None:
        return
    if name in NUMBERS:
        low, high = NUMBERS[name]
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name}: a whole number or null")
        if not low <= value <= high:
            raise ValueError(f"{name}: from {low} to {high}")
    elif not isinstance(value, bool):
        raise ValueError(f"{name}: true, false or null")


def _row():
    return models.PlatformSettings.objects.first()


def get(name):
    """A setting's value: the platform's own, else the server's."""
    row = _row()
    value = getattr(row, name) if row else None
    return getattr(settings, SETTINGS[name]) if value is None else value


def describe():
    """Each setting: its value, the server's, and whether it is set here."""
    row = _row()
    described = {}
    for name, server_name in SETTINGS.items():
        own = getattr(row, name) if row else None
        server = getattr(settings, server_name)
        described[name] = {
            "value": server if own is None else own,
            "server_default": server,
            "set_here": own is not None,
        }
    return described


def update(values, actor):
    """
    Change some settings (true or false, or a number; null follows the
    server again), and log what changed.
    """
    row = _row() or models.PlatformSettings()
    changes = {}
    for name, value in values.items():
        if name not in SETTINGS:
            raise ValueError(f"Unknown setting: {name}")
        _check(name, value)
        if getattr(row, name) != value:
            changes[name] = [getattr(row, name), value]
            setattr(row, name, value)
    if not changes:
        return {}
    row.updated_by = actor
    row.save()
    platform_roles.log(
        PlatformLogActionChoices.SETTINGS_CHANGED,
        None,
        actor,
        target_name="",
        changes=changes,
    )
    return changes
