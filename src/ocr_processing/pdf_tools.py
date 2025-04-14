# -*- coding: utf-8 -*-
import logging
from PyPDF2 import PdfReader, PdfWriter
import os

def extract_pdf_section(input_pdf_path, output_pdf_path, page_debut, page_fin):
    """Extrait une section de pages d'un PDF."""
    logging.info(f"Tentative d'extraction des pages {page_debut}-{page_fin} de {input_pdf_path} vers {output_pdf_path}")
    try:
        reader = PdfReader(input_pdf_path)
        writer = PdfWriter()
        num_pages = len(reader.pages)

        # Ajustement pour être inclusif et gérer les limites
        start_page_idx = max(0, page_debut - 1)
        end_page_idx = min(num_pages, page_fin) # page_fin est exclusive dans range, donc c'est bon

        if start_page_idx >= end_page_idx or start_page_idx >= num_pages:
             logging.error(f"Plage de pages invalide ({page_debut}-{page_fin}) pour le PDF de {num_pages} pages.")
             print(f"Plage de pages invalide ({page_debut}-{page_fin}) pour le PDF de {num_pages} pages.")
             return False

        logging.info(f"Extraction des pages indices {start_page_idx} à {end_page_idx - 1} (numéros {start_page_idx + 1} à {end_page_idx}).")
        for i in range(start_page_idx, end_page_idx):
            writer.add_page(reader.pages[i])

        if len(writer.pages) > 0:
            with open(output_pdf_path, "wb") as f:
                writer.write(f)
            logging.info(f"Section PDF extraite avec succès dans {output_pdf_path}")
            print(f"Section PDF extraite avec succès dans {output_pdf_path}")
            return True
        else:
             logging.warning(f"Aucune page n'a été extraite pour la plage {page_debut}-{page_fin}.")
             print("Aucune page n'a été extraite.")
             return False

    except Exception as e:
        logging.error(f"Erreur lors de l'extraction de la section du PDF '{input_pdf_path}': {e}", exc_info=True)
        print(f"Erreur lors de l'extraction de la section du PDF: {e}")
        return False

def convert_pdf_to_txt(pdf_path, txt_output_path):
    """Extrait le texte brut d'un PDF et le sauvegarde."""
    logging.info(f"Tentative de conversion de {pdf_path} en texte vers {txt_output_path}")
    full_text = ""
    try:
        reader = PdfReader(pdf_path)
        num_pages = len(reader.pages)
        logging.info(f"Lecture de {num_pages} pages dans {pdf_path}")
        for i, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text()
                if page_text:
                    # Ajouter un séparateur clair entre les pages
                    full_text += f"\n--- PAGE {i + 1} ---\n"
                    full_text += page_text.strip() + "\n"
                else:
                    logging.warning(f"Aucun texte extrait de la page {i + 1} de {pdf_path}")
                    full_text += f"\n--- PAGE {i + 1} [Extraction de texte vide] ---\n"
            except Exception as page_error:
                 logging.error(f"Erreur lors de l'extraction du texte de la page {i + 1} de {pdf_path}: {page_error}", exc_info=True)
                 full_text += f"\n--- PAGE {i + 1} [Erreur d'extraction] ---\n"


        with open(txt_output_path, "w", encoding="utf-8") as f:
            f.write(full_text)
        logging.info(f"PDF converti en texte avec succès : {txt_output_path}")
        print(f"PDF converti en texte : {txt_output_path}")
        return full_text

    except Exception as e:
        logging.error(f"Erreur lors de la conversion du PDF '{pdf_path}' en texte: {e}", exc_info=True)
        print(f"Erreur lors de la conversion du PDF en texte: {e}")
        return "" # Retourner une chaîne vide en cas d'erreur majeure