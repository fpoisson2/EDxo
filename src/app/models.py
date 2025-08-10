from datetime import datetime

import sys

from flask import current_app
from flask_login import UserMixin
from sqlalchemy import UniqueConstraint, select
from sqlalchemy.ext.hybrid import hybrid_property

from src.extensions import db

# Alias to prevent duplicate imports when modules use ``app.models``
sys.modules.setdefault("app.models", sys.modules[__name__])

# Association table for User-Programme many-to-many relationship
user_programme = db.Table(
    'User_Programme',
    db.Column('user_id', db.Integer, db.ForeignKey('User.id', ondelete='CASCADE'), primary_key=True),
    db.Column('programme_id', db.Integer, db.ForeignKey('Programme.id', ondelete='CASCADE'), primary_key=True),
    extend_existing=True,
)

# Association table for Cours-Programme with per-programme session
cours_programme = db.Table(
    'Cours_Programme',
    db.Column('cours_id', db.Integer, db.ForeignKey('Cours.id', ondelete='CASCADE'), primary_key=True),
    db.Column('programme_id', db.Integer, db.ForeignKey('Programme.id', ondelete='CASCADE'), primary_key=True),
    db.Column('session', db.Integer, nullable=False, default=0),
    extend_existing=True
)

class CoursProgramme(db.Model):
    """Modèle d'association entre Cours et Programme incluant la session."""
    __table__ = cours_programme

    # Relations vers Cours et Programme
    cours = db.relationship('Cours', back_populates='programme_assocs')
    programme = db.relationship('Programme', back_populates='cours_assocs')

competence_programme = db.Table(
    'Competence_Programme',
    db.Column('competence_id', db.Integer, db.ForeignKey('Competence.id', ondelete='CASCADE'), primary_key=True),
    db.Column('programme_id',   db.Integer, db.ForeignKey('Programme.id',    ondelete='CASCADE'), primary_key=True),
    extend_existing=True,
)


class MailgunConfig(db.Model):
    __tablename__ = 'mailgun_config'
    id = db.Column(db.Integer, primary_key=True)
    mailgun_domain = db.Column(db.String(255), nullable=False)
    mailgun_api_key = db.Column(db.String(255), nullable=False)

    def __repr__(self):
        return f"<MailgunConfig domain={self.mailgun_domain}>"

class OpenAIModel(db.Model):
    __tablename__ = 'openai_models'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    input_price = db.Column(db.Float, nullable=False)   # Coût par token en input
    output_price = db.Column(db.Float, nullable=False)  # Coût par token en output

    def __repr__(self):
        return f"<OpenAIModel {self.name}>"


class ChatModelConfig(db.Model):
    __tablename__ = 'chat_model_config'

    id = db.Column(db.Integer, primary_key=True)
    chat_model = db.Column(db.String(64), nullable=False, default='gpt-4.1-mini')
    tool_model = db.Column(db.String(64), nullable=False, default='gpt-4.1-mini')
    reasoning_effort = db.Column(db.String(16))
    verbosity = db.Column(db.String(16))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_current(cls):
        config = cls.query.first()
        if not config:
            config = cls()
            db.session.add(config)
            db.session.commit()
        return config

class AnalysePlanCoursPrompt(db.Model):
    __tablename__ = 'analyse_plan_cours_prompt'
    
    id = db.Column(db.Integer, primary_key=True)
    prompt_template = db.Column(db.Text, nullable=False)
    ai_model = db.Column(
        db.String(50), 
        nullable=False, 
        server_default='gpt-4o'  # Utiliser server_default au lieu de default
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, onupdate=datetime.utcnow)


class PlanDeCoursPromptSettings(db.Model):
    """Modèle pour stocker les configurations de prompts pour chaque champ du plan de cours."""
    id = db.Column(db.Integer, primary_key=True)
    field_name = db.Column(db.String(100), nullable=False, unique=True)
    prompt_template = db.Column(db.Text, nullable=False)
    context_variables = db.Column(db.JSON, default=list)  # Liste des variables contextuelles requises
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<PlanDeCoursPromptSettings {self.field_name}>'
        

