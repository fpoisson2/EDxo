#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# Configuration de l'application Flask et de la base de données
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.abspath('programme.db?timeout=30')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Modèles de données
class Cours(db.Model):
    __tablename__ = "Cours"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.Text, nullable=False, unique=True)
    nom = db.Column(db.Text, nullable=False)

    def __repr__(self):
        return f"<Cours {self.code} - {self.nom}>"

class Competence(db.Model):
    __tablename__ = "Competence"
    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, nullable=False)
    code = db.Column(db.Text, nullable=False)
    nom = db.Column(db.Text, nullable=False)
    criteria_de_performance = db.Column(db.Text, nullable=True)
    contexte_de_realisation = db.Column(db.Text, nullable=True)
    
    elements = db.relationship("ElementCompetence", back_populates="competence", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Competence {self.code} - {self.nom}>"

class ElementCompetence(db.Model):
    __tablename__ = "ElementCompetence"
    id = db.Column(db.Integer, primary_key=True)
    competence_id = db.Column(db.Integer, db.ForeignKey('Competence.id'), nullable=False)
    nom = db.Column(db.Text, nullable=False)
    
    competence = db.relationship("Competence", back_populates="elements")

    def __repr__(self):
        return f"<ElementCompetence {self.nom}>"

class ElementCompetenceParCours(db.Model):
    __tablename__ = "ElementCompetenceParCours"
    id = db.Column(db.Integer, primary_key=True)
    cours_id = db.Column(db.Integer, db.ForeignKey('Cours.id'), nullable=False)
    element_competence_id = db.Column(db.Integer, db.ForeignKey('ElementCompetence.id'), nullable=False)
    status = db.Column(db.Text, nullable=False, server_default="Non traité")

    cours = db.relationship("Cours")
    element_competence = db.relationship("ElementCompetence")

    def __repr__(self):
        return f"<ElementCompetenceParCours cours_id={self.cours_id} status={self.status}>"

# ------------------------------------------------------------------------------
# Fonction de chargement des données JSON des cours
# ------------------------------------------------------------------------------
def load_courses_data():
    """
    Charge les données JSON des cours.
    Dans cet exemple, le JSON est inclus directement dans le code.
    """
    json_data = r'''
{
  "courses": [
    {
      "code": "243-115-LI",
      "titre": "Introduction à la profession",
      "compétences": [
        {
          "code": "02H8",
          "description": "Explorer la profession",
          "statut": "Développé significativement"
        },
        {
          "code": "02HG",
          "description": "Réaliser des travaux d’atelier",
          "statut": "Développé significativement"
        },
        {
          "code": "02HP",
          "description": "Produire des documents techniques",
          "statut": "Développé significativement"
        }
      ]
    },
    {
      "code": "243-136-LI",
      "titre": "Développement de produits 1 : introduction",
      "compétences": [
        {
          "code": "02HD",
          "description": "Produire des schémas électroniques",
          "statut": "Développé significativement"
        }
      ]
    },
    {
      "code": "243-156-LI",
      "titre": "Programmation 1 : introduction",
      "compétences": [
        {
          "code": "02HJ",
          "description": "Programmer des éléments programmables",
          "statut": "Développé significativement"
        }
      ]
    },
    {
      "code": "243-176-LI",
      "titre": "Électronique 1: composants et circuits de base",
      "compétences": [
        {
          "code": "02HA",
          "description": "Résoudre des problèmes en électronique",
          "statut": "Développé significativement"
        },
        {
          "code": "02HB",
          "description": "Analyser des informations techniques",
          "statut": "Développé significativement"
        },
        {
          "code": "02HF",
          "description": "Réaliser des prises de mesures",
          "statut": "Développé significativement"
        }
      ]
    },
    {
      "code": "243-214-LI",
      "titre": "Réalisation de projets électroniques programmables",
      "compétences": [
        {
          "code": "02HG",
          "description": "Réaliser des travaux d’atelier",
          "statut": "Atteint"
        }
      ]
    },
    {
      "code": "243-236-LI",
      "titre": "Développement de produits 2: dessin et prototypes",
      "compétences": [
        {
          "code": "02HD",
          "description": "Produire des schémas électroniques",
          "statut": "Atteint"
        },
        {
          "code": "02HH",
          "description": "Assurer la fabrication de circuits imprimés",
          "statut": "Développé significativement"
        }
      ]
    },
    {
      "code": "243-256-LI",
      "titre": "Programmation 2: outils et microcontrôleurs",
      "compétences": [
        {
          "code": "02HB",
          "description": "Analyser des informations techniques",
          "statut": "Développé significativement"
        },
        {
          "code": "02HJ",
          "description": "Programmer des éléments programmables",
          "statut": "Développé significativement"
        }
      ]
    },
    {
      "code": "243-276-LI",
      "titre": "Électronique 2: circuits numériques",
      "compétences": [
        {
          "code": "02HA",
          "description": "Résoudre des problèmes en électronique",
          "statut": "Développé significativement"
        },
        {
          "code": "02HB",
          "description": "Analyser des informations techniques",
          "statut": "Développé significativement"
        },
        {
          "code": "02HC",
          "description": "Analyser des circuits",
          "statut": "Développé significativement"
        },
        {
          "code": "02HF",
          "description": "Réaliser des prises de mesures",
          "statut": "Atteint"
        }
      ]
    },
    {
      "code": "243-315-LI",
      "titre": "Introduction aux systèmes d’exploitation",
      "compétences": [
        {
          "code": "02HL",
          "description": "Exploiter des systèmes d’exploitation",
          "statut": "Atteint"
        }
      ]
    },
    {
      "code": "243-336-LI",
      "titre": "Développement de produits 3: dessin et assemblages",
      "compétences": [
        {
          "code": "02HH",
          "description": "Assurer la fabrication de circuits imprimés",
          "statut": "Atteint"
        },
        {
          "code": "02HQ",
          "description": "Effectuer un diagnostic",
          "statut": "Développé significativement"
        }
      ]
    },
    {
      "code": "243-356-LI",
      "titre": "Programmation 3: microcontrôleurs et périphériques",
      "compétences": [
        {
          "code": "02HB",
          "description": "Analyser des informations techniques",
          "statut": "Développé significativement"
        },
        {
          "code": "02HJ",
          "description": "Programmer des éléments programmables",
          "statut": "Développé significativement"
        },
        {
          "code": "02HK",
          "description": "Établir des communications avec un élément programmable",
          "statut": "Développé significativement"
        }
      ]
    },
    {
      "code": "243-376-LI",
      "titre": "Électronique 3: circuits analogiques",
      "compétences": [
        {
          "code": "02HA",
          "description": "Résoudre des problèmes en électronique",
          "statut": "Développé significativement"
        },
        {
          "code": "02HB",
          "description": "Analyser des informations techniques",
          "statut": "Développé significativement"
        },
        {
          "code": "02HC",
          "description": "Analyser des circuits",
          "statut": "Développé significativement"
        }
      ]
    },
    {
      "code": "243-436-LI",
      "titre": "Développement de produits 4 : dessin et certifications",
      "compétences": [
        {
          "code": "02HR",
          "description": "Réaliser des tests",
          "statut": "Développé significativement"
        },
        {
          "code": "02HW",
          "description": "Contrôler la qualité d’équipements et/ou de systèmes",
          "statut": "Développé significativement"
        }
      ]
    },
    {
      "code": "243-456-LI",
      "titre": "Programmation 4 : objets et systèmes",
      "compétences": [
        {
          "code": "02HJ",
          "description": "Programmer des éléments programmables",
          "statut": "Développé significativement"
        },
        {
          "code": "02HK",
          "description": "Établir des communications avec un élément programmable",
          "statut": "Développé significativement"
        },
        {
          "code": "02HM",
          "description": "Exploiter des objets connectés en réseau",
          "statut": "Atteint"
        }
      ]
    },
    {
      "code": "243-476-LI",
      "titre": "Électronique 4 : circuits spécialisés",
      "compétences": [
        {
          "code": "02HA",
          "description": "Résoudre des problèmes en électronique",
          "statut": "Atteint"
        },
        {
          "code": "02HB",
          "description": "Analyser des informations techniques",
          "statut": "Atteint"
        },
        {
          "code": "02HC",
          "description": "Analyser des circuits",
          "statut": "Atteint"
        }
      ]
    },
    {
      "code": "235-010-LI",
      "titre": "Gestion d’activités en milieu de travail",
      "compétences": [
        {
          "code": "02HE",
          "description": "Planifier la réalisation des tâches professionnelles",
          "statut": "Atteint"
        },
        {
          "code": "02HP",
          "description": "Produire des documents techniques",
          "statut": "Développé significativement"
        },
        {
          "code": "02HY",
          "description": "Contribuer au changement technologique",
          "statut": "Développé significativement"
        }
      ]
    },
    {
      "code": "243-538-LI",
      "titre": "Fabrication de systèmes et tests",
      "compétences": [
        {
          "code": "02HQ",
          "description": "Effectuer un diagnostic",
          "statut": "Atteint"
        },
        {
          "code": "02HR",
          "description": "Réaliser des tests",
          "statut": "Développé significativement"
        },
        {
          "code": "02HX",
          "description": "Assurer le soutien technique",
          "statut": "Développé significativement"
        }
      ]
    },
    {
      "code": "243-557-LI",
      "titre": "Programmation de systèmes et tests",
      "compétences": [
        {
          "code": "02HK",
          "description": "Établir des communications avec un élément programmable",
          "statut": "Atteint"
        },
        {
          "code": "02HU",
          "description": "Participer au développement de la partie logicielle",
          "statut": "Développé significativement"
        }
      ]
    },
    {
      "code": "243-577-LI",
      "titre": "Conception de systèmes et tests",
      "compétences": [
        {
          "code": "02HC",
          "description": "Analyser des circuits",
          "statut": "Développé significativement"
        },
        {
          "code": "02HN",
          "description": "Exploiter des capteurs et des actionneurs",
          "statut": "Atteint"
        },
        {
          "code": "02HT",
          "description": "Participer au développement d’un prototype",
          "statut": "Développé significativement"
        },
        {
          "code": "02HY",
          "description": "Contribuer au changement technologique",
          "statut": "Atteint"
        }
      ]
    },
    {
      "code": "350-021-LI",
      "titre": "Psychologie du travail en électronique programmable",
      "compétences": [
        {
          "code": "02H9",
          "description": "Interagir en contexte professionnel",
          "statut": "Atteint"
        },
        {
          "code": "02HX",
          "description": "Assurer le soutien technique",
          "statut": "Développé significativement"
        }
      ]
    },
    {
      "code": "243-614-LI",
      "titre": "Développement d’un projet d’inspiration",
      "compétences": [
        {
          "code": "02HP",
          "description": "Produire des documents techniques",
          "statut": "Atteint"
        },
        {
          "code": "02HT",
          "description": "Participer au développement d’un prototype",
          "statut": "Développé significativement"
        },
        {
          "code": "02HY",
          "description": "Contribuer au changement technologique",
          "statut": "Développé significativement"
        }
      ]
    },
    {
      "code": "243-637-LI",
      "titre": "Fabrication d’un projet d’inspiration",
      "compétences": [
        {
          "code": "02HR",
          "description": "Réaliser des tests",
          "statut": "Développé significativement"
        },
        {
          "code": "02HS",
          "description": "Élaborer une preuve de concept",
          "statut": "Développé significativement"
        },
        {
          "code": "02HW",
          "description": "Contrôler la qualité d’équipements et/ou de systèmes",
          "statut": "Atteint"
        }
      ]
    },
    {
      "code": "243-656-LI",
      "titre": "Programmation d’un projet d’inspiration",
      "compétences": [
        {
          "code": "02HU",
          "description": "Participer au développement de la partie logicielle",
          "statut": "Développé significativement"
        },
        {
          "code": "02HV",
          "description": "Intégrer les parties d’un système programmable",
          "statut": "Développé significativement"
        }
      ]
    },
    {
      "code": "243-675-LI",
      "titre": "Fabrication d’un projet dirigé (ASP)",
      "compétences": [
        {
          "code": "02HR",
          "description": "Réaliser des tests",
          "statut": "Développé significativement"
        },
        {
          "code": "02HT",
          "description": "Participer au développement d’un prototype",
          "statut": "Développé significativement"
        },
        {
          "code": "02HW",
          "description": "Contrôler la qualité d’équipements et/ou de systèmes",
          "statut": "Développé significativement"
        },
        {
          "code": "02HX",
          "description": "Assurer le soutien technique",
          "statut": "Atteint"
        }
      ]
    },
    {
      "code": "243-695-LI",
      "titre": "Programmation d’un projet dirigé (ASP)",
      "compétences": [
        {
          "code": "02HS",
          "description": "Élaborer une preuve de concept",
          "statut": "Atteint"
        },
        {
          "code": "02HU",
          "description": "Participer au développement de la partie logicielle",
          "statut": "Atteint"
        },
        {
          "code": "02HV",
          "description": "Intégrer les parties d’un système programmable",
          "statut": "Atteint"
        }
      ]
    }
  ]
}

    '''
    return json.loads(json_data)

def insert_element_competence_par_cours():
    """
    Parcourt les données JSON et pour chaque cours :
    1. Trouve ou crée la compétence
    2. Pour chaque élément de compétence de cette compétence :
        - Trouve ou crée l'élément de compétence
        - Crée une entrée dans ElementCompetenceParCours avec le statut associé
    """
    print("[INFO] Chargement des données de cours...")
    data = load_courses_data()
    courses_data = data.get("courses", [])
    nb_insert = 0

    print(f"[INFO] {len(courses_data)} cours trouvés dans les données JSON.")

    for course_entry in courses_data:
        cours_code = course_entry.get("code")
        print(f"[INFO] Traitement du cours '{cours_code}'...")

        # Recherche du cours
        cours = Cours.query.filter_by(code=cours_code).first()
        if not cours:
            print(f"[WARN] Cours avec code '{cours_code}' non trouvé en BD.")
            continue

        print(f"[INFO] Cours trouvé : ID={cours.id}, Code='{cours_code}'.")

        for comp_entry in course_entry.get("compétences", []):
            comp_code = comp_entry.get("code")
            comp_desc = comp_entry.get("description")
            statut = comp_entry.get("statut", "Non traité")

            # Trouve ou crée la compétence
            competence = Competence.query.filter_by(code=comp_code).first()
            if not competence:
                competence = Competence(
                    programme_id=3,  # À ajuster selon votre contexte
                    code=comp_code,
                    nom=comp_desc
                )
                db.session.add(competence)
                db.session.flush()
                print(f"[INFO] Nouvelle compétence ajoutée : ID={competence.id}, Code='{comp_code}'.")
            else:
                print(f"[INFO] Compétence existante trouvée : ID={competence.id}, Code='{comp_code}'.")

            # Boucle sur les éléments de compétence associés
            for element in competence.elements:
                # Crée l'entrée dans ElementCompetenceParCours avec le statut associé
                ecp = ElementCompetenceParCours(
                    cours_id=cours.id,
                    element_competence_id=element.id,
                    status=statut
                )
                db.session.add(ecp)
                nb_insert += 1
                print(f"[INFO] Ajout dans ElementCompetenceParCours : Cours ID={cours.id}, Élément ID={element.id}, Status='{statut}'.")

    db.session.commit()
    print(f"[INFO] Insertion terminée. Total de {nb_insert} enregistrements ajoutés.")


if __name__ == '__main__':
    with app.app_context():
        # db.create_all()  # Décommenter si nécessaire
        insert_element_competence_par_cours()