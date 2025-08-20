# forms.py
import re

from flask_login import current_user
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import (
    StringField,
    FormField,
    FloatField,
    SelectField,
    SelectMultipleField,
    IntegerField,
    TextAreaField,
    FieldList,
    Form,
    BooleanField,
    PasswordField,
    HiddenField,
    TimeField,
    DecimalField,
    URLField
)
from wtforms import ValidationError, ColorField, SubmitField
from wtforms import widgets
from wtforms.validators import DataRequired, InputRequired, NumberRange, Optional, Length, EqualTo, Email, URL
from wtforms.widgets import ListWidget, CheckboxInput

from .models import User
from ..utils.openai_pricing import get_all_models

# Liste des régions disponibles
REGIONS = [
    ('Abitibi-Témiscamingue', 'Abitibi-Témiscamingue'),
    ('Bas-Saint-Laurent', 'Bas-Saint-Laurent'),
    ('Capitale-Nationale', 'Capitale-Nationale'),
    ('Centre-du-Québec', 'Centre-du-Québec'),
    ('Chaudière-Appalaches', 'Chaudière-Appalaches'),
    ('Côte-Nord', 'Côte-Nord'),
    ('Estrie', 'Estrie'),
    ('Gaspésie–Îles-de-la-Madeleine', 'Gaspésie–Îles-de-la-Madeleine'),
    ('Lanaudière', 'Lanaudière'),
    ('Laurentides', 'Laurentides'),
    ('Laval', 'Laval'),
    ('Mauricie', 'Mauricie'),
    ('Montérégie', 'Montérégie'),
    ('Montréal', 'Montréal'),
    ('Outaouais', 'Outaouais'),
    ('Saguenay–Lac-Saint-Jean', 'Saguenay–Lac-Saint-Jean'),
    ('À distance', 'À distance')
]



class ConfirmationGrilleForm(FlaskForm):
    """Formulaire pour confirmer l'importation d'une grille de cours."""
    programme_id = SelectField(
        'Programme', 
        validators=[DataRequired()], 
        coerce=int,
        render_kw={"class": "form-select"}
    )
    
    nom_programme = StringField(
        'Nom du programme (tel que détecté dans le PDF)', 
        validators=[DataRequired(), Length(max=255)],
        render_kw={"class": "form-control", "readonly": True}
    )
    
    task_id = HiddenField('ID de la tâche')
    grille_json = HiddenField('JSON de la grille')
    
    confirmer = SubmitField('Confirmer importation', render_kw={"class": "btn btn-success"})
    annuler = SubmitField('Annuler', render_kw={"class": "btn btn-secondary"})


class FileUploadForm(FlaskForm):
    file = FileField("Importez un fichier PDF", validators=[DataRequired()])
    submit = SubmitField("Envoyer")

