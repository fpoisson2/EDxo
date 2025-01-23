import fitz
import json

def extract_pdf_content(pdf_path):
    # Charger le PDF
    document = fitz.open(pdf_path)
    extracted_data = []
    competence = {}

    for page_num in range(document.page_count):
        page = document.load_page(page_num)
        text = page.get_text("text")

        # Diviser le texte en lignes
        lines = text.split("\n")
        for line in lines:
            if line.startswith("Code :"):
                if competence:
                    extracted_data.append(competence)
                    competence = {}
                competence["Code"] = line.split(":")[1].strip()
            elif line.startswith("Énoncé de la compétence"):
                competence["Énoncé"] = line.split(":")[1].strip()
            elif line.startswith("Contexte de réalisation"):
                competence["Contexte"] = []
            elif line.startswith("Critères de performance"):
                competence["Critères"] = []
            elif line.startswith("•"):
                if "Contexte" in competence:
                    competence["Contexte"].append(line[1:].strip())
                elif "Critères" in competence:
                    competence["Critères"].append(line[1:].strip())

    if competence:
        extracted_data.append(competence)

    # Convertir en JSON
    return json.dumps(extracted_data, indent=4, ensure_ascii=False)

# Chemin vers le fichier PDF
pdf_path = "Technologie du génie électrique _ Électronique programmable (243.G0).pdf"
result = extract_pdf_content(pdf_path)

# Enregistrer le fichier JSON
with open("extracted_data.json", "w", encoding="utf-8") as json_file:
    json_file.write(result)

print("Extraction terminée. Les données sont enregistrées dans 'extracted_data.json'.")
