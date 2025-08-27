import pytest
from types import SimpleNamespace
import app.tasks.ocr as ocr_tasks


def run_task(competence, download_path_local, txt_output_dir, base_filename_local, openai_key, model="gpt-test"):
    original_request = ocr_tasks.extract_json_competence.request
    object.__setattr__(
        ocr_tasks.extract_json_competence, "request", SimpleNamespace(id="test-task")
    )
    try:
        return ocr_tasks.extract_json_competence.run(
            competence,
            download_path_local,
            txt_output_dir,
            base_filename_local,
            openai_key,
            model,
        )
    finally:
        object.__setattr__(ocr_tasks.extract_json_competence, "request", original_request)


def test_pdf_inexistant_declenche_exception(app, tmp_path, monkeypatch):
    pdf_dir = tmp_path / "pdf"
    txt_dir = tmp_path / "txt"
    pdf_dir.mkdir()
    txt_dir.mkdir()

    with app.app_context():
        app.config["PDF_OUTPUT_DIR"] = str(pdf_dir)
        app.config["TXT_OUTPUT_DIR"] = str(txt_dir)

        def fake_extract_pdf_section(src, dest, start, end):
            raise FileNotFoundError("missing pdf")

        monkeypatch.setattr(ocr_tasks.pdf_tools, "extract_pdf_section", fake_extract_pdf_section)
        monkeypatch.setattr(ocr_tasks.pdf_tools, "convert_pdf_to_txt", lambda *args, **kwargs: "")
        monkeypatch.setattr(ocr_tasks.api_clients, "extraire_competences_depuis_pdf", lambda *args, **kwargs: {})

        competence = {"code": "C1", "page_debut": 1, "page_fin": 2}
        with pytest.raises(FileNotFoundError):
            run_task(competence, "missing.pdf", str(txt_dir), "base", "key")


def test_retour_vide_si_conversion_vide(app, tmp_path, monkeypatch):
    pdf_dir = tmp_path / "pdf"
    txt_dir = tmp_path / "txt"
    pdf_dir.mkdir()
    txt_dir.mkdir()

    with app.app_context():
        app.config["PDF_OUTPUT_DIR"] = str(pdf_dir)
        app.config["TXT_OUTPUT_DIR"] = str(txt_dir)

        monkeypatch.setattr(ocr_tasks.pdf_tools, "extract_pdf_section", lambda *args, **kwargs: True)
        monkeypatch.setattr(ocr_tasks.pdf_tools, "convert_pdf_to_txt", lambda *args, **kwargs: "   ")
        monkeypatch.setattr(ocr_tasks.api_clients, "extraire_competences_depuis_pdf", lambda *args, **kwargs: {})

        competence = {"code": "C1", "page_debut": 1, "page_fin": 2}
        result = run_task(competence, "dummy.pdf", str(txt_dir), "base", "key")
        assert result == {
            "competences": [],
            "code": "C1",
            "api_usage": {"prompt_tokens": 0, "completion_tokens": 0, "model": "gpt-test"},
        }


def test_succes_retourne_usages_api(app, tmp_path, monkeypatch):
    pdf_dir = tmp_path / "pdf"
    txt_dir = tmp_path / "txt"
    pdf_dir.mkdir()
    txt_dir.mkdir()

    with app.app_context():
        app.config["PDF_OUTPUT_DIR"] = str(pdf_dir)
        app.config["TXT_OUTPUT_DIR"] = str(txt_dir)

        monkeypatch.setattr(ocr_tasks.pdf_tools, "extract_pdf_section", lambda *args, **kwargs: True)
        monkeypatch.setattr(ocr_tasks.pdf_tools, "convert_pdf_to_txt", lambda *args, **kwargs: "texte")

        usage = SimpleNamespace(input_tokens=7, output_tokens=3)
        mock_response = {"result": '{"competences": [{"Code": "C1"}]}', "usage": usage}
        monkeypatch.setattr(
            ocr_tasks.api_clients,
            "extraire_competences_depuis_pdf",
            lambda *args, **kwargs: mock_response,
        )

        competence = {"code": "C1", "page_debut": 1, "page_fin": 2}
        result = run_task(competence, "dummy.pdf", str(txt_dir), "base", "key")
        assert result["api_usage"] == {
            "prompt_tokens": 7,
            "completion_tokens": 3,
            "model": "gpt-test",
        }
        assert result["competences"] == [{"Code": "C1"}]
        assert result["code"] == "C1"