class GrillePromptSettings(db.Model):
    """Paramètres pour la génération de grilles d'évaluation"""
    __tablename__ = 'grille_prompt_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    prompt_template = db.Column(db.Text, nullable=False)
    level1_description = db.Column(db.Text, nullable=False)
    level2_description = db.Column(db.Text, nullable=False)
    level3_description = db.Column(db.Text, nullable=False)
    level4_description = db.Column(db.Text, nullable=False)
    level5_description = db.Column(db.Text, nullable=False)
    level6_description = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @classmethod
    def get_current(cls):
        """Récupère les paramètres actuels ou crée une entrée par défaut"""
        settings = cls.query.first()
        if not settings:
            settings = cls(
                prompt_template=(
                    "Tu es un expert en évaluation pédagogique. "
                    "Crée une grille d'évaluation à six niveaux pour le savoir-faire '{savoir_faire}' "
                    "associé à la capacité '{capacite}'.\n\n"
                    "Pour le niveau 4 (seuil de réussite minimum) : {seuil}\n"
                    "Pour le niveau 6 (cible visée) : {cible}\n\n"
                    "Utilise des verbes d'action et assure une progression claire entre les niveaux."
                ),
                level1_description="Niveau 1 - Aucun travail réalisé : Description des comportements observables démontrant l'absence complète de réalisation",
                level2_description="Niveau 2 - Performance très insuffisante : Description des comportements observables démontrant une performance largement sous le seuil minimal attendu",
                level3_description="Niveau 3 - Performance insuffisante : Description des comportements observables démontrant une performance sous le seuil minimal mais en progression par rapport au niveau 2",
                level4_description="Niveau 4 - Seuil de réussite minimal : Description des comportements observables démontrant l'atteinte du seuil minimal de réussite acceptable",
                level5_description="Niveau 5 - Performance supérieure : Description des comportements observables démontrant une performance dépassant le seuil minimal mais n'atteignant pas encore la cible visée",
                level6_description="Niveau 6 - Cible visée atteinte : Description des comportements observables démontrant l'atteinte complète des objectifs avec autonomie"
            )
            db.session.add(settings)
            db.session.commit()
        return settings

class EvaluationSavoirFaire(db.Model):
    __tablename__ = 'evaluation_savoirfaire'
    
    evaluation_id = db.Column(db.Integer, 
                            db.ForeignKey('PlanDeCoursEvaluations.id', 
                                        name='fk_evaluation_savoirfaire_evaluation'), primary_key=True)
    savoir_faire_id = db.Column(db.Integer, 
                               db.ForeignKey('PlanCadreCapaciteSavoirsFaire.id',
                                           name='fk_evaluation_savoirfaire_savoirfaire'), primary_key=True)
    capacite_id = db.Column(db.Integer, 
                          db.ForeignKey('PlanCadreCapacites.id',
                                      name='fk_evaluation_savoirfaire_capacite'))
    selected = db.Column(db.Boolean, default=True)
    
    # Champs pour les six niveaux
    level1_description = db.Column(db.String(255), nullable=True)
    level2_description = db.Column(db.String(255), nullable=True)
    level3_description = db.Column(db.String(255), nullable=True)
    level4_description = db.Column(db.String(255), nullable=True)
    level5_description = db.Column(db.String(255), nullable=True)
    level6_description = db.Column(db.String(255), nullable=True)
    
    __table_args__ = (
        db.PrimaryKeyConstraint('evaluation_id', 'savoir_faire_id', 
                              name='pk_evaluation_savoirfaire'),
    )
    
    evaluation = db.relationship('PlanDeCoursEvaluations', 
                               backref=db.backref('savoir_faire_associations'),
                               foreign_keys=[evaluation_id])
    capacite = db.relationship('PlanCadreCapacites',
                             foreign_keys=[capacite_id])
    savoir_faire = db.relationship('PlanCadreCapaciteSavoirsFaire',
                                 foreign_keys=[savoir_faire_id])
    
    def __repr__(self):
        return f"<EvaluationSavoirFaire evaluation_id={self.evaluation_id}, savoir_faire_id={self.savoir_faire_id}>"



