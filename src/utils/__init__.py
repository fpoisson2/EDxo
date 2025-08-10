"""Lightweight export layer for utility helpers.

This package exposes a curated set of helpers via lazy attribute access.  The
actual helper modules often depend on the Flask application or database models;
importing them eagerly would therefore trigger side effects and, in some
cases, circular imports during application start-up.  By deferring those
imports until the attributes are first used we keep imports inexpensive and
avoid initialization issues.
"""

from importlib import import_module
from typing import Any, Dict


# Mapping of attribute name -> module path.  Attributes are loaded on demand
# via ``__getattr__``.
_LAZY_IMPORTS: Dict[str, str] = {
    # Email helpers
    "send_reset_email": "utils.email_helpers",
    # Google API helper
    "build_gmail_service": "utils.google_api",
    # Backup utilities
    "get_scheduler_instance": "utils.backup_utils",
    "send_backup_email_with_context": "utils.backup_utils",
    "send_backup_email": "utils.backup_utils",
    # Generic utilities
    "save_grille_to_database": "utils.utils",
    "normalize_text": "utils.utils",
    "extract_code_from_title": "utils.utils",
    "determine_base_filename": "utils.utils",
    "is_teacher_in_programme": "utils.utils",
    "get_programme_id_for_cours": "utils.utils",
    "get_programme_ids_for_cours": "utils.utils",
    "is_coordo_for_programme": "utils.utils",
    "get_initials": "utils.utils",
    "get_all_cegeps": "utils.utils",
    "get_cegep_details_data": "utils.utils",
    "get_plan_cadre_data": "utils.utils",
    "replace_tags_jinja2": "utils.utils",
    "generate_docx_with_template": "utils.utils",
}


__all__ = list(_LAZY_IMPORTS.keys())


def __getattr__(name: str) -> Any:
    """Dynamically import utility attributes on first access.

    This mechanism avoids importing heavy modules unless they are actually
    needed, which in turn prevents circular dependencies during application
    initialization.
    """

    if name in _LAZY_IMPORTS:
        module = import_module(_LAZY_IMPORTS[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Provide module attributes for ``dir()`` calls."""

    return sorted(__all__)

