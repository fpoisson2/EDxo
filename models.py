# models.py
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy


class User(UserMixin):
    def __init__(self, id, username, password, role):
        self.id = id
        self.username = username
        self.password = password
        self.role = role

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# ---------------------
# 1) Modèles Cours et PlanCadre
# ---------------------

class Cours(db.Model):
    """
    Représente un cours.
    """
    __tablename__ = "Cours"
    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, nullable=False)
    code = db.Column(db.Text, nullable=False)
    nom = db.Column(db.Text, nullable=False)
    nombre_unites = db.Column(db.Float, nullable=False, default=1.0)
    session = db.Column(db.Integer, nullable=False, default=0)
    heures_theorie = db.Column(db.Integer, nullable=False, default=0)
    heures_laboratoire = db.Column(db.Integer, nullable=False, default=0)
    heures_travail_maison = db.Column(db.Integer, nullable=False, default=0)
    fil_conducteur_id = db.Column(db.Integer, nullable=True)  # Optionnel

    # Relations
    plan_cadre = db.relationship("PlanCadre", back_populates="cours", uselist=False)
    plans_de_cours = db.relationship("PlanDeCours", back_populates="cours")

    def __repr__(self):
        return f"<Cours {self.code} - {self.nom}>"


class PlanCadre(db.Model):
    """
    Représente le plan-cadre d'un cours.
    """
    __tablename__ = "PlanCadre"
    id = db.Column(db.Integer, primary_key=True)
    cours_id = db.Column(db.Integer, db.ForeignKey("Cours.id"), nullable=False, unique=True)

    # Champ: place et rôle du cours dans le programme
    place_intro = db.Column(db.Text, nullable=True)

    # Relations: Capacités, Savoir-être, Évaluations sommatives
    capacites = db.relationship("PlanCadreCapacites", back_populates="plan_cadre", cascade="all, delete-orphan")
    savoirs_etre = db.relationship("PlanCadreSavoirEtre", back_populates="plan_cadre", cascade="all, delete-orphan")

    # Relation vers Cours
    cours = db.relationship("Cours", back_populates="plan_cadre")

    def __repr__(self):
        return f"<PlanCadre id={self.id} pour Cours id={self.cours_id}>"


