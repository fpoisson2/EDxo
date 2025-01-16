from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# ------------------------------------------------------------------------------
# Modèle User (mise à jour pour correspondre au schéma)
# ------------------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "User"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.Text, nullable=False)
    password = db.Column(db.Text, nullable=False)
    role = db.Column(db.Text, nullable=False, server_default="invite")
    openai_key = db.Column(db.Text, nullable=True)
    cegep_id = db.Column(db.Integer, nullable=True)
    department_id = db.Column(db.Integer, nullable=True)

    def __repr__(self):
        return f"<User {self.username}>"

# ------------------------------------------------------------------------------
# Modèles liés aux compétences et éléments de compétences
# ------------------------------------------------------------------------------

class Competence(db.Model):
    __tablename__ = "Competence"
    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, nullable=False)
    code = db.Column(db.Text, nullable=False)
    nom = db.Column(db.Text, nullable=False)
    criteria_de_performance = db.Column(db.Text, nullable=True)
    contexte_de_realisation = db.Column(db.Text, nullable=True)

    # Relation vers éléments de compétence
    elements = db.relationship("ElementCompetence", back_populates="competence", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Competence {self.code} - {self.nom}>"

class ElementCompetence(db.Model):
    __tablename__ = "ElementCompetence"
    id = db.Column(db.Integer, primary_key=True)
    competence_id = db.Column(db.Integer, db.ForeignKey("Competence.id"), nullable=False)
    nom = db.Column(db.Text, nullable=False)

    # Relation vers le modèle Competence
    competence = db.relationship("Competence", back_populates="elements")
    # Relation vers les critères (un élément peut avoir plusieurs critères)
    criteria = db.relationship("ElementCompetenceCriteria", back_populates="element", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ElementCompetence {self.nom}>"

class ElementCompetenceCriteria(db.Model):
    __tablename__ = "ElementCompetenceCriteria"
    id = db.Column(db.Integer, primary_key=True)
    element_competence_id = db.Column(db.Integer, db.ForeignKey("ElementCompetence.id"), nullable=False)
    criteria = db.Column(db.Text, nullable=False)

    element = db.relationship("ElementCompetence", back_populates="criteria")

    def __repr__(self):
        return f"<ElementCompetenceCriteria {self.criteria[:20]}>"

# ------------------------------------------------------------------------------
# Autres tables complémentaires liées aux cours
# ------------------------------------------------------------------------------

class FilConducteur(db.Model):
    __tablename__ = "FilConducteur"
    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text, nullable=False)
    couleur = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<FilConducteur {self.description[:20]}>"

class CoursPrealable(db.Model):
    __tablename__ = "CoursPrealable"
    id = db.Column(db.Integer, primary_key=True)
    cours_id = db.Column(db.Integer, nullable=False)
    cours_prealable_id = db.Column(db.Integer, nullable=False)
    note_necessaire = db.Column(db.Integer, nullable=True)

    def __repr__(self):
        return f"<CoursPrealable cours_id={self.cours_id} prealable_id={self.cours_prealable_id}>"

class CoursCorequis(db.Model):
    __tablename__ = "CoursCorequis"
    id = db.Column(db.Integer, primary_key=True)
    cours_id = db.Column(db.Integer, nullable=False)
    cours_corequis_id = db.Column(db.Integer, nullable=False)

    def __repr__(self):
        return f"<CoursCorequis cours_id={self.cours_id} corequis_id={self.cours_corequis_id}>"

class CompetenceParCours(db.Model):
    __tablename__ = "CompetenceParCours"
    id = db.Column(db.Integer, primary_key=True)
    cours_id = db.Column(db.Integer, nullable=False)
    competence_developpee_id = db.Column(db.Integer, nullable=False)
    competence_atteinte_id = db.Column(db.Integer, nullable=False)

    def __repr__(self):
        return f"<CompetenceParCours cours_id={self.cours_id}>"

class ElementCompetenceParCours(db.Model):
    __tablename__ = "ElementCompetenceParCours"
    id = db.Column(db.Integer, primary_key=True)
    cours_id = db.Column(db.Integer, nullable=False)
    element_competence_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.Text, nullable=False, server_default="Non traité")

    def __repr__(self):
        return f"<ElementCompetenceParCours cours_id={self.cours_id} status={self.status}>"

# ------------------------------------------------------------------------------
# Modèles pour PlanCadre et ses éléments
# ------------------------------------------------------------------------------

