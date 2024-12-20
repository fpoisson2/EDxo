# forms.py
from flask_wtf import FlaskForm
from wtforms import (
    StringField,
    FormField,
    FloatField,
    SubmitField,
    SelectField,
    SelectMultipleField,
    IntegerField,
    TextAreaField,
    FieldList,
    Form,
    BooleanField
)
from wtforms import ColorField, SubmitField
from wtforms.validators import DataRequired, InputRequired, NumberRange, Optional
from wtforms.widgets import ListWidget, CheckboxInput
from flask_ckeditor import CKEditorField
from flask_wtf.file import FileField, FileAllowed, FileRequired

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

class ProgrammeForm(FlaskForm):
    nom = StringField('Nom', validators=[DataRequired()])
    submit = SubmitField('Ajouter Programme')

class CompetenceForm(FlaskForm):
    programme = SelectField('Programme', coerce=int, validators=[DataRequired()])
    code = StringField('Code', validators=[DataRequired()])
    nom = StringField('Nom', validators=[DataRequired()])
    criteria_de_performance = CKEditorField('Critères de Performance', validators=[DataRequired()])
    contexte_de_realisation = CKEditorField('Contexte de Réalisation', validators=[DataRequired()])
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
    description = StringField('Description', validators=[DataRequired()])
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
    programme = SelectField('Programme', coerce=int, validators=[DataRequired()])
    code = StringField('Code', validators=[DataRequired()])
    nom = StringField('Nom', validators=[DataRequired()])
    session = SelectField('Session', choices=[
        (1, 'Session 1'),
        (2, 'Session 2'),
        (3, 'Session 3'),
        (4, 'Session 4'),
        (5, 'Session 5'),
        (6, 'Session 6')
    ], coerce=int, validators=[DataRequired()])
    heures_theorie = IntegerField('Heures Théorie', validators=[InputRequired(), NumberRange(min=0)])
    heures_laboratoire = IntegerField('Heures Laboratoire', validators=[InputRequired(), NumberRange(min=0)])
    heures_travail_maison = IntegerField('Heures Travail Maison', validators=[InputRequired(), NumberRange(min=0)])
    elements_competence = FieldList(
        FormField(ElementCompetenceStatusForm),
        min_entries=0,
        max_entries=20
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

class SavoirFieldForm(Form):
    class Meta:
        csrf = False
    texte = StringField("Texte", validators=[DataRequired()])
    cible = StringField("Cible", validators=[Optional()])
    seuil_reussite = StringField("Seuil de réussite", validators=[Optional()])

class MoyenEvaluationFieldForm(Form):
    class Meta:
        csrf = False
    texte = StringField("Moyen d'évaluation", validators=[Optional()])

class GenerateContentForm(FlaskForm):
    submit = SubmitField('Générer le Contenu')

class GenerationSettingForm(FlaskForm):
    use_ai = BooleanField('Utiliser l\'IA')
    text_content = TextAreaField('Texte / Prompt', validators=[Optional()])

    class Meta:
        csrf = False  # Assurez-vous que le CSRF est activé

class GlobalGenerationSettingsForm(FlaskForm):
    sections = FieldList(FormField(GenerationSettingForm), min_entries=21, max_entries=21)
    submit = SubmitField('Enregistrer les Paramètres')

class CapaciteForm(FlaskForm):
    capacite = StringField("Capacité", validators=[DataRequired()])
    description_capacite = TextAreaField("Description")
    ponderation_min = IntegerField("Pondération minimale", validators=[DataRequired()])
    ponderation_max = IntegerField("Pondération maximale", validators=[DataRequired()])
    savoirs_necessaires = FieldList(StringField("Texte"), min_entries=0, max_entries=50)
    savoirs_faire = FieldList(FormField(SavoirFieldForm), min_entries=0, max_entries=50)
    moyens_evaluation = FieldList(FormField(MoyenEvaluationFieldForm), min_entries=0, max_entries=50)
    submit = SubmitField("Enregistrer")

# Nouveau sous-formulaire avec description
class PlanCadreItemWithDescriptionForm(Form):
    texte = StringField("Texte", validators=[DataRequired()])
    texte_description = TextAreaField("Description", validators=[Optional()])

# Sous-formulaire pour savoir_etre sans description
class PlanCadreTexteFieldForm(Form):
    class Meta:
        csrf = False
    texte = StringField("Texte", validators=[DataRequired()])

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
    savoir_etre = FieldList(FormField(PlanCadreTexteFieldForm), min_entries=0, max_entries=50)
    competences_certifiees = FieldList(FormField(PlanCadreCompetenceCertifieeForm), min_entries=0, max_entries=50)
    cours_corequis = FieldList(FormField(PlanCadreCoursCorequisForm), min_entries=0, max_entries=50)

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
