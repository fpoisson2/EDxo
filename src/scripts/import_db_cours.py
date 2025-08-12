import json
import re

from ..app.models import Cours, CoursPrealable, CoursCorequis  # Importez vos modèles
from ..app.models import db  # Importez votre objet db

from ..app import app

# La chaîne JSON fournie (vous pouvez aussi le charger depuis un fichier)
json_data = r'''
{
  "courses": [
    {
      "code": "243-115-LI",
      "titre": "Introduction à la profession",
      "préalable": "",
      "corequis": "",
      "unités": "2,00",
      "theorie": "2 h",
      "labo": "2 h",
      "étude": "2 h",
      "compétence": "02H8 Explorer la profession; 02HG Réaliser des travaux d’atelier; 02HP Produire des documents techniques"
    },
    {
      "code": "243-136-LI",
      "titre": "Développement de produits 1 : introduction",
      "préalable": "",
      "corequis": "",
      "unités": "2,66",
      "theorie": "2 h",
      "labo": "4 h",
      "étude": "2 h",
      "compétence": "02HD Produire des schémas électroniques"
    },
    {
      "code": "243-156-LI",
      "titre": "Programmation 1 : introduction",
      "préalable": "",
      "corequis": "",
      "unités": "2,66",
      "theorie": "2 h",
      "labo": "4 h",
      "étude": "2 h",
      "compétence": "02HJ Programmer des éléments programmables"
    },
    {
      "code": "243-176-LI",
      "titre": "Électronique 1: composants et circuits de base",
      "préalable": "",
      "corequis": "",
      "unités": "2,66",
      "theorie": "2 h",
      "labo": "4 h",
      "étude": "2 h",
      "compétence": "02HA Résoudre des problèmes en électronique; 02HB Analyser des informations techniques; 02HF Réaliser des prises de mesures"
    },
    {
      "code": "243-214-LI",
      "titre": "Réalisation de projets électroniques programmables",
      "préalable": "",
      "corequis": "",
      "unités": "2,33",
      "theorie": "2 h",
      "labo": "2 h",
      "étude": "3 h",
      "compétence": "02HG Réaliser des travaux d’atelier"
    },
    {
      "code": "243-236-LI",
      "titre": "Développement de produits 2: dessin et prototypes",
      "préalable": "50 % 243-136-LI",
      "corequis": "",
      "unités": "2,66",
      "theorie": "2 h",
      "labo": "4 h",
      "étude": "2 h",
      "compétence": "02HD Produire des schémas électroniques; 02HH Assurer la fabrication de circuits imprimés"
    },
    {
      "code": "243-256-LI",
      "titre": "Programmation 2: outils et microcontrôleurs",
      "préalable": "50 % 243-156-LI",
      "corequis": "",
      "unités": "2,66",
      "theorie": "2 h",
      "labo": "4 h",
      "étude": "2 h",
      "compétence": "02HB Analyser des informations techniques; 02HJ Programmer des éléments programmables"
    },
    {
      "code": "243-276-LI",
      "titre": "Électronique 2: circuits numériques",
      "préalable": "50 % 243-176-LI",
      "corequis": "",
      "unités": "2,66",
      "theorie": "2 h",
      "labo": "4 h",
      "étude": "2 h",
      "compétence": "02HA Résoudre des problèmes en électronique; 02HB Analyser des informations techniques; 02HC Analyser des circuits; 02HF Réaliser des prises de mesures"
    },
    {
      "code": "243-315-LI",
      "titre": "Introduction aux systèmes d’exploitation",
      "préalable": "",
      "corequis": "",
      "unités": "2,66",
      "theorie": "2 h",
      "labo": "3 h",
      "étude": "3 h",
      "compétence": "02HL Exploiter des systèmes d’exploitation"
    },
    {
      "code": "243-336-LI",
      "titre": "Développement de produits 3: dessin et assemblages",
      "préalable": "60% 243-236-LI",
      "corequis": "",
      "unités": "2,66",
      "theorie": "2 h",
      "labo": "4 h",
      "étude": "2 h",
      "compétence": "02HH Assurer la fabrication de circuits imprimés; 02HQ Effectuer un diagnostic"
    },
    {
      "code": "243-356-LI",
      "titre": "Programmation 3: microcontrôleurs et périphériques",
      "préalable": "60% 243-256-LI",
      "corequis": "",
      "unités": "2,66",
      "theorie": "2 h",
      "labo": "4 h",
      "étude": "2 h",
      "compétence": "02HB Analyser des informations techniques; 02HJ Programmer des éléments programmables; 02HK Établir des communications avec un élément programmable"
    },
    {
      "code": "243-376-LI",
      "titre": "Électronique 3: circuits analogiques",
      "préalable": "60% 243-276-LI",
      "corequis": "",
      "unités": "2,66",
      "theorie": "2 h",
      "labo": "4 h",
      "étude": "2 h",
      "compétence": "02HA Résoudre des problèmes en électronique; 02HB Analyser des informations techniques; 02HC Analyser des circuits"
    },
    {
      "code": "243-436-LI",
      "titre": "Développement de produits 4 : dessin et certifications",
      "préalable": "60% 243-336-LI",
      "corequis": "",
      "unités": "2,66",
      "theorie": "2 h",
      "labo": "4 h",
      "étude": "2 h",
      "compétence": "02HR Réaliser des tests; 02HW Contrôler la qualité d’équipements et/ou de systèmes"
    },
    {
      "code": "243-456-LI",
      "titre": "Programmation 4 : objets et systèmes",
      "préalable": "60% 243-356-LI",
      "corequis": "",
      "unités": "2,66",
      "theorie": "2 h",
      "labo": "4 h",
      "étude": "2 h",
      "compétence": "02HJ Programmer des éléments programmables; 02HK Établir des communications avec un élément programmable; 02HM Exploiter des objets connectés en réseau"
    },
    {
      "code": "243-476-LI",
      "titre": "Électronique 4 : circuits spécialisés",
      "préalable": "60% 243-376-LI",
      "corequis": "",
      "unités": "2,66",
      "theorie": "2 h",
      "labo": "4 h",
      "étude": "2 h",
      "compétence": "02HA Résoudre des problèmes en électronique; 02HB Analyser des informations techniques; 02HC Analyser des circuits"
    },
    {
      "code": "235-010-LI",
      "titre": "Gestion d’activités en milieu de travail",
      "préalable": "",
      "corequis": "",
      "unités": "2,66",
      "theorie": "2 h",
      "labo": "3 h",
      "étude": "3 h",
      "compétence": "02HE Planifier la réalisation des tâches professionnelles; 02HP Produire des documents techniques; 02HY Contribuer au changement technologique"
    },
    {
      "code": "243-538-LI",
      "titre": "Fabrication de systèmes et tests",
      "préalable": "60% 243-436-LI",
      "corequis": "",
      "unités": "3,66",
      "theorie": "2 h",
      "labo": "6 h",
      "étude": "3 h",
      "compétence": "02HQ Effectuer un diagnostic; 02HR Réaliser des tests; 02HX Assurer le soutien technique"
    },
    {
      "code": "243-557-LI",
      "titre": "Programmation de systèmes et tests",
      "préalable": "60% 243-456-LI",
      "corequis": "",
      "unités": "3,00",
      "theorie": "2 h",
      "labo": "5 h",
      "étude": "2 h",
      "compétence": "02HK Établir des communications avec un élément programmable; 02HU Participer au développement de la partie logicielle"
    },
    {
      "code": "243-577-LI",
      "titre": "Conception de systèmes et tests",
      "préalable": "60% 243-476-LI",
      "corequis": "",
      "unités": "3,00",
      "theorie": "2 h",
      "labo": "5 h",
      "étude": "2 h",
      "compétence": "02HC Analyser des circuits; 02HN Exploiter des capteurs et des actionneurs; 02HT Participer au développement d’un prototype; 02HY Contribuer au changement technologique"
    },
    {
      "code": "350-021-LI",
      "titre": "Psychologie du travail en électronique programmable",
      "préalable": "",
      "corequis": "",
      "unités": "1,33",
      "theorie": "2 h",
      "labo": "1 h",
      "étude": "1 h",
      "compétence": "02H9 Interagir en contexte professionnel; 02HX Assurer le soutien technique"
    },
    {
      "code": "243-614-LI",
      "titre": "Développement d’un projet d’inspiration",
      "préalable": "60% 243-476-LI",
      "corequis": "243-637-LI et 243-656-LI",
      "unités": "2,00",
      "theorie": "2 h",
      "labo": "2 h",
      "étude": "2 h",
      "compétence": "02HP Produire des documents techniques; 02HT Participer au développement d’un prototype; 02HY Contribuer au changement technologique"
    },
    {
      "code": "243-637-LI",
      "titre": "Fabrication d’un projet d’inspiration",
      "préalable": "60% 243-436-LI",
      "corequis": "243-614-LI et 243-656-LI",
      "unités": "3,00",
      "theorie": "2 h",
      "labo": "5 h",
      "étude": "2 h",
      "compétence": "02HR Réaliser des tests; 02HS Élaborer une preuve de concept; 02HW Contrôler la qualité d’équipements et/ou de systèmes"
    },
    {
      "code": "243-656-LI",
      "titre": "Programmation d’un projet d’inspiration",
      "préalable": "60% 243-456-LI",
      "corequis": "243-614-LI et 243-637-LI",
      "unités": "2,66",
      "theorie": "2 h",
      "labo": "4 h",
      "étude": "2 h",
      "compétence": "02HU Participer au développement de la partie logicielle; 02HV Intégrer les parties d’un système programmable"
    },
    {
      "code": "243-675-LI",
      "titre": "Fabrication d’un projet dirigé (ASP)",
      "préalable": "60% 243-538-LI, 60% 243-557-LI et 60% 243-577-LI",
      "corequis": "243-695-LI",
      "unités": "2,33",
      "theorie": "2 h",
      "labo": "3 h",
      "étude": "2 h",
      "compétence": "02HR Réaliser des tests; 02HT Participer au développement d’un prototype; 02HW Contrôler la qualité d’équipements et/ou de systèmes; 02HX Assurer le soutien technique"
    },
    {
      "code": "243-695-LI",
      "titre": "Programmation d’un projet dirigé (ASP)",
      "préalable": "60% 243-538-LI, 60% 243-557-LI et 60% 243-577-LI",
      "corequis": "243-675-LI",
      "unités": "2,33",
      "theorie": "2 h",
      "labo": "3 h",
      "étude": "2 h",
      "compétence": "02HS Élaborer une preuve de concept; 02HU Participer au développement de la partie logicielle; 02HV Intégrer les parties d’un système programmable"
    }
  ]
}
'''