class DBChange(db.Model):
    __tablename__ = "DBChange"
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('User.id', name='fk_dbchange_user_id'))
    operation = db.Column(db.String(10))
    table_name = db.Column(db.String(50))
    record_id = db.Column(db.Integer)
    changes = db.Column(db.JSON)

class BackupConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    frequency = db.Column(db.String(20), nullable=False)
    backup_time = db.Column(db.String(5), nullable=False)  # Format: HH:MM
    enabled = db.Column(db.Boolean, default=False)
    
# ------------------------------------------------------------------------------
# Modèle User (mise à jour pour correspondre au schéma)
# ------------------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "User"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.Text, nullable=False)
    password = db.Column(db.Text, nullable=False)
    last_openai_response_id = db.Column(db.String, nullable=True)
    # Nouveaux champs
    image = db.Column(db.Text, nullable=True)
    nom = db.Column(db.Text, nullable=True)
    prenom = db.Column(db.Text, nullable=True)
    is_first_connexion = db.Column(db.Boolean, nullable=False, server_default='1')  # '1' pour TRUE en SQLite
    # Champs existants
    role = db.Column(db.Text, nullable=False, server_default="invite")
    openai_key = db.Column(db.Text, nullable=True)
    cegep_id = db.Column(db.Integer, db.ForeignKey("ListeCegep.id"), nullable=True)
    department_id = db.Column(db.Integer, db.ForeignKey("Department.id"), nullable=True)
    credits = db.Column(db.Float, nullable=False, default=0.0)
    email = db.Column(db.String(120), nullable=True)
    last_login = db.Column(db.DateTime, nullable=True)

    reset_version = db.Column(db.Integer, default=0)  # Champ pour invalider les anciens tokens

    # Méthode pour générer le token de réinitialisation
    def get_reset_token(self, expires_sec=1800):
        from itsdangerous import URLSafeTimedSerializer
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        token_data = {
            'user_id': self.id,
            'reset_version': self.reset_version
        }
        return s.dumps(token_data, salt='password-reset-salt')

    @staticmethod
    def verify_reset_token(token, expires_sec=1800):
        from itsdangerous import URLSafeTimedSerializer
        s = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token, salt='password-reset-salt', max_age=expires_sec)
            user_id = data.get('user_id')
            token_reset_version = data.get('reset_version')
        except Exception:
            return None
        user = User.query.get(user_id)
        # Vérifier que la version du token correspond à celle de l'utilisateur
        if user and user.reset_version == token_reset_version:
            return user
        return None
    
    __table_args__ = (
        UniqueConstraint('email', name='uq_user_email'),
    )

    # Relations
    programmes = db.relationship('Programme', 
                               secondary=user_programme,
                               backref=db.backref('users', lazy='dynamic'))

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

    programmes = db.relationship(
        'Programme',
        secondary=competence_programme,
        backref=db.backref('competences', lazy='dynamic'),
        lazy='dynamic'
    )    

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

    def to_dict(self):
        return {
            "id": self.id,
            "nom": self.nom,
            "competence_code": self.competence.code if self.competence else ""
        }


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
    # Spécifiez un nom pour la contrainte de clé étrangère
    programme_id = db.Column(db.Integer, db.ForeignKey("Programme.id", name="fk_filconducteur_programme"), nullable=False)
    description = db.Column(db.Text, nullable=False)
    couleur = db.Column(db.Text, nullable=True)

    # Relation vers Programme
    programme = db.relationship("Programme", back_populates="fil_conducteurs")

    # Relationship back to Cours
    cours_list = db.relationship("Cours", back_populates="fil_conducteur")

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
    cours_id = db.Column(db.Integer, db.ForeignKey("Cours.id"), nullable=False)
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
    modified_by_id = db.Column(db.Integer, 
                             db.ForeignKey("User.id", name="fk_plan_cadre_modified_by"),
                             nullable=True)
    modified_at = db.Column(db.DateTime, nullable=True)

    # Relations
    cours = db.relationship("Cours", back_populates="plan_cadre")
    capacites = db.relationship("PlanCadreCapacites", back_populates="plan_cadre", cascade="all, delete-orphan")
    savoirs_etre = db.relationship("PlanCadreSavoirEtre", back_populates="plan_cadre", cascade="all, delete-orphan")

    # Exemple de tables complémentaires (si besoin)
    objets_cibles = db.relationship("PlanCadreObjetsCibles", back_populates="plan_cadre", cascade="all, delete-orphan")
    cours_relies = db.relationship("PlanCadreCoursRelies", back_populates="plan_cadre", cascade="all, delete-orphan")
    cours_prealables = db.relationship("PlanCadreCoursPrealables", back_populates="plan_cadre", cascade="all, delete-orphan")
    cours_corequis = db.relationship("PlanCadreCoursCorequis", back_populates="plan_cadre", cascade="all, delete-orphan")
    competences_certifiees = db.relationship("PlanCadreCompetencesCertifiees", back_populates="plan_cadre", cascade="all, delete-orphan")
    competences_developpees = db.relationship("PlanCadreCompetencesDeveloppees", back_populates="plan_cadre", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<PlanCadre id={self.id} pour Cours id={self.cours_id}>"

    def to_dict(self):
        """
        Convert PlanCadre model instance to a dictionary for JSON serialization.
        Includes all fields and handles nested relationships comprehensively.
        """
        return {
            'id': self.id,
            'cours_id': self.cours_id,
            'place_intro': self.place_intro,
            'objectif_terminal': self.objectif_terminal,
            'structure_intro': self.structure_intro,
            'structure_activites_theoriques': self.structure_activites_theoriques,
            'structure_activites_pratiques': self.structure_activites_pratiques,
            'structure_activites_prevues': self.structure_activites_prevues,
            'eval_evaluation_sommative': self.eval_evaluation_sommative,
            'eval_nature_evaluations_sommatives': self.eval_nature_evaluations_sommatives,
            'eval_evaluation_de_la_langue': self.eval_evaluation_de_la_langue,
            'eval_evaluation_sommatives_apprentissages': self.eval_evaluation_sommatives_apprentissages,
            'additional_info': self.additional_info,
            'ai_model': self.ai_model,
            
            # Cours information
            'cours_info': {
                'id': self.cours.id if self.cours else None,
                'code': self.cours.code if self.cours else None,
                'nom': self.cours.nom if self.cours else None,
                'programme_id': self.cours.programme_id if self.cours else None,
            } if hasattr(self, 'cours') else None,
            
            # Capacités
            'capacites': [
                {
                    'id': capacite.id,
                    'capacite': capacite.capacite,
                    'description_capacite': capacite.description_capacite,
                    'ponderation_min': capacite.ponderation_min,
                    'ponderation_max': capacite.ponderation_max,
                    
                    # Savoirs Nécessaires
                    'savoirs_necessaires': [
                        {'id': sn.id, 'texte': sn.texte} 
                        for sn in capacite.savoirs_necessaires
                    ],
                    
                    # Savoirs Faire
                    'savoirs_faire': [
                        {
                            'id': sf.id, 
                            'texte': sf.texte,
                            'cible': sf.cible,
                            'seuil_reussite': sf.seuil_reussite
                        } 
                        for sf in capacite.savoirs_faire
                    ],
                    
                    # Moyens Evaluation
                    'moyens_evaluation': [
                        {'id': me.id, 'texte': me.texte} 
                        for me in capacite.moyens_evaluation
                    ]
                } 
                for capacite in self.capacites
            ],
            
            # Savoirs Être
            'savoirs_etre': [
                {'id': se.id, 'texte': se.texte} 
                for se in self.savoirs_etre
            ],
            
            # Objets Cibles
            'objets_cibles': [
                {
                    'id': oc.id, 
                    'texte': oc.texte,
                    'description': oc.description
                } 
                for oc in self.objets_cibles
            ],
            
            # Cours Reliés
            'cours_relies': [
                {
                    'id': cr.id, 
                    'texte': cr.texte,
                    'description': cr.description
                } 
                for cr in self.cours_relies
            ],
            
            # Cours Préalables
            'cours_prealables': [
                {
                    'id': cp.id, 
                    'texte': cp.texte,
                    'description': cp.description
                } 
                for cp in self.cours_prealables
            ],
            
            # Cours Corequis
            'cours_corequis': [
                {
                    'id': cc.id, 
                    'texte': cc.texte,
                    'description': cc.description
                } 
                for cc in self.cours_corequis
            ],
            
            # Compétences Certifiées
            'competences_certifiees': [
                {
                    'id': cc.id, 
                    'texte': cc.texte,
                    'description': cc.description
                } 
                for cc in self.competences_certifiees
            ],
            
            # Compétences Développées
            'competences_developpees': [
                {
                    'id': cd.id, 
                    'texte': cd.texte,
                    'description': cd.description
                } 
                for cd in self.competences_developpees
            ]
        }

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

class PlanCadreCoursCorequis(db.Model):
    __tablename__ = "PlanCadreCoursCorequis"
    id = db.Column(db.Integer, primary_key=True)
    plan_cadre_id = db.Column(db.Integer, db.ForeignKey("PlanCadre.id"), nullable=False)
    texte = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text, nullable=True)

    plan_cadre = db.relationship("PlanCadre", back_populates="cours_corequis")

    def __repr__(self):
        return f"<PlanCadreCoursCorequis id={self.id}>"

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
    department_id = db.Column(db.Integer, nullable=True)
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
    compatibility_percentage = db.Column(db.Float, nullable=True)
    recommendation_ameliore = db.Column(db.Text, nullable=True)
    recommendation_plan_cadre = db.Column(db.Text, nullable=True)
    modified_by_id = db.Column(db.Integer, 
                             db.ForeignKey("User.id", name="fk_plan_de_cours_modified_by"),
                             nullable=True)
    modified_at = db.Column(db.DateTime, nullable=True)

    modified_by = db.relationship("User", foreign_keys=[modified_by_id])


    # Relations
    cours = db.relationship("Cours", back_populates="plans_de_cours")
    calendriers = db.relationship("PlanDeCoursCalendrier", back_populates="plan_de_cours", cascade="all, delete-orphan")
    mediagraphies = db.relationship("PlanDeCoursMediagraphie", back_populates="plan_de_cours", cascade="all, delete-orphan")
    disponibilites = db.relationship("PlanDeCoursDisponibiliteEnseignant", back_populates="plan_de_cours", cascade="all, delete-orphan")
    evaluations = db.relationship("PlanDeCoursEvaluations", back_populates="plan_de_cours", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<PlanDeCours id={self.id} session={self.session} pour Cours id={self.cours_id}>"

    def to_dict(self):
        """
        Convert PlanDeCours model instance to a dictionary for JSON serialization.
        Includes the most relevant fields and handles nested relationships.
        """
        return {
            'id': self.id,
            'cours_id': self.cours_id,
            'session': self.session,
            'campus': self.campus,
            'nom_enseignant': self.nom_enseignant,
            'telephone_enseignant': self.telephone_enseignant,
            'courriel_enseignant': self.courriel_enseignant,
            'bureau_enseignant': self.bureau_enseignant,
            'presentation_du_cours': self.presentation_du_cours,
            'objectif_terminal_du_cours': self.objectif_terminal_du_cours,
            'organisation_et_methodes': self.organisation_et_methodes,
            'accomodement': self.accomodement,
            'evaluation_formative_apprentissages': self.evaluation_formative_apprentissages,
            'evaluation_expression_francais': self.evaluation_expression_francais,
            'seuil_reussite': self.seuil_reussite,
            'place_et_role_du_cours': self.place_et_role_du_cours,
            'materiel': self.materiel,
            'compatibility_percentage': self.compatibility_percentage,
            'recommendation_ameliore': self.recommendation_ameliore,
            'recommendation_plan_cadre': self.recommendation_plan_cadre,
            "modified_by": {
                "id": self.modified_by.id,
                "username": self.modified_by.username
            } if self.modified_by else None,
            "modified_at": self.modified_at.isoformat() if self.modified_at else None,
            
            # Optional: Include related course information if needed
            'cours_info': {
                'code': self.cours.code if self.cours else None,
                'nom': self.cours.nom if self.cours else None,
                'programme_id': self.cours.programme_id if self.cours else None,
            } if hasattr(self, 'cours') else None,
            
            # Optional: Include calendar details
            'calendriers': [
                {
                    'semaine': cal.semaine,
                    'sujet': cal.sujet,
                    'activites': cal.activites,
                    'travaux_hors_classe': cal.travaux_hors_classe,
                    'evaluations': cal.evaluations
                } for cal in self.calendriers
            ] if self.calendriers else [],
            
            # Optional: Include mediagraphie
            'mediagraphies': [
                {
                    'reference_bibliographique': media.reference_bibliographique
                } for media in self.mediagraphies
            ] if self.mediagraphies else [],
            
            # Optional: Include disponibilites
            'disponibilites': [
                {
                    'jour_semaine': dispo.jour_semaine,
                    'plage_horaire': dispo.plage_horaire,
                    'lieu': dispo.lieu
                } for dispo in self.disponibilites
            ] if self.disponibilites else [],
            
            # Optional: Include evaluations
            'evaluations': [
                {
                    'titre_evaluation': eval.titre_evaluation,
                    'description': eval.description,
                    'semaine': eval.semaine
                } for eval in self.evaluations
            ] if self.evaluations else []
        }


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

class ChatHistory(db.Model):
    __tablename__ = 'chat_history' # Bonne pratique de définir explicitement

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey('User.id', ondelete='CASCADE', name='fk_chathistory_user_id'),
        nullable=False
    )
    # Rôles possibles: 'user', 'assistant', 'function', 'system'
    role = db.Column(db.String(50), nullable=False)

    # Contenu textuel du message
    content = db.Column(db.Text, nullable=False)

    timestamp = db.Column(db.DateTime, default=datetime.utcnow, server_default=db.func.current_timestamp()) # Amélioré

    # Assurez-vous que le nom de la classe User est correct ('User')
    user = db.relationship('User',
                           backref=db.backref('chat_histories',
                                              lazy=True,
                                              cascade='all, delete-orphan'))

    @classmethod
    def get_recent_history(cls, user_id, limit=10):
        """Récupère les N derniers messages et les retourne dans l'ordre chronologique."""
        recent = cls.query.filter_by(user_id=user_id)\
                          .order_by(cls.timestamp.desc())\
                          .limit(limit)\
                          .all()
        return recent[::-1] # Inverse pour ordre chrono

    def __repr__(self):
        return f'<ChatHistory {self.id} User:{self.user_id} Role:{self.role}>'