class PlanCadreCapacites(db.Model):
    """
    Une capacité du plan-cadre, incluant sa description et sa pondération.
    """
    __tablename__ = "PlanCadreCapacites"
    id = db.Column(db.Integer, primary_key=True)
    plan_cadre_id = db.Column(db.Integer, db.ForeignKey("PlanCadre.id"), nullable=False)

    # Champs requis par la BD
    capacite = db.Column(db.Text, nullable=False)
    description_capacite = db.Column(db.Text, nullable=True)
    ponderation_min = db.Column(db.Integer, nullable=False, default=0)
    ponderation_max = db.Column(db.Integer, nullable=False, default=0)

    # Relation vers le plan-cadre
    plan_cadre = db.relationship("PlanCadre", back_populates="capacites")

    # Relations vers les sous-éléments (savoirs nécessaires, savoir-faire, moyens d'évaluation)
    savoirs_necessaires = db.relationship(
        "PlanCadreCapaciteSavoirsNecessaires",
        back_populates="capacite",
        cascade="all, delete-orphan"
    )
    savoirs_faire = db.relationship(
        "PlanCadreCapaciteSavoirsFaire",
        back_populates="capacite",
        cascade="all, delete-orphan"
    )
    moyens_evaluation = db.relationship(
        "PlanCadreCapaciteMoyensEvaluation",
        back_populates="capacite",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<PlanCadreCapacites id={self.id} plan_cadre_id={self.plan_cadre_id}>"

class PlanCadreCapaciteSavoirsNecessaires(db.Model):
    """
    Savoirs nécessaires associés à une capacité du plan-cadre.
    """
    __tablename__ = "PlanCadreCapaciteSavoirsNecessaires"
    id = db.Column(db.Integer, primary_key=True)
    capacite_id = db.Column(db.Integer, db.ForeignKey("PlanCadreCapacites.id"), nullable=False)

    texte = db.Column(db.Text, nullable=False)

    # Relation vers la capacité
    capacite = db.relationship("PlanCadreCapacites", back_populates="savoirs_necessaires")

    def __repr__(self):
        return f"<PlanCadreCapaciteSavoirsNecessaires id={self.id} capacite_id={self.capacite_id}>"


class PlanCadreCapaciteSavoirsFaire(db.Model):
    """
    Savoir-faire associés à une capacité du plan-cadre.
    """
    __tablename__ = "PlanCadreCapaciteSavoirsFaire"
    id = db.Column(db.Integer, primary_key=True)
    capacite_id = db.Column(db.Integer, db.ForeignKey("PlanCadreCapacites.id"), nullable=False)

    texte = db.Column(db.Text, nullable=False)
    cible = db.Column(db.Text, nullable=True)
    seuil_reussite = db.Column(db.Text, nullable=True)

    # Relation vers la capacité
    capacite = db.relationship("PlanCadreCapacites", back_populates="savoirs_faire")

    def __repr__(self):
        return f"<PlanCadreCapaciteSavoirsFaire id={self.id} capacite_id={self.capacite_id}>"

class PlanCadreCapaciteMoyensEvaluation(db.Model):
    """
    Moyens d’évaluation associés à une capacité du plan-cadre.
    """
    __tablename__ = "PlanCadreCapaciteMoyensEvaluation"
    id = db.Column(db.Integer, primary_key=True)
    capacite_id = db.Column(db.Integer, db.ForeignKey("PlanCadreCapacites.id"), nullable=False)

    texte = db.Column(db.Text, nullable=False)

    # Relation vers la capacité
    capacite = db.relationship("PlanCadreCapacites", back_populates="moyens_evaluation")

    def __repr__(self):
        return f"<PlanCadreCapaciteMoyensEvaluation id={self.id} capacite_id={self.capacite_id}>"


class PlanCadreSavoirEtre(db.Model):
    """
    Savoir-être associés au plan-cadre.
    """
    __tablename__ = "PlanCadreSavoirEtre"
    id = db.Column(db.Integer, primary_key=True)
    plan_cadre_id = db.Column(db.Integer, db.ForeignKey("PlanCadre.id"), nullable=False)

    texte = db.Column(db.Text, nullable=False)

    plan_cadre = db.relationship("PlanCadre", back_populates="savoirs_etre")

    def __repr__(self):
        return f"<PlanCadreSavoirEtre id={self.id} plan_cadre_id={self.plan_cadre_id}>"

# ---------------------
# 2) Modèles PlanDeCours
# ---------------------

class PlanDeCours(db.Model):
    """
    Représente un plan de cours (nouvelle table).
    """
    __tablename__ = "PlanDeCours"
    id = db.Column(db.Integer, primary_key=True)
    cours_id = db.Column(db.Integer, db.ForeignKey("Cours.id"), nullable=False)

    session = db.Column(db.Text, nullable=False)  # Ex: "A23", "H24"
    campus = db.Column(db.Text, nullable=False) 

    # Champs "nouveaux"
    presentation_du_cours = db.Column(db.Text, nullable=True)
    objectif_terminal_du_cours = db.Column(db.Text, nullable=True)
    organisation_et_methodes = db.Column(db.Text, nullable=True)
    accomodement = db.Column(db.Text, nullable=True)
    evaluation_formative_apprentissages = db.Column(db.Text, nullable=True)
    evaluation_expression_francais = db.Column(db.Text, nullable=True)
    seuil_reussite = db.Column(db.Text, nullable=True)

    nom_enseignant = db.Column(db.Text, nullable=True)
    telephone_enseignant = db.Column(db.Text, nullable=True)
    courriel_enseignant = db.Column(db.Text, nullable=True)
    bureau_enseignant = db.Column(db.Text, nullable=True)

    # Relations vers les sous-éléments
    calendriers = db.relationship("PlanDeCoursCalendrier", back_populates="plan_de_cours", cascade="all, delete-orphan")
    mediagraphies = db.relationship("PlanDeCoursMediagraphie", back_populates="plan_de_cours", cascade="all, delete-orphan")
    disponibilites = db.relationship("PlanDeCoursDisponibiliteEnseignant", back_populates="plan_de_cours", cascade="all, delete-orphan")
    evaluations = db.relationship("PlanDeCoursEvaluations", back_populates="plan_de_cours", cascade="all, delete-orphan")

    # Relation vers Cours
    cours = db.relationship("Cours", back_populates="plans_de_cours")

    def __repr__(self):
        return f"<PlanDeCours id={self.id}, session={self.session} pour Cours id={self.cours_id}>"


class PlanDeCoursCalendrier(db.Model):
    """
    Calendrier des activités (semaine, sujet, etc.).
    """
    __tablename__ = "PlanDeCoursCalendrier"
    id = db.Column(db.Integer, primary_key=True)
    plan_de_cours_id = db.Column(db.Integer, db.ForeignKey("PlanDeCours.id"), nullable=False)

    semaine = db.Column(db.Integer, nullable=True)
    sujet = db.Column(db.Text, nullable=True)
    activites = db.Column(db.Text, nullable=True)
    travaux_hors_classe = db.Column(db.Text, nullable=True)
    evaluations = db.Column(db.Text, nullable=True)

    plan_de_cours = db.relationship("PlanDeCours", back_populates="calendriers")

    def __repr__(self):
        return f"<PlanDeCoursCalendrier id={self.id} plan_de_cours_id={self.plan_de_cours_id}>"


class PlanDeCoursMediagraphie(db.Model):
    """
    Liste de références bibliographiques / médiagraphie.
    """
    __tablename__ = "PlanDeCoursMediagraphie"
    id = db.Column(db.Integer, primary_key=True)
    plan_de_cours_id = db.Column(db.Integer, db.ForeignKey("PlanDeCours.id"), nullable=False)

    reference_bibliographique = db.Column(db.Text, nullable=False)

    plan_de_cours = db.relationship("PlanDeCours", back_populates="mediagraphies")

    def __repr__(self):
        return f"<PlanDeCoursMediagraphie id={self.id} plan_de_cours_id={self.plan_de_cours_id}>"


class PlanDeCoursDisponibiliteEnseignant(db.Model):
    """
    Disponibilités de l’enseignant (jour, plage horaire, local).
    """
    __tablename__ = "PlanDeCoursDisponibiliteEnseignant"
    id = db.Column(db.Integer, primary_key=True)
    plan_de_cours_id = db.Column(db.Integer, db.ForeignKey("PlanDeCours.id"), nullable=False)

    jour_semaine = db.Column(db.Text, nullable=True)             # Ex: "Lundi", "Mardi", etc.
    plage_horaire = db.Column(db.Text, nullable=True)    # Ex: "9h-11h", "14h-16h"
    lieu = db.Column(db.Text, nullable=True)     # Ex: "Bureau 101"

    plan_de_cours = db.relationship("PlanDeCours", back_populates="disponibilites")

    def __repr__(self):
        return f"<PlanDeCoursDisponibiliteEnseignant id={self.id} plan_de_cours_id={self.plan_de_cours_id}>"


class PlanDeCoursEvaluations(db.Model):
    """
    Évaluations propres au plan de cours.
    """
    __tablename__ = "PlanDeCoursEvaluations"
    id = db.Column(db.Integer, primary_key=True)
    plan_de_cours_id = db.Column(db.Integer, db.ForeignKey("PlanDeCours.id"), nullable=False)

    titre_evaluation = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    semaine = db.Column(db.Integer, nullable=True)
    ponderation = db.Column(db.Text, nullable=True)  # Ex: "20%"

    plan_de_cours = db.relationship("PlanDeCours", back_populates="evaluations")

    def __repr__(self):
        return f"<PlanDeCoursEvaluations id={self.id} plan_de_cours_id={self.plan_de_cours_id}>"