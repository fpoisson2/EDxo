"""Convenience imports for utility helpers.

This module exposes a subset of utility functions while avoiding expensive or
application-specific imports at module import time.  In particular, importing
``send_reset_email`` directly would pull in the Flask application models and
cause circular import issues during application start up.  To sidestep this we
provide a lightweight proxy that performs the actual import only when the
function is invoked."""

from .google_api import build_gmail_service
from .backup_utils import (
    get_scheduler_instance,
    send_backup_email_with_context,
    send_backup_email,
)
from .utils import (
    save_grille_to_database,
    normalize_text,
    extract_code_from_title,
    determine_base_filename,
    is_teacher_in_programme,
    get_programme_id_for_cours,
    get_programme_ids_for_cours,
    is_coordo_for_programme,
    get_initials,
    get_all_cegeps,
    get_cegep_details_data,
    get_plan_cadre_data,
    replace_tags_jinja2,
    generate_docx_with_template,
)


def send_reset_email(*args, **kwargs) -> None:
    """Lazy proxy to :func:`utils.email_helpers.send_reset_email`.

    Importing ``email_helpers`` at module load time introduces a circular
    dependency because that module relies on ``app.models`` which, in turn,
    imports from :mod:`utils`.  Deferring the import until the function is
    called breaks this cycle while keeping a convenient top-level export.
    """

    from .email_helpers import send_reset_email as _send_reset_email

    _send_reset_email(*args, **kwargs)

__all__ = [
    "send_reset_email",
    "build_gmail_service",
    "get_scheduler_instance",
    "send_backup_email_with_context",
    "send_backup_email",
    "save_grille_to_database",
    "normalize_text",
    "extract_code_from_title",
    "determine_base_filename",
    "is_teacher_in_programme",
    "get_programme_id_for_cours",
    "get_programme_ids_for_cours",
    "is_coordo_for_programme",
    "get_initials",
    "get_all_cegeps",
    "get_cegep_details_data",
    "get_plan_cadre_data",
    "replace_tags_jinja2",
    "generate_docx_with_template",
]
