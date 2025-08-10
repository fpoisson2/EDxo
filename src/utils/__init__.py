"""Convenience imports for utility helpers."""

from .email_helpers import send_reset_email
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