# Chargez le JSON
data = json.loads(json_data)

# Dictionnaire pour stocker la correspondance {code_cours: id}
cours_mapping = {}

# Fonctions utilitaires pour la conversion
def parse_float(val_str):
    return float(val_str.replace(',', '.').strip())

def parse_heures(val_str):
    match = re.match(r'(\d+)', val_str.strip())
    return int(match.group(1)) if match else 0

# On utilise programme_id = 3 pour tous les cours
programme_id = 3

with app.app_context():
    # Première étape : insertion des cours dans la table Cours
    for cours in data["courses"]:
        nouveau_cours = Cours(
            programme_id=programme_id,
            code=cours["code"],
            nom=cours["titre"],
            nombre_unites=parse_float(cours["unités"]),
            heures_theorie=parse_heures(cours["theorie"]),
            heures_laboratoire=parse_heures(cours["labo"]),
            heures_travail_maison=parse_heures(cours["étude"])
        )
        db.session.add(nouveau_cours)
        db.session.flush()  # pour attribuer un id
        cours_mapping[cours["code"]] = nouveau_cours.id

    # Deuxième étape : insertion des préalables et corequis
    def extraire_codes(champ):
        """
        Extrait la liste des codes de cours depuis une chaîne.
        Exemple : "50 % 243-136-LI" ou "243-614-LI et 243-656-LI"
        """
        if not champ:
            return []
        codes = re.findall(r'\d{3}-\d{3,}-LI', champ)
        return codes

    for cours in data["courses"]:
        cours_id = cours_mapping[cours["code"]]

        # Traiter les préalables
        prerequis = extraire_codes(cours["préalable"])
        note = None
        note_match = re.search(r'(\d+)\s*%', cours["préalable"])
        if note_match:
            note = int(note_match.group(1))
        for code_pre in prerequis:
            if code_pre in cours_mapping:
                cp = CoursPrealable(
                    cours_id=cours_id,
                    cours_prealable_id=cours_mapping[code_pre],
                    note_necessaire=note
                )
                db.session.add(cp)
            else:
                print(f"Avertissement : le cours préalable {code_pre} n'existe pas dans les données insérées.")

        # Traiter les corequis
        corequis = extraire_codes(cours["corequis"])
        for code_co in corequis:
            if code_co in cours_mapping:
                cc = CoursCorequis(
                    cours_id=cours_id,
                    cours_corequis_id=cours_mapping[code_co]
                )
                db.session.add(cc)
            else:
                print(f"Avertissement : le cours corequis {code_co} n'existe pas dans les données insérées.")

    # Finalement, commit de la transaction
    db.session.commit()

print("Insertion terminée avec succès.")