class PlanCadre(db.Model):
    __tablename__ = "PlanCadre"
    id = db.Column(db.Integer, primary_key=True)
    cours_id = db.Column(db.Integer, db.ForeignKey("Cours.id"), nullable=False, unique=True)
    # Champs du schéma étendu :
    place_intro = db.Column(db.Text, nullable=True)
    objectif_terminal = db.Column(db.Text, nullable=True)
    structure_intro = db.Column(db.Text, nullable=True)
    structure_activites_theoriques = db.Column(db.Text, nullable=True)
    structure_activites_pratiques = db.Column(db.Text, nullable=True)
    structure_activites_prevues = db.Column(db.Text, nullable=True)
    eval_evaluation_sommative = db.Column(db.Text, nullable=True)
    eval_nature_evaluations_sommatives = db.Column(db.Text, nullable=True)
    eval_evaluation_de_la_langue = db.Column(db.Text, nullable=True)
    eval_evaluation_sommatives_apprentissages = db.Column(db.Text, nullable=True)
    additional_info = db.Column(db.Text, nullable=True)
    ai_model = db.Column(db.Text, nullable=True, server_default="gpt-4o")

    # Relations
    cours = db.relationship("Cours", back_populates="plan_cadre")
    capacites = db.relationship("PlanCadreCapacites", back_populates="plan_cadre", cascade="all, delete-orphan")
    savoirs_etre = db.relationship("PlanCadreSavoirEtre", back_populates="plan_cadre", cascade="all, delete-orphan")

    # Exemple de tables complémentaires (si besoin)
    objets_cibles = db.relationship("PlanCadreObjetsCibles", back_populates="plan_cadre", cascade="all, delete-orphan")
    cours_relies = db.relationship("PlanCadreCoursRelies", back_populates="plan_cadre", cascade="all, delete-orphan")
    cours_prealables = db.relationship("PlanCadreCoursPrealables", back_populates="plan_cadre", cascade="all, delete-orphan")
    competences_certifiees = db.relationship("PlanCadreCompetencesCertifiees", back_populates="plan_cadre", cascade="all, delete-orphan")
    competences_developpees = db.relationship("PlanCadreCompetencesDeveloppees", back_populates="plan_cadre", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<PlanCadre id={self.id} pour Cours id={self.cours_id}>"

    @classmethod
    def get_by_cours_info(cls, nom=None, code=None):
        """Récupère un plan-cadre à partir du nom ou du code du cours."""
        print(f"[DEBUG] get_by_cours_info appelé avec: nom={nom}, code={code}")
        
        if not nom and not code:
            print("[DEBUG] Aucun critère de recherche fourni")
            return None

        try:
            print("[DEBUG] Construction de la requête")
            query = db.session.query(cls).join(Cours)
            
            conditions = []
            print("[DEBUG] Ajout des conditions de filtrage")
            if nom:
                print(f"[DEBUG] Ajout condition nom: {nom}")
                conditions.append(Cours.nom.ilike(f"%{nom}%"))
            if code:
                print(f"[DEBUG] Ajout condition code: {code}")
                conditions.append(Cours.code.ilike(f"%{code}%"))

            query = query.filter(db.or_(*conditions))
            print(f"[DEBUG] Requête finale: {str(query)}")
            
            result = query.first()
            print(f"[DEBUG] Résultat de la requête: {result}")
            
            return result

        except Exception as e:
            print(f"[DEBUG] Erreur dans get_by_cours_info: {str(e)}")
            print(f"[DEBUG] Type d'erreur: {type(e)}")
            import traceback
            print("[DEBUG] Traceback:")
            traceback.print_exc()
            return None


class PlanCadreCapacites(db.Model):
    __tablename__ = "PlanCadreCapacites"
    id = db.Column(db.Integer, primary_key=True)
    plan_cadre_id = db.Column(db.Integer, db.ForeignKey("PlanCadre.id"), nullable=False)
    capacite = db.Column(db.Text, nullable=False)
    description_capacite = db.Column(db.Text, nullable=True)
    ponderation_min = db.Column(db.Integer, nullable=False, server_default="0")
    ponderation_max = db.Column(db.Integer, nullable=False, server_default="0")

    plan_cadre = db.relationship("PlanCadre", back_populates="capacites")
    savoirs_necessaires = db.relationship("PlanCadreCapaciteSavoirsNecessaires", back_populates="capacite", cascade="all, delete-orphan")
    savoirs_faire = db.relationship("PlanCadreCapaciteSavoirsFaire", back_populates="capacite", cascade="all, delete-orphan")
    moyens_evaluation = db.relationship("PlanCadreCapaciteMoyensEvaluation", back_populates="capacite", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<PlanCadreCapacites id={self.id} plan_cadre_id={self.plan_cadre_id}>"

class PlanCadreCapaciteSavoirsNecessaires(db.Model):
    __tablename__ = "PlanCadreCapaciteSavoirsNecessaires"
    id = db.Column(db.Integer, primary_key=True)
    capacite_id = db.Column(db.Integer, db.ForeignKey("PlanCadreCapacites.id"), nullable=False)
    texte = db.Column(db.Text, nullable=False)

    capacite = db.relationship("PlanCadreCapacites", back_populates="savoirs_necessaires")

    def __repr__(self):
        return f"<PlanCadreCapaciteSavoirsNecessaires id={self.id}>"

class PlanCadreCapaciteSavoirsFaire(db.Model):
    __tablename__ = "PlanCadreCapaciteSavoirsFaire"
    id = db.Column(db.Integer, primary_key=True)
    capacite_id = db.Column(db.Integer, db.ForeignKey("PlanCadreCapacites.id"), nullable=False)
    texte = db.Column(db.Text, nullable=False)
    cible = db.Column(db.Text, nullable=True)
    seuil_reussite = db.Column(db.Text, nullable=True)

    capacite = db.relationship("PlanCadreCapacites", back_populates="savoirs_faire")

    def __repr__(self):
        return f"<PlanCadreCapaciteSavoirsFaire id={self.id}>"

class PlanCadreCapaciteMoyensEvaluation(db.Model):
    __tablename__ = "PlanCadreCapaciteMoyensEvaluation"
    id = db.Column(db.Integer, primary_key=True)
    capacite_id = db.Column(db.Integer, db.ForeignKey("PlanCadreCapacites.id"), nullable=False)
    texte = db.Column(db.Text, nullable=False)

    capacite = db.relationship("PlanCadreCapacites", back_populates="moyens_evaluation")

    def __repr__(self):
        return f"<PlanCadreCapaciteMoyensEvaluation id={self.id}>"

class PlanCadreSavoirEtre(db.Model):
    __tablename__ = "PlanCadreSavoirEtre"
    id = db.Column(db.Integer, primary_key=True)
    plan_cadre_id = db.Column(db.Integer, db.ForeignKey("PlanCadre.id"), nullable=False)
    texte = db.Column(db.Text, nullable=False)

    plan_cadre = db.relationship("PlanCadre", back_populates="savoirs_etre")

    def __repr__(self):
        return f"<PlanCadreSavoirEtre id={self.id}>"

# Tables complémentaires optionnelles pour PlanCadre
class PlanCadreObjetsCibles(db.Model):
    __tablename__ = "PlanCadreObjetsCibles"
    id = db.Column(db.Integer, primary_key=True)
    plan_cadre_id = db.Column(db.Integer, db.ForeignKey("PlanCadre.id"), nullable=False)
    texte = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=True)

    plan_cadre = db.relationship("PlanCadre", back_populates="objets_cibles")

    def __repr__(self):
        return f"<PlanCadreObjetsCibles id={self.id}>"

class PlanCadreCoursRelies(db.Model):
    __tablename__ = "PlanCadreCoursRelies"
    id = db.Column(db.Integer, primary_key=True)
    plan_cadre_id = db.Column(db.Integer, db.ForeignKey("PlanCadre.id"), nullable=False)
    texte = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=True)

    plan_cadre = db.relationship("PlanCadre", back_populates="cours_relies")

    def __repr__(self):
        return f"<PlanCadreCoursRelies id={self.id}>"