class PlanDeCoursMediagraphie(db.Model):
    __tablename__ = "PlanDeCoursMediagraphie"
    id = db.Column(db.Integer, primary_key=True)
    plan_de_cours_id = db.Column(db.Integer, db.ForeignKey("PlanDeCours.id"), nullable=False)
    reference_bibliographique = db.Column(db.Text, nullable=True)

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
    savoir_faire = db.relationship(
        "EvaluationSavoirFaire",
        back_populates="evaluation",
        cascade="all, delete-orphan",
        overlaps="savoir_faire_associations"
    )

    def __repr__(self):
        return f"<PlanDeCoursEvaluations id={self.id}>"

class PlanDeCoursEvaluationsCapacites(db.Model):
    __tablename__ = "PlanDeCoursEvaluationsCapacites"
    id = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(db.Integer, db.ForeignKey("PlanDeCoursEvaluations.id"), nullable=False)
    capacite_id = db.Column(db.Integer, db.ForeignKey("PlanCadreCapacites.id"), nullable=True)
    ponderation = db.Column(db.Text, nullable=True)

    evaluation = db.relationship("PlanDeCoursEvaluations", back_populates="capacites")
    capacite = db.relationship("PlanCadreCapacites", backref="evaluation_capacites")

    def __repr__(self):
        return f"<PlanDeCoursEvaluationsCapacites id={self.id}>"