class AssociateDevisForm(FlaskForm):
    base_filename = HiddenField(validators=[DataRequired()])
    programme_id = SelectField("Choisir le Programme Cible :", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Procéder à la Révision des Compétences")

class ReviewImportConfirmForm(FlaskForm):
    """
    Formulaire soumis depuis la page de révision pour confirmer l'importation
    des compétences ou juste la validation du texte OCR.
    Contient principalement des champs cachés pour passer les informations nécessaires.
    """
    programme_id = HiddenField("ID Programme", validators=[DataRequired()])
    base_filename = HiddenField("Nom de fichier de base", validators=[DataRequired()])
    # Ce champ indiquera si des données structurées étaient présentes lors de l'affichage
    import_structured = HiddenField("Import Structuré Possible") # Pas besoin de validator, on lit juste la valeur 'true'/'false'

    # On peut définir le bouton submit ici ou le mettre directement en HTML
    submit_confirm = SubmitField("Confirmer") # Texte générique, sera ajusté dans le template

    # Note: Pas besoin de champs visibles ici car le but est de confirmer
    # les données déjà affichées sur la page.

class OcrProgrammeSelectionForm(FlaskForm):
    """Formulaire pour sélectionner un secteur et un programme."""
    secteur_url = SelectField('Secteur', choices=[], validators=[DataRequired("Veuillez choisir un secteur.")])
    programme_url = SelectField('Programme', choices=[], validators=[DataRequired("Veuillez choisir un programme.")])
    pdf_title = StringField('Titre (Optionnel - sera remplacé par le nom du programme si laissé vide)',
                            validators=[Optional(), Length(max=150)])
    submit = SubmitField('Démarrer le traitement du devis')

class ForgotPasswordForm(FlaskForm):
    email = StringField('Adresse email', validators=[DataRequired(), Email()])
    recaptcha_token = HiddenField('Recaptcha Token')
    submit = SubmitField("Envoyer l'email de réinitialisation")

class ResetPasswordForm(FlaskForm):
    password = PasswordField('Nouveau mot de passe', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirmez le nouveau mot de passe', validators=[DataRequired(), EqualTo('password')])
    recaptcha_token = HiddenField('Recaptcha Token')
    submit = SubmitField("Réinitialiser le mot de passe")
    
class MailgunConfigForm(FlaskForm):
    mailgun_domain = StringField('Mailgun Domain', validators=[DataRequired()])
    mailgun_api_key = StringField('Mailgun API Key', validators=[DataRequired()])
    submit = SubmitField('Enregistrer')

class OpenAIModelForm(FlaskForm):
    name = StringField("Nom du modèle", validators=[DataRequired()])
    input_price = DecimalField("Prix en input (par token)", validators=[DataRequired(), NumberRange(min=0)])
    output_price = DecimalField("Prix en output (par token)", validators=[DataRequired(), NumberRange(min=0)])
    submit = SubmitField("Ajouter")


class ChatSettingsForm(FlaskForm):
    chat_model = SelectField('Modèle pour le chat', validators=[DataRequired()])
    tool_model = SelectField("Modèle pour l'appel d'outils", validators=[DataRequired()])
    reasoning_effort = SelectField(
        "Effort de raisonnement",
        choices=[
            ('minimal', 'Minimal'),
            ('low', 'Faible'),
            ('medium', 'Moyen'),
            ('high', 'Élevé')
        ],
        default='medium'
    )
    verbosity = SelectField(
        "Verbosité",
        choices=[
            ('low', 'Faible'),
            ('medium', 'Moyenne'),
            ('high', 'Élevée')
        ],
        default='medium'
    )
    submit = SubmitField('Enregistrer')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        models = get_all_models()
        self.chat_model.choices = [(model.name, model.name) for model in models]
        self.tool_model.choices = [(model.name, model.name) for model in models]

class MultiCheckboxField(SelectMultipleField):
    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()

class ProfileEditForm(FlaskForm):
    prenom = StringField('Prénom', validators=[DataRequired(), Length(max=50)])
    nom = StringField('Nom', validators=[DataRequired(), Length(max=50)])
    email = StringField('Email', validators=[
        DataRequired(),
        Email(message='Adresse email invalide.'),
        Length(max=120)
    ])
    image = SelectField('Avatar', choices=[], validators=[DataRequired()])
    cegep = SelectField('Cégep', choices=[''], validators=[Optional()])
    department = SelectField('Département', choices=[''], validators=[Optional()])
    programmes = MultiCheckboxField('Programmes', choices=[], coerce=int)
    submit_profile = SubmitField('Mettre à jour le profil')

    def validate_email(self, email):
        if email.data != current_user.email:
            user = User.query.filter_by(email=email.data).first()
            if user:
                raise ValidationError('Cette adresse email est déjà utilisée.')
    
class UploadForm(FlaskForm):
    file = FileField('Fichier', validators=[DataRequired()])
    submit = SubmitField('Téléverser')

class CegepForm(FlaskForm):
    nom = StringField('Nom du cégep', validators=[DataRequired()])
    type = SelectField('Type', choices=[('Public', 'Public'), ('Privé', 'Privé'), ('À distance', 'À distance')], validators=[DataRequired()])
    region = SelectField('Région', choices=REGIONS, validators=[DataRequired()])
    submit = SubmitField('Ajouter')

class DeletePlanForm(FlaskForm):
    pass  # Aucun champ nécessaire, le jeton CSRF est géré automatiquement
    
class SavoirFaireEntryForm(FlaskForm):
    evaluation_id = HiddenField('ID de l\'Évaluation')
    savoir_faire_id = HiddenField('ID du Savoir-Faire')
    capacite_id = HiddenField('ID de la Capacité')
    savoir_faire_nom = StringField('Savoir-Faire', render_kw={'readonly': True})
    capacite_nom = StringField("Capacité")
    selected = BooleanField('Sélectionné')
    
    level1_description = StringField('Niveau 1 Description', validators=[Optional()])
    level2_description = StringField('Niveau 2 Description', validators=[Optional()])
    level3_description = StringField('Niveau 3 Description', validators=[Optional()])
    level4_description = StringField('Niveau 4 Description', validators=[Optional()])
    level5_description = StringField('Niveau 5 Description', validators=[Optional()])
    level6_description = StringField('Niveau 6 Description', validators=[Optional()])

class SixLevelGridForm(FlaskForm):
    evaluations = FieldList(FormField(SavoirFaireEntryForm), min_entries=0)
    submit = SubmitField('Enregistrer')

class CourseSelectionForm(FlaskForm):
    course = SelectField('Cours', coerce=lambda x: int(x) if x else None)
    submit_course = SubmitField('Sélectionner le Cours')

class PlanSelectionForm(FlaskForm):
    plan = SelectField('Plan', coerce=lambda x: int(x) if x else None)
    submit_plan = SubmitField('Sélectionner le Plan de Cours')

class SavoirFaireCheckboxForm(Form):
    savoir_faire_id = HiddenField('Savoir Faire ID')
    capacite_id = HiddenField('Capacite ID')
    selected = BooleanField('Selected')

class EvaluationForm(FlaskForm):
    evaluation_id = HiddenField('Évaluation ID')
    evaluation_titre = StringField('Titre Évaluation')  # Changer HiddenField en StringField
    savoir_faire = FieldList(FormField(SavoirFaireCheckboxForm))

class EvaluationSelectionForm(FlaskForm):
    evaluation = SelectField('Sélectionner une évaluation', coerce=int)
    description = TextAreaField('Description détaillée de l\'évaluation')

    
class EvaluationGridForm(FlaskForm):
    evaluations = FieldList(FormField(EvaluationForm))
    submit = SubmitField('Enregistrer la Grille d\'Évaluation')

class BackupConfigForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    frequency = SelectField('Frequency', choices=[
        ('daily', 'Quotidien'),
        ('weekly', 'Hebdomadaire'),
        ('monthly', 'Mensuel')
    ])
    backup_time = TimeField('Backup Time', validators=[DataRequired()])
    enabled = BooleanField('Enabled')

class CreditManagementForm(FlaskForm):
    user_id = HiddenField('User ID')
    amount = FloatField('Montant', validators=[
        DataRequired(), 
        NumberRange(min=0.01, message="Le montant doit être supérieur à 0")
    ])
    operation = SelectField('Opération', choices=[
        ('add', 'Ajouter des crédits'),
        ('remove', 'Retirer des crédits')
    ])

class ChatForm(FlaskForm):
    message = StringField('Message', validators=[DataRequired()])
    submit = SubmitField('Envoyer')
    
# Exemple de widget pour le champ multi-select sous forme de cases à cocher
class MultiCheckboxField(SelectMultipleField):
    widget = ListWidget(prefix_label=False)
    option_widget = CheckboxInput()

class EditUserForm(FlaskForm):
    user_id = HiddenField('ID')
    username = StringField("Nom d'utilisateur", validators=[DataRequired()])
    email = StringField("Courriel", validators=[DataRequired(), Email()])
    password = PasswordField("Nouveau mot de passe", validators=[Optional()])
    role = SelectField("Rôle", choices=[('admin', 'Admin'), ('professeur', 'Professeur'), ('cp', 'CP'), ('coordo', 'Coordo'), ('invite', 'Invite')], validators=[DataRequired()])
    cegep_id = SelectField("Cégep", coerce=int, validators=[Optional()])
    department_id = SelectField("Département", coerce=int, validators=[Optional()])
    programmes = MultiCheckboxField("Programmes", coerce=int, default=[])
    openai_key = StringField('Clé API OpenAI')
    submit = SubmitField("Enregistrer les modifications")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.programmes.data is None:
            self.programmes.data = []

    def validate_department_id(self, field):
        if field.data != 0 and self.cegep_id.data == 0:
            raise ValidationError("Vous devez d'abord sélectionner un cégep.")
        if field.data != 0 and field.data not in [c[0] for c in field.choices]:
            field.data = 0  # Reset to "Aucun" if invalid

class CalendrierForm(FlaskForm):
    semaine = IntegerField("Semaine", validators=[Optional()])
    sujet = TextAreaField("Sujet", validators=[Optional()])
    activites = TextAreaField("Activités", validators=[Optional()])
    travaux_hors_classe = TextAreaField("Travaux hors-classe", validators=[Optional()])
    evaluations = TextAreaField("Évaluations", validators=[Optional()])

class MediagraphieForm(FlaskForm):
    reference_bibliographique = TextAreaField("Référence", validators=[DataRequired()])

class DisponibiliteForm(FlaskForm):
    jour_semaine = StringField("Jour", validators=[Optional()])
    plage_horaire = StringField("Plage horaire", validators=[Optional()])
    lieu = StringField("Local/Bureau", validators=[Optional()])

class CapaciteEvaluationForm(FlaskForm):
    """
    Sous-formulaire qui représente la liaison (capacite_id, ponderation)
    pour une évaluation donnée.
    """
    capacite_id = SelectField('Capacité', coerce=int, validators=[Optional()])
    ponderation = StringField("Pondération (ex: 20%)", validators=[Optional()])

class EvaluationPlanCoursForm(FlaskForm):
    titre_evaluation = StringField("Titre de l'évaluation", validators=[Optional()])
    texte_description = TextAreaField("Description", validators=[Optional()])
    semaine = IntegerField("Semaine", validators=[Optional()])

    # Au lieu d'un unique champ "ponderation", on utilise un FieldList de "CapaciteEvaluationForm"
    capacites = FieldList(FormField(CapaciteEvaluationForm), min_entries=0)

class PlanDeCoursForm(FlaskForm):
    # Champs principaux
    campus = StringField("Campus", validators=[Optional()])
    session = StringField("Session", validators=[Optional()])
    presentation_du_cours = TextAreaField("Présentation du cours", validators=[Optional()])
    objectif_terminal_du_cours = TextAreaField("Objectif terminal reformulé", validators=[Optional()])
    organisation_et_methodes = TextAreaField("Organisation du cours et méthodes pédagogiques", validators=[Optional()])
    accomodement = TextAreaField("Accommodement", validators=[Optional()])
    evaluation_formative_apprentissages = TextAreaField("Évaluation formative des apprentissages", validators=[Optional()])
    evaluation_expression_francais = TextAreaField("Évaluation de l’expression en français", validators=[Optional()])
    seuil_reussite = TextAreaField("Seuil de réussite du cours", validators=[Optional()])

    # Informations enseignant
    nom_enseignant = StringField("Nom de l’enseignant", validators=[Optional()])
    telephone_enseignant = StringField("Téléphone de l’enseignant", validators=[Optional()])
    courriel_enseignant = StringField("Courriel de l’enseignant", validators=[Optional()])
    bureau_enseignant = StringField("Bureau de l’enseignant", validators=[Optional()])

    materiel = TextAreaField('Matériel', validators=[Optional()])

    # Listes associées
    calendriers = FieldList(FormField(CalendrierForm), min_entries=0)
    mediagraphies = FieldList(FormField(MediagraphieForm), min_entries=0)
    disponibilites = FieldList(FormField(DisponibiliteForm), min_entries=0)
    evaluations = FieldList(FormField(EvaluationPlanCoursForm), min_entries=0)

    # Bouton de soumission (si besoin)
    submit = SubmitField("Enregistrer")

class AnalysePromptForm(FlaskForm):
    prompt_template = TextAreaField(
        'Template du prompt',
        validators=[DataRequired()],
        render_kw={"rows": 20, "class": "form-control font-monospace"}
    )
    ai_model = SelectField(
        'Modèle d\'IA',
        validators=[DataRequired()],
        default='gpt-5',
        render_kw={"class": "form-control"}
    )
    submit = SubmitField('Sauvegarder', render_kw={"class": "btn btn-primary"})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Récupérer la liste des modèles depuis la base de données
        models = get_all_models()
        # Construire la liste des choix sous forme de tuple (valeur, libellé)
        # Vous pouvez adapter le libellé en fonction de vos besoins (ex: ajouter le tarif)
        self.ai_model.choices = [(model.name, model.name) for model in models]


class PlanDeCoursPromptSettingsForm(FlaskForm):
    prompt_template = TextAreaField(
        'Template du prompt',
        validators=[DataRequired()],
        render_kw={"rows": 20, "class": "form-control font-monospace"}
    )
    ai_model = SelectField(
        'Modèle d\'IA',
        validators=[DataRequired()],
        default='gpt-5',
        render_kw={"class": "form-control"}
    )
    submit = SubmitField('Sauvegarder', render_kw={"class": "btn btn-primary"})

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        models = get_all_models()
        self.ai_model.choices = [(model.name, model.name) for model in models]


class GenerateContentForm(FlaskForm):
    additional_info = TextAreaField('Informations complémentaires', validators=[DataRequired()])
    ai_model = SelectField(
        'Modèle d\'IA',
        validators=[DataRequired()],
        default='gpt-5'
    )
    reasoning_effort = SelectField(
        "Effort de raisonnement",
        choices=[
            ('minimal', 'Minimal'),
            ('low', 'Faible'),
            ('medium', 'Moyen'),
            ('high', 'Élevé')
        ],
        default='medium'
    )
    verbosity = SelectField(
        "Verbosité",
        choices=[
            ('low', 'Faible'),
            ('medium', 'Moyenne'),
            ('high', 'Élevée')
        ],
        default='medium'
    )
    improve_only = BooleanField('Améliorer le contenu existant', default=False)
    submit = SubmitField('Générer le plan-cadre')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        models = get_all_models()
        self.ai_model.choices = [(model.name, model.name) for model in models]

class LoginForm(FlaskForm):
    username = StringField('Nom d\'utilisateur', 
                           validators=[DataRequired(), Length(min=3, max=25)],
                           render_kw={"autocomplete": "username"})
    password = PasswordField('Mot de passe', 
                             validators=[DataRequired(), Length(min=8)],
                             render_kw={"autocomplete": "current-password"})
    recaptcha_token = HiddenField('Recaptcha Token')  # Champ pour le token reCAPTCHA
    submit = SubmitField('Se connecter')
    
class PlanCadreCompetenceCertifieeForm(Form):
    texte = StringField("Texte", validators=[DataRequired()])
    texte_description = TextAreaField("Description", validators=[Optional()])

class PlanCadreCoursCorequisForm(Form):
    texte = StringField("Texte", validators=[DataRequired()])
    texte_description = TextAreaField("Description", validators=[Optional()])

class ImportPlanCadreForm(FlaskForm):
    json_file = FileField('Importer un fichier JSON', validators=[
        FileRequired(message='Veuillez sélectionner un fichier JSON à importer.'),
        FileAllowed(['json'], 'Seuls les fichiers JSON sont autorisés.')
    ])
    submit = SubmitField('Importer JSON')
    
class MultiCheckboxField(SelectMultipleField):
    widget = ListWidget(prefix_label=False)
    option_widget = CheckboxInput()

class CoursPrealableEntryForm(Form):
    class Meta:
        csrf = False
    cours_prealable_id = SelectField('Cours Préalable', coerce=int, validators=[DataRequired()])
    note_necessaire = FloatField('Note Nécessaire', validators=[InputRequired(), NumberRange(min=0, max=100)])

class ProgrammeMinisterielForm(FlaskForm):
    nom = StringField("Nom du programme ministériel", validators=[DataRequired()])
    code = StringField("Code du programme ministériel", validators=[DataRequired()])
    submit = SubmitField("Ajouter")

class ProgrammeForm(FlaskForm):
    nom = StringField("Nom du programme", validators=[DataRequired()])
    # On remplace l'IntegerField par un SelectField pour choisir le département
    department_id = SelectField("Département", coerce=int, validators=[DataRequired()])
    # Pour le programme ministériel, si c'est optionnel, on pourra utiliser Optional()
    liste_programme_ministeriel_id = SelectField("Programme ministériel", coerce=int, validators=[Optional()])
    # Le cégep est également un menu déroulant
    cegep_id = SelectField("Cégep", coerce=int, validators=[DataRequired()])
    variante = StringField("Variante", validators=[Optional()])
    submit = SubmitField("Ajouter le programme")

class CompetenceForm(FlaskForm):
    programmes = SelectMultipleField(
        "Programmes",
        coerce=int,
        validators=[DataRequired()]
    )
    code = StringField('Code', validators=[DataRequired()])
    nom = StringField('Nom', validators=[DataRequired()])
    criteria_de_performance = TextAreaField('Critères de Performance', validators=[Optional()])
    contexte_de_realisation = TextAreaField('Contexte de Réalisation', validators=[Optional()])
    submit = SubmitField('Ajouter/Mettre à Jour Compétence')

class ElementCompetenceForm(FlaskForm):
    competence = SelectField('Compétence', coerce=int, validators=[DataRequired()])
    nom = StringField('Nom', validators=[DataRequired()])
    criteres_de_performance = FieldList(
        TextAreaField('Critère de Performance', validators=[DataRequired()]),
        min_entries=1,
        max_entries=10
    )
    submit = SubmitField('Ajouter Élément de Compétence')

class FilConducteurForm(FlaskForm):
    programme = SelectField('Programme', coerce=int, validators=[DataRequired()])
    description = StringField('Nom du fil', validators=[DataRequired()])
    couleur = ColorField('Couleur', validators=[Optional()])  # Nouveau champ pour la couleur
    submit = SubmitField('Ajouter Fil Conducteur')

class ElementCompetenceStatusForm(Form):
    class Meta:
        csrf = False
    element_competence = SelectField('Élément de Compétence', coerce=int, validators=[DataRequired()])
    status = SelectField('Statut', choices=[
        ('Non traité', 'Non traité'),
        ('Traité superficiellement', 'Traité superficiellement'),
        ('Développé significativement', 'Développé significativement'),
        ('Atteint', 'Atteint'),
        ('Réinvesti', 'Réinvesti')
    ], validators=[DataRequired()])

class CoursForm(FlaskForm):
    # Champ supplémentaire pour l'association à plusieurs programmes. L'utilisateur
    # peut sélectionner un ou plusieurs autres programmes (en plus du programme
    # principal ci-dessus) auxquels le cours sera lié via la relation many-to-many
    # ``Cours.programmes``.
    programmes_associes = SelectMultipleField(
        'Programmes associés',
        coerce=int,
        validators=[Optional()],
        render_kw={"class": "form-select", "multiple": True}
    )
    code = StringField('Code', validators=[DataRequired()])
    nom = StringField('Nom', validators=[DataRequired()])
    heures_theorie = IntegerField('Heures Théorie', validators=[InputRequired(), NumberRange(min=0)])
    heures_laboratoire = IntegerField('Heures Laboratoire', validators=[InputRequired(), NumberRange(min=0)])
    heures_travail_maison = IntegerField('Heures Travail Maison', validators=[InputRequired(), NumberRange(min=0)])
    elements_competence = FieldList(
        FormField(ElementCompetenceStatusForm),
        min_entries=0
    )
    prealables = FieldList(FormField(CoursPrealableEntryForm), min_entries=0)
    corequis = SelectMultipleField('Cours Corequis', coerce=int)
    fil_conducteur = SelectField('Fil Conducteur', coerce=int, choices=[], validators=[Optional()])
    submit = SubmitField('Ajouter/Mettre à Jour Cours')

class CoursPrealableForm(FlaskForm):
    cours = SelectField('Cours', coerce=int, validators=[DataRequired()])
    cours_prealable = SelectField('Cours Préalable', coerce=int, validators=[DataRequired()])
    note_necessaire = FloatField('Note Nécessaire', validators=[DataRequired(), NumberRange(min=0, max=100)])
    submit = SubmitField('Ajouter Cours Préalable')

class CoursCorequisForm(FlaskForm):
    cours = SelectField('Cours', coerce=int, validators=[DataRequired()])
    cours_corequis = SelectField('Cours Corequis', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Ajouter Cours Corequis')

class CompetenceParCoursForm(FlaskForm):
    cours = SelectField('Cours', coerce=int, validators=[DataRequired()])
    competence_developpee = SelectField('Compétence Développée', coerce=int, validators=[DataRequired()])
    competence_atteinte = SelectField('Compétence Atteinte', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Ajouter Compétence par Cours')

class ElementCompetenceParCoursForm(FlaskForm):
    cours = SelectField('Cours', coerce=int, validators=[DataRequired()])
    element_developpe = SelectField('Élément Développé', coerce=int, validators=[DataRequired()])
    element_reinvesti = SelectField('Élément Réinvesti', coerce=int, validators=[DataRequired()])
    element_atteint = SelectField('Élément Atteint', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Ajouter Élément de Compétence par Cours')

class DeleteForm(FlaskForm):
    submit = SubmitField('Supprimer')

class CapaciteSavoirFaireForm(Form):
    class Meta:
        csrf = False
    texte =TextAreaField("Texte", validators=[Optional()])
    cible = TextAreaField("Cible", validators=[Optional()])
    seuil_reussite = TextAreaField("Seuil de réussite", validators=[Optional()])

class MoyenEvaluationFieldForm(Form):
    class Meta:
        csrf = False
    texte = StringField("Moyen d'évaluation", validators=[Optional()])

#class GenerateContentForm(FlaskForm):
#    submit = SubmitField('Générer le Contenu')

class GenerationSettingForm(FlaskForm):
    use_ai = BooleanField('Utiliser l\'IA')
    text_content = TextAreaField('Texte / Prompt', validators=[Optional()])

    class Meta:
        csrf = False  # Assurez-vous que le CSRF est activé

class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Mot de passe actuel', validators=[DataRequired()])
    new_password = PasswordField('Nouveau mot de passe', validators=[
        DataRequired(),
        Length(min=8, message='Le mot de passe doit contenir au moins 8 caractères.')
    ])
    confirm_password = PasswordField('Confirmer le nouveau mot de passe', validators=[
        DataRequired(),
        EqualTo('new_password', message='Les mots de passe doivent correspondre.')
    ])
    submit = SubmitField('Changer de mot de passe')

def password_complexity_check(form, field):
    password = field.data
    if (len(password) < 8 or
        not re.search(r"[A-Z]", password) or
        not re.search(r"[a-z]", password) or
        not re.search(r"[0-9]", password) or
        not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password)):
        raise ValidationError('Le mot de passe doit contenir au moins 8 caractères, incluant une majuscule, une minuscule, un chiffre et un caractère spécial.')

class WelcomeChangePasswordForm(FlaskForm):
    new_password = PasswordField('Nouveau mot de passe', validators=[
        DataRequired(),
        password_complexity_check
    ])
    confirm_password = PasswordField('Confirmer le nouveau mot de passe', validators=[
        DataRequired(),
        EqualTo('new_password', message='Les mots de passe doivent correspondre.')
    ])
    submit_password = SubmitField('Changer de mot de passe')

class CombinedWelcomeForm(ProfileEditForm, WelcomeChangePasswordForm):
    pass

class GlobalGenerationSettingsForm(FlaskForm):
    sections = FieldList(FormField(GenerationSettingForm), min_entries=21, max_entries=21)
    openai_key = StringField('Clé OpenAI', validators=[Optional()])
    submit = SubmitField('Enregistrer les Paramètres')

class CapaciteItemForm(Form):
    class Meta:
        csrf = False
    id = HiddenField('ID')
    capacite = StringField("Capacité", validators=[Optional()])
    description_capacite = TextAreaField("Description", validators=[Optional()])
    ponderation_min = IntegerField("Pondération minimale", validators=[Optional()])
    ponderation_max = IntegerField("Pondération maximale", validators=[Optional()])
    savoirs_necessaires = FieldList(StringField("Savoir nécessaire"), min_entries=0)
    savoirs_faire = FieldList(FormField(CapaciteSavoirFaireForm), min_entries=0)
    moyens_evaluation = FieldList(StringField("Moyen d'évaluation"), min_entries=0)

# Nouveau sous-formulaire avec description
class PlanCadreItemWithDescriptionForm(Form):
    texte = StringField("Texte", validators=[DataRequired()])
    texte_description = TextAreaField("Description", validators=[Optional()])

# Sous-formulaire pour savoir_etre sans description
class PlanCadreTexteFieldForm(Form):
    class Meta:
        csrf = False
    texte = StringField("Texte", validators=[Optional()])  # Changed from DataRequired to Optional


class PlanCadreForm(FlaskForm):
    place_intro = TextAreaField('Introduction Place et Rôle du Cours', validators=[Optional()])
    objectif_terminal = TextAreaField('Objectif Terminal', validators=[Optional()])
    structure_intro = TextAreaField('Introduction Structure du Cours', validators=[Optional()])
    structure_activites_theoriques = TextAreaField('Activités Théoriques', validators=[Optional()])
    structure_activites_pratiques = TextAreaField('Activités Pratiques', validators=[Optional()])
    structure_activites_prevues = TextAreaField('Activités Prévues', validators=[Optional()])
    eval_evaluation_sommative = TextAreaField('Évaluation Sommative des Apprentissages', validators=[Optional()])
    eval_nature_evaluations_sommatives = TextAreaField('Nature des Évaluations Sommatives', validators=[Optional()])
    eval_evaluation_de_la_langue = TextAreaField('Évaluation de la Langue', validators=[Optional()])
    eval_evaluation_sommatives_apprentissages = TextAreaField('Évaluation Sommative des Apprentissages (CKEditor)', validators=[Optional()])

    # Listes dynamiques
    competences_developpees = FieldList(FormField(PlanCadreItemWithDescriptionForm), min_entries=0, max_entries=50)
    objets_cibles = FieldList(FormField(PlanCadreItemWithDescriptionForm), min_entries=0, max_entries=50)
    cours_relies = FieldList(FormField(PlanCadreItemWithDescriptionForm), min_entries=0, max_entries=50)
    cours_prealables = FieldList(FormField(PlanCadreItemWithDescriptionForm), min_entries=0, max_entries=50)
    savoir_etre = FieldList(FormField(PlanCadreTexteFieldForm), min_entries=0)
    competences_certifiees = FieldList(FormField(PlanCadreCompetenceCertifieeForm), min_entries=0, max_entries=50)
    cours_corequis = FieldList(FormField(PlanCadreCoursCorequisForm), min_entries=0, max_entries=50)
    
    capacites = FieldList(FormField(CapaciteItemForm), min_entries=0)

    submit = SubmitField('Ajouter/Mettre à Jour Plan Cadre')

class SavoirEtreForm(FlaskForm):
    texte = TextAreaField('Savoir-être', validators=[DataRequired()])
    submit = SubmitField('Ajouter Savoir-être')

class CompetenceDeveloppeeForm(FlaskForm):
    texte = StringField('Compétence Développée', validators=[DataRequired()])
    submit = SubmitField('Ajouter Compétence Développée')

class ObjetCibleForm(FlaskForm):
    texte = StringField('Objet Cible', validators=[DataRequired()])
    submit = SubmitField('Ajouter Objet Cible')

class CoursRelieForm(FlaskForm):
    texte = StringField('Cours Relié', validators=[DataRequired()])
    submit = SubmitField('Ajouter Cours Relié')

class PlanCadreCoursPrealableForm(FlaskForm):
    texte = StringField('Cours Préalable', validators=[DataRequired()])
    submit = SubmitField('Ajouter Cours Préalable')

class DuplicatePlanCadreForm(FlaskForm):
    new_cours_id = SelectField('Dupliquer vers le Cours', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Dupliquer Plan Cadre')

class CreateUserForm(FlaskForm):
    username = StringField('Nom d\'utilisateur', validators=[DataRequired(), Length(min=3, max=25)])
    password = PasswordField('Mot de passe', validators=[DataRequired(), Length(min=6)])
    role = SelectField('Rôle', choices=[
        ('admin', 'Admin'),
        ('professeur', 'Professeur'),
        ('coordo', 'Coordonnateur'),
        ('cp', 'Conseiller pédagogique')
    ], validators=[DataRequired()])
    submit = SubmitField('Créer')

# forms.py
class DeleteUserForm(FlaskForm):
    user_id = HiddenField(validators=[DataRequired()])
    submit = SubmitField('Supprimer')

class DepartmentForm(FlaskForm):
    nom = StringField("Nom du Département", validators=[DataRequired()])
    # Ajoute le champ cegep_id
    cegep_id = SelectField("Cégep associé", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Ajouter")
    
class DepartmentRegleForm(FlaskForm):
    regle = StringField('Règle', validators=[DataRequired(), Length(max=200)])
    contenu = TextAreaField('Contenu', validators=[DataRequired()])

class DepartmentPIEAForm(FlaskForm):
    article = StringField('Article', validators=[DataRequired(), Length(max=200)])
    contenu = TextAreaField('Contenu', validators=[DataRequired()])

class DeleteForm(FlaskForm):
    """Simple form for CSRF protection on delete operations"""
    pass

class APITokenForm(FlaskForm):
    ttl = IntegerField('Durée de vie (jours)', validators=[Optional()])
    submit = SubmitField('Générer un jeton')

class OcrTriggerForm(FlaskForm):
    pdf_url = URLField('URL du PDF', validators=[DataRequired(), URL()])
    pdf_title = StringField('Titre (Optionnel)', validators=[Optional(), Length(max=100)])
    submit = SubmitField('Démarrer le traitement')