class PlanCadreCoursPrealables(db.Model):
    __tablename__ = "PlanCadreCoursPrealables"
    id = db.Column(db.Integer, primary_key=True)
    plan_cadre_id = db.Column(db.Integer, db.ForeignKey("PlanCadre.id"), nullable=False)
    texte = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=True)

    plan_cadre = db.relationship("PlanCadre", back_populates="cours_prealables")

    def __repr__(self):
        return f"<PlanCadreCoursPrealables id={self.id}>"

class PlanCadreCompetencesCertifiees(db.Model):
    __tablename__ = "PlanCadreCompetencesCertifiees"
    id = db.Column(db.Integer, primary_key=True)
    plan_cadre_id = db.Column(db.Integer, db.ForeignKey("PlanCadre.id"), nullable=False)
    texte = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=True)

    plan_cadre = db.relationship("PlanCadre", back_populates="competences_certifiees")

    def __repr__(self):
        return f"<PlanCadreCompetencesCertifiees id={self.id}>"

class PlanCadreCompetencesDeveloppees(db.Model):
    __tablename__ = "PlanCadreCompetencesDeveloppees"
    id = db.Column(db.Integer, primary_key=True)
    plan_cadre_id = db.Column(db.Integer, db.ForeignKey("PlanCadre.id"), nullable=False)
    texte = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=True)

    plan_cadre = db.relationship("PlanCadre", back_populates="competences_developpees")

    def __repr__(self):
        return f"<PlanCadreCompetencesDeveloppees id={self.id}>"