# ------------------------------------------------------------------------------
# Autres modèles liés aux départements et programmes
# ------------------------------------------------------------------------------

class Department(db.Model):
    __tablename__ = "Department"
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.Text, nullable=False)
    cegep_id = db.Column(db.Integer, db.ForeignKey("ListeCegep.id"), nullable=True)

    # Relations
    regles = db.relationship("DepartmentRegles", back_populates="department", cascade="all, delete-orphan")
    piea = db.relationship("DepartmentPIEA", back_populates="department", cascade="all, delete-orphan")
    programmes = db.relationship("Programme", back_populates="department")
    users = db.relationship('User', backref='department_rel', foreign_keys='User.department_id')


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
    liste_programme_ministeriel_id = db.Column(db.Integer, db.ForeignKey("ListeProgrammeMinisteriel.id"), nullable=True)
    cegep_id = db.Column(db.Integer, db.ForeignKey("ListeCegep.id"), nullable=True)
    variante = db.Column(db.Text, nullable=True)

    # Relations
    fil_conducteurs = db.relationship("FilConducteur", back_populates="programme")
    # Les relations Department et ListeProgrammeMinisteriel demeurent inchangées.
    department = db.relationship("Department", back_populates="programmes")
    liste_programme_ministeriel = db.relationship("ListeProgrammeMinisteriel", back_populates="programmes")

    # ------------------------------------------------------------------
    # Propriété de compatibilité : ``cours``
    # ------------------------------------------------------------------
    # Dans l'ancien schéma, ``programme.cours`` faisait référence à la clé
    # étrangère *programme_id* dans la table *Cours*.  Cette colonne ayant
    # disparu, l'information est maintenant accessible par la relation
    # many-to-many créée comme *backref* de ``Cours.programmes`` (nommée
    # ``cours_associes``).  On expose donc cette dernière sous le nom
    # historique afin d'éviter au reste du code de changer immédiatement.

    # Relation many-to-many vers Cours via la table d'association
    cours_associes = db.relationship(
        'Cours',
        secondary=cours_programme,
        back_populates='programmes',
        lazy='dynamic'
    )
    @property
    def cours(self):
        return list(self.cours_associes)
    
    # Association object pour Cours-Programme, incluant la session par programme
    cours_assocs = db.relationship('CoursProgramme', back_populates='programme', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Programme {self.nom}>"

# ------------------------------------------------------------------------------
# Modèle de base pour Cours
# ------------------------------------------------------------------------------

class Cours(db.Model):
    __tablename__ = "Cours"
    id = db.Column(db.Integer, primary_key=True)
    # L'association à un ou plusieurs programmes se fait désormais **uniquement**
    # via la table d'association ``Cours_Programme`` (relation plusieurs-à-plusieurs).
    # Le champ historique ``programme_id`` – qui implémentait une relation
    # un-à-plusieurs – a été retiré de la base de données.  Le code d'application
    # ne doit donc plus l'utiliser.
    code = db.Column(db.Text, nullable=False)
    nom = db.Column(db.Text, nullable=False)
    nombre_unites = db.Column(db.Float, nullable=False, default=1.0)
    heures_theorie = db.Column(db.Integer, nullable=False, default=0)
    heures_laboratoire = db.Column(db.Integer, nullable=False, default=0)
    heures_travail_maison = db.Column(db.Integer, nullable=False, default=0)

    # Add the missing ForeignKey to FilConducteur:
    fil_conducteur_id = db.Column(db.Integer, db.ForeignKey("FilConducteur.id", name="fk_cours_filconducteur"))

    # Relationship back to FilConducteur
    fil_conducteur = db.relationship("FilConducteur", back_populates="cours_list")

    # Objet d'association Cours ↔ Programme (incluant le champ session)
    programme_assocs = db.relationship(
        'CoursProgramme',
        back_populates='cours',
        cascade='all, delete-orphan'
    )
    # Relation many-to-many vers Programme (facilitant les jointures)
    programmes = db.relationship(
        'Programme',
        secondary=cours_programme,
        back_populates='cours_associes',
        lazy='dynamic'
    )

    plan_cadre = db.relationship("PlanCadre", back_populates="cours", uselist=False)
    plans_de_cours = db.relationship("PlanDeCours", back_populates="cours")

    # ------------------------------------------------------------------
    # Propriété de compatibilité : ``programme_id`` / ``programme``
    # ------------------------------------------------------------------
    # De nombreuses parties du code historique font toujours référence au
    # champ ``programme_id`` ou à l'attribut ``programme`` sur un objet
    # Cours.  Pour éviter de casser l'application en attendant la mise à
    # jour complète du code, on expose une propriété Python éponyme qui
    # renvoie l'identifiant (resp. l'instance) du *premier* programme
    # associé via la relation plusieurs-à-plusieurs.  Aucune colonne n'est
    # cependant créée dans la base de données.

    @property
    def programme(self):
        """Retourne le premier programme associé (héritage historique)."""
        # Retourne le premier élément de la liste, ou None si inexistante
        return self.programmes[0] if self.programmes else None

    @hybrid_property
    def programme_id(self):
        """Identifiant du *premier* programme associé (propriété legacy).

        Permet également les filtres au niveau SQL (via la partie expression)
        pour conserver la compatibilité du code existant qui exécute par
        exemple ``Cours.query.filter_by(programme_id=...)``.
        """
        prog = self.programme
        return prog.id if prog else None

    @programme_id.expression
    def programme_id(cls):  # pylint: disable=no-self-argument
        return (
            select(cours_programme.c.programme_id)
            .where(cours_programme.c.cours_id == cls.id)
            .limit(1)
            .scalar_subquery()
        )

    def __repr__(self):
        return f"<Cours {self.code} - {self.nom}>"
    
    @property
    def sessions_map(self):
        """Retourne un dict mapping programme_id -> session pour ce cours."""
        return {assoc.programme_id: assoc.session for assoc in getattr(self, 'programme_assocs', [])}

class ListeCegep(db.Model):
    __tablename__ = "ListeCegep"
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.Text, nullable=False)
    type = db.Column(db.Text, nullable=False, server_default="'Public'")
    region = db.Column(db.Text, nullable=False, server_default="'Capitale-Nationale'")

    # Relations avec les clés étrangères explicites
    users = db.relationship('User', backref='cegep', foreign_keys='User.cegep_id')
    departments = db.relationship('Department', backref='cegep', foreign_keys='Department.cegep_id')
    programmes = db.relationship('Programme', backref='cegep', foreign_keys='Programme.cegep_id')

    def __repr__(self):
        return f"<ListeCegep {self.nom}>"

class GlobalGenerationSettings(db.Model):
    __tablename__ = "GlobalGenerationSettings"
    id = db.Column(db.Integer, primary_key=True)
    section = db.Column(db.Text, nullable=False)
    use_ai = db.Column(db.Boolean, nullable=False, server_default="0")
    text_content = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<GlobalGenerationSettings {self.section}>"

