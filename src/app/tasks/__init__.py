from .ocr import process_ocr_task
from .generation_plan_cadre import generate_plan_cadre_content_task
from .generation_plan_de_cours import generate_plan_de_cours_all_task
from .import_grille import extract_grille_from_pdf_task
from .import_plan_de_cours import import_plan_de_cours_task
# Only preview mode is supported for Plan-cadre import
from .import_plan_cadre import import_plan_cadre_preview_task
from .generation_logigramme import generate_programme_logigramme_task
from .generation_grille import generate_programme_grille_task
from .docx_to_schema import docx_to_json_schema_task
from . import data_schema  # ensure submodule is importable as src.app.tasks.data_schema

# Improve import compatibility when 'app' aliasing is used
try:
    import sys as _sys
    _sys.modules.setdefault('app.tasks.data_schema', data_schema)
    _sys.modules.setdefault('src.app.tasks.data_schema', data_schema)
except Exception:
    pass