# ------------------------------------------------------------------------------
# Modèles pour PlanDeCours et ses sous-éléments
# ------------------------------------------------------------------------------

class PlanDeCours(db.Model):
    __tablename__ = "PlanDeCours"
    id = db.Column(db.Integer, primary_key=True)
    cours_id = db.Column(db.Integer, db.ForeignKey("Cours.id"), nullable=False)
    department_id = db.Column(db.Integer, nullable=True)  # Comme dans le schéma étendu
    session = db.Column(db.Text, nullable=False)
    campus = db.Column(db.Text, nullable=True)
    nom_enseignant = db.Column(db.Text, nullable=True)
    telephone_enseignant = db.Column(db.Text, nullable=True)
    courriel_enseignant = db.Column(db.Text, nullable=True)
    bureau_enseignant = db.Column(db.Text, nullable=True)
    presentation_du_cours = db.Column(db.Text, nullable=True)
    objectif_terminal_du_cours = db.Column(db.Text, nullable=True)
    organisation_et_methodes = db.Column(db.Text, nullable=True)
    accomodement = db.Column(db.Text, nullable=True)
    evaluation_formative_apprentissages = db.Column(db.Text, nullable=True)
    evaluation_expression_francais = db.Column(db.Text, nullable=True)
    seuil_reussite = db.Column(db.Text, nullable=True)
    place_et_role_du_cours = db.Column(db.Text, nullable=True)
    materiel = db.Column(db.Text, nullable=True, server_default="''")

    # Relations
    cours = db.relationship("Cours", back_populates="plans_de_cours")
    calendriers = db.relationship("PlanDeCoursCalendrier", back_populates="plan_de_cours", cascade="all, delete-orphan")
    mediagraphies = db.relationship("PlanDeCoursMediagraphie", back_populates="plan_de_cours", cascade="all, delete-orphan")
    disponibilites = db.relationship("PlanDeCoursDisponibiliteEnseignant", back_populates="plan_de_cours", cascade="all, delete-orphan")
    evaluations = db.relationship("PlanDeCoursEvaluations", back_populates="plan_de_cours", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<PlanDeCours id={self.id} session={self.session} pour Cours id={self.cours_id}>"

class PlanDeCoursCalendrier(db.Model):
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
        return f"<PlanDeCoursCalendrier id={self.id}>"

class PlanDeCoursMediagraphie(db.Model):
    __tablename__ = "PlanDeCoursMediagraphie"
    id = db.Column(db.Integer, primary_key=True)
    plan_de_cours_id = db.Column(db.Integer, db.ForeignKey("PlanDeCours.id"), nullable=False)
    reference_bibliographique = db.Column(db.Text, nullable=False)

    plan_de_cours = db.relationship("PlanDeCours", back_populates="mediagraphies")

    def __repr__(self):
        return f"<PlanDeCoursMediagraphie id={self.id}>"

class PlanDeCoursDisponibiliteEnseignant(db.Model):
    __tablename__ = "PlanDeCoursDisponibiliteEnseignant"
    id = db.Column(db.Integer, primary_key=True)
    plan_de_cours_id = db.Column(db.Integer, db.ForeignKey("PlanDeCours.id"), nullable=False)
    jour_semaine = db.Column(db.Text, nullable=True)
    plage_horaire = db.Column(db.Text, nullable=True)
    lieu = db.Column(db.Text, nullable=True)

    plan_de_cours = db.relationship("PlanDeCours", back_populates="disponibilites")

    def __repr__(self):
        return f"<PlanDeCoursDisponibiliteEnseignant id={self.id}>"

class PlanDeCoursEvaluations(db.Model):
    __tablename__ = "PlanDeCoursEvaluations"
    id = db.Column(db.Integer, primary_key=True)
    plan_de_cours_id = db.Column(db.Integer, db.ForeignKey("PlanDeCours.id"), nullable=False)
    titre_evaluation = db.Column(db.Text, nullable=True)
    description = db.Column(db.Text, nullable=True)
    semaine = db.Column(db.Integer, nullable=True)

    plan_de_cours = db.relationship("PlanDeCours", back_populates="evaluations")
    capacites = db.relationship("PlanDeCoursEvaluationsCapacites", back_populates="evaluation", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<PlanDeCoursEvaluations id={self.id}>"

class PlanDeCoursEvaluationsCapacites(db.Model):
    __tablename__ = "PlanDeCoursEvaluationsCapacites"
    id = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(db.Integer, db.ForeignKey("PlanDeCoursEvaluations.id"), nullable=False)
    capacite_id = db.Column(db.Integer, db.ForeignKey("PlanCadreCapacites.id"), nullable=False)
    ponderation = db.Column(db.Text, nullable=True)

    evaluation = db.relationship("PlanDeCoursEvaluations", back_populates="capacites")
    capacite = db.relationship("PlanCadreCapacites")  

    def __repr__(self):
        return f"<PlanDeCoursEvaluationsCapacites id={self.id}>"

# ------------------------------------------------------------------------------
# Autres modèles liés aux départements et programmes
# ------------------------------------------------------------------------------

class Department(db.Model):
    __tablename__ = "Department"
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.Text, nullable=False, unique=True)
    cegep_id = db.Column(db.Integer, nullable=True)

    regles = db.relationship("DepartmentRegles", back_populates="department", cascade="all, delete-orphan")
    piea = db.relationship("DepartmentPIEA", back_populates="department", cascade="all, delete-orphan")
    programmes = db.relationship("Programme", back_populates="department")

    def __repr__(self):
        return f"<Department {self.nom}>"

class DepartmentRegles(db.Model):
    __tablename__ = "DepartmentRegles"
    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(db.Integer, db.ForeignKey("Department.id", ondelete="CASCADE"), nullable=False, index=True)
    regle = db.Column(db.Text, nullable=False)
    contenu = db.Column(db.Text, nullable=False)

    department = db.relationship("Department", back_populates="regles")

    def __repr__(self):
        return f"<DepartmentRegles id={self.id}>"

class DepartmentPIEA(db.Model):
    __tablename__ = "DepartmentPIEA"
    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(db.Integer, db.ForeignKey("Department.id"), nullable=False)
    article = db.Column(db.Text, nullable=False)
    contenu = db.Column(db.Text, nullable=False)

    department = db.relationship("Department", back_populates="piea")

    def __repr__(self):
        return f"<DepartmentPIEA id={self.id}>"

class ListeProgrammeMinisteriel(db.Model):
    __tablename__ = "ListeProgrammeMinisteriel"
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.Text, nullable=False)
    code = db.Column(db.Text, nullable=False)

    # Optionnel : si vous voulez créer une relation bidirectionnelle
    programmes = db.relationship("Programme", back_populates="liste_programme_ministeriel")

    def __repr__(self):
        return f"<ListeProgrammeMinisteriel {self.nom}>"
        
class Programme(db.Model):
    __tablename__ = "Programme"
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.Text, nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("Department.id"), nullable=False)
    # Ajout de la référence à ListeProgrammeMinisteriel
    liste_programme_ministeriel_id = db.Column(db.Integer, db.ForeignKey("ListeProgrammeMinisteriel.id"), nullable=True)
    cegep_id = db.Column(db.Integer, nullable=True)
    variante = db.Column(db.Text, nullable=True)

    # Relations
    cours = db.relationship("Cours", back_populates="programme")
    department = db.relationship("Department", back_populates="programmes")
    liste_programme_ministeriel = db.relationship("ListeProgrammeMinisteriel", back_populates="programmes")

    def __repr__(self):
        return f"<Programme {self.nom}>"

# ------------------------------------------------------------------------------
# Modèle de base pour Cours
# ------------------------------------------------------------------------------

class Cours(db.Model):
    __tablename__ = "Cours"
    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("Programme.id"), nullable=False)
    code = db.Column(db.Text, nullable=False)
    nom = db.Column(db.Text, nullable=False)
    nombre_unites = db.Column(db.Float, nullable=False, default=1.0)
    session = db.Column(db.Integer, nullable=False, default=0)
    heures_theorie = db.Column(db.Integer, nullable=False, default=0)
    heures_laboratoire = db.Column(db.Integer, nullable=False, default=0)
    heures_travail_maison = db.Column(db.Integer, nullable=False, default=0)
    fil_conducteur_id = db.Column(db.Integer, nullable=True)

    programme = db.relationship("Programme", back_populates="cours")
    plan_cadre = db.relationship("PlanCadre", back_populates="cours", uselist=False)
    plans_de_cours = db.relationship("PlanDeCours", back_populates="cours")

    def __repr__(self):
        return f"<Cours {self.code} - {self.nom}>"
