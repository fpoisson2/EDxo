# app.py
from flask import Blueprint, Flask, render_template, redirect, url_for, request, flash, send_file, jsonify

from forms import (
    ProgrammeForm,
    CompetenceForm,
    ElementCompetenceForm,
    FilConducteurForm,
    CoursForm,
    CoursPrealableForm,
    CoursCorequisForm,
    CompetenceParCoursForm,
    ElementCompetenceParCoursForm,
    DeleteForm,
    MultiCheckboxField,
    PlanCadreForm,
    CapaciteForm,
    SavoirEtreForm,
    CompetenceDeveloppeeForm,
    ObjetCibleForm,
    CoursRelieForm,
    CoursPrealableForm,
    DuplicatePlanCadreForm,
    ImportPlanCadreForm,
    PlanCadreCompetenceCertifieeForm,
    PlanCadreCoursCorequisForm,
    GenerateContentForm,
    GlobalGenerationSettingsForm, 
    GenerationSettingForm,
    ChangePasswordForm,
    LoginForm
)
from flask_ckeditor import CKEditor
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import sqlite3
import json
from decorator import role_required, roles_required
import logging
from collections import defaultdict
from openai import OpenAI
from openai import OpenAIError
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import os
import markdown
from jinja2 import Template
import bleach
from docxtpl import DocxTemplate
from io import BytesIO 
from werkzeug.security import generate_password_hash, check_password_hash
from utils import get_db_connection, parse_html_to_list, parse_html_to_nested_list, get_plan_cadre_data, replace_tags_jinja2, process_ai_prompt, generate_docx_with_template
from models import User



main = Blueprint('main', __name__)

# Define the markdown filter
@main.app_template_filter('markdown')
def markdown_filter(text):
    return markdown.markdown(text)


@main.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))  # Redirigez vers une page appropriée si déjà connecté

    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data
        password = form.password.data

        conn = get_db_connection()
        user_row = conn.execute('SELECT * FROM User WHERE username = ?', (username,)).fetchone()
        conn.close()

        if user_row and check_password_hash(user_row['password'], password):
            user = User(id=user_row['id'], username=user_row['username'], password=user_row['password'], role=user_row['role'])
            login_user(user)
            flash('Connexion réussie !', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.index'))
        else:
            flash('Nom d\'utilisateur ou mot de passe incorrect.', 'danger')

    return render_template('login.html', form=form)


# Route pour la déconnexion
@main.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Déconnexion réussie.', 'success')
    return redirect(url_for('main.login'))

@main.route('/manage_users', methods=['GET', 'POST'])
@role_required('admin')
def manage_users():
    if current_user.role != 'admin':  # Vérifiez que seul l'admin a accès
        flash('Accès interdit.', 'danger')
        return redirect(url_for('settings.parametres'))

    conn = get_db_connection()
    users = conn.execute('SELECT * FROM User').fetchall()
    conn.close()

    if request.method == 'POST':
        if 'create_user' in request.form:
            username = request.form.get('username')
            password = request.form.get('password')
            role = request.form.get('role')

            # Vérification des champs
            if not username or not password or not role:
                flash('Tous les champs sont requis pour créer un utilisateur.', 'warning')
                return redirect(url_for('main.manage_users'))

            hashed_password = generate_password_hash(password, method='scrypt')
            try:
                conn = get_db_connection()
                conn.execute(
                    'INSERT INTO User (username, password, role) VALUES (?, ?, ?)',
                    (username, hashed_password, role)
                )
                conn.commit()
                flash('Utilisateur créé avec succès.', 'success')
            except Exception as e:
                flash(f'Erreur lors de la création : {e}', 'danger')
            finally:
                conn.close()
            return redirect(url_for('main.manage_users'))

        elif 'delete_user' in request.form:
            user_id = request.form.get('user_id')

            # Empêcher la suppression de l'utilisateur actuel
            if str(user_id) == str(current_user.id):
                flash('Vous ne pouvez pas supprimer votre propre compte.', 'danger')
                return redirect(url_for('main.manage_users'))

            # Optionnel : Empêcher la suppression des comptes administrateurs (sauf si vous le souhaitez)
            # user_to_delete = conn.execute('SELECT * FROM User WHERE id = ?', (user_id,)).fetchone()
            # if user_to_delete and user_to_delete['role'] == 'admin':
            #     flash('Vous ne pouvez pas supprimer un compte administrateur.', 'danger')
            #     return redirect(url_for('main.manage_users'))

            try:
                conn = get_db_connection()
                conn.execute('DELETE FROM User WHERE id = ?', (user_id,))
                conn.commit()
                flash('Utilisateur supprimé avec succès.', 'success')
            except Exception as e:
                flash(f'Erreur lors de la suppression : {e}', 'danger')
            finally:
                conn.close()
            return redirect(url_for('main.manage_users'))

    return render_template('manage_users.html', users=users, current_user_id=current_user.id)
@main.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        current_password = form.current_password.data
        new_password = form.new_password.data

        # Vérifier le mot de passe actuel
        if not check_password_hash(current_user.password, current_password):
            flash('Mot de passe actuel incorrect.', 'danger')
            return redirect(url_for('main.change_password'))

        # Générer le nouveau mot de passe haché
        hashed_new_password = generate_password_hash(new_password, method='scrypt')

        # Mettre à jour le mot de passe dans la base de données
        try:
            conn = get_db_connection()
            conn.execute('UPDATE User SET password = ? WHERE id = ?', (hashed_new_password, current_user.id))
            conn.commit()
            flash('Votre mot de passe a été mis à jour avec succès.', 'success')
            return redirect(url_for('main.profile'))  # Remplacez 'profile' par la route souhaitée
        except Exception as e:
            flash(f'Erreur lors de la mise à jour du mot de passe : {e}', 'danger')
            return redirect(url_for('main.change_password'))
        finally:
            conn.close()

    return render_template('change_password.html', form=form)

@main.route('/')
@login_required
def index():
    conn = get_db_connection()
    programmes = conn.execute('SELECT * FROM Programme').fetchall()
    conn.close()
    
    if programmes:
        # Sélectionner le premier programme comme défaut
        default_programme_id = programmes[0]['id']  # Assurez-vous que 'id' est la clé correcte
        return redirect(url_for('programme.view_programme', programme_id=default_programme_id))
    else:
        # Si aucun programme n'existe, rediriger vers la page d'ajout
        flash('Aucun programme trouvé. Veuillez en ajouter un.', 'warning')
        return redirect(url_for('main.add_programme'))

@main.route('/add_programme', methods=('GET', 'POST'))
@role_required('admin')
def add_programme():
    form = ProgrammeForm()
    if form.validate_on_submit():
        nom = form.nom.data
        conn = get_db_connection()
        conn.execute('INSERT INTO Programme (nom) VALUES (?)', (nom,))
        conn.commit()
        conn.close()
        flash('Programme ajouté avec succès!')
        return redirect(url_for('main.index'))
    return render_template('add_programme.html', form=form)

# --------------------- Competence Routes ---------------------
@main.route('/add_competence', methods=['GET', 'POST'])
@role_required('admin')
def add_competence():
    form = CompetenceForm()
    conn = get_db_connection()
    programmes = conn.execute('SELECT id, nom FROM Programme').fetchall()
    conn.close()
    form.programme.choices = [(p['id'], p['nom']) for p in programmes]

    if form.validate_on_submit():
        programme_id = form.programme.data
        code = form.code.data
        nom = form.nom.data
        criteria_de_performance = form.criteria_de_performance.data or ""
        contexte_de_realisation = form.contexte_de_realisation.data or ""

        # Nettoyer le contenu avant de l'enregistrer
        allowed_tags = [
            'ul', 'ol', 'li', 'strong', 'em', 'p', 'br', 'a', 
            'h1', 'h2', 'h3', 'h4', 'h5', 'h6'
        ]
        allowed_attributes = {'a': ['href', 'title', 'target']}

        criteria_clean = bleach.clean(
            criteria_de_performance,
            tags=allowed_tags,
            attributes=allowed_attributes,
            strip=True
        )
        context_clean = bleach.clean(
            contexte_de_realisation,
            tags=allowed_tags,
            attributes=allowed_attributes,
            strip=True
        )

        try:
            conn = get_db_connection()
            conn.execute('''
                INSERT INTO Competence (programme_id, code, nom, criteria_de_performance, contexte_de_realisation)
                VALUES (?, ?, ?, ?, ?)
            ''', (programme_id, code, nom, criteria_clean, context_clean))
            conn.commit()
            conn.close()
            flash('Compétence ajoutée avec succès!', 'success')
            return redirect(url_for('programme.view_programme', programme_id=programme_id))
        except sqlite3.Error as e:
            flash(f'Erreur lors de l\'ajout de la compétence : {e}', 'danger')
            return redirect(url_for('main.add_competence'))

    return render_template('add_competence.html', form=form)

# --------------------- ElementCompetence Routes ---------------------

@main.route('/add_element_competence', methods=('GET', 'POST'))
@role_required('admin')
def add_element_competence():
    form = ElementCompetenceForm()
    conn = get_db_connection()
    competences = conn.execute('SELECT id, nom FROM Competence').fetchall()
    conn.close()
    form.competence.choices = [(c['id'], c['nom']) for c in competences]

    if form.validate_on_submit():
        competence_id = form.competence.data
        nom = form.nom.data
        criteres = form.criteres_de_performance.data  # Liste des critères

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            # Insérer l'Élément de Compétence
            cursor.execute('INSERT INTO ElementCompetence (competence_id, nom) VALUES (?, ?)', (competence_id, nom))
            element_competence_id = cursor.lastrowid

            # Insérer chaque critère de performance
            for crit in criteres:
                cursor.execute('INSERT INTO ElementCompetenceCriteria (element_competence_id, criteria) VALUES (?, ?)', (element_competence_id, crit))

            conn.commit()
            flash('Élément de compétence et critères de performance ajoutés avec succès!', 'success')
            return redirect(url_for('programme.view_programme', programme_id=get_programme_id(conn, competence_id)))
        except sqlite3.Error as e:
            conn.rollback()
            flash(f'Erreur lors de l\'ajout de l\'élément de compétence : {e}', 'danger')
        finally:
            conn.close()
    return render_template('add_element_competence.html', form=form)


@main.route('/add_fil_conducteur', methods=('GET', 'POST'))
@role_required('admin')
def add_fil_conducteur():
    form = FilConducteurForm()
    conn = get_db_connection()
    programmes = conn.execute('SELECT id, nom FROM Programme').fetchall()
    conn.close()
    form.programme.choices = [(p['id'], p['nom']) for p in programmes]

    if form.validate_on_submit():
        programme_id = form.programme.data
        description = form.description.data
        couleur = form.couleur.data or '#FFFFFF'  # Utiliser blanc par défaut si aucune couleur spécifiée

        conn = get_db_connection()
        conn.execute('INSERT INTO FilConducteur (programme_id, description, couleur) VALUES (?, ?, ?)', (programme_id, description, couleur))
        conn.commit()
        conn.close()
        flash('Fil conducteur ajouté avec succès!')
        return redirect(url_for('programme.view_programme', programme_id=programme_id))

    return render_template('add_fil_conducteur.html', form=form)



@main.route('/add_cours', methods=('GET', 'POST'))
@role_required('admin')
def add_cours():
    form = CoursForm()
    conn = get_db_connection()
    
    # Récupérer les programmes et éléments de compétence pour les choix des champs
    programmes = conn.execute('SELECT id, nom FROM Programme').fetchall()
    elements_competence_rows = conn.execute('SELECT id, nom FROM ElementCompetence').fetchall()
    elements_competence = [dict(row) for row in elements_competence_rows]
    conn.close()
    
    form.programme.choices = [(p['id'], p['nom']) for p in programmes]
    
    # Récupérer les éléments de compétence et les passer au formulaire
    for subform in form.elements_competence:
        subform.element_competence.choices = [(e['id'], e['nom']) for e in elements_competence]
    
    if form.validate_on_submit():
        programme_id = form.programme.data
        code = form.code.data
        nom = form.nom.data
        session = form.session.data
        heures_theorie = form.heures_theorie.data
        heures_laboratoire = form.heures_laboratoire.data
        heures_travail_maison = form.heures_travail_maison.data
        nombre_unites = (heures_theorie + heures_laboratoire + heures_travail_maison)/3
        
        elements_competence_data = form.elements_competence.data or []
    
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Insérer le cours dans la table Cours
            cursor.execute('''
                INSERT INTO Cours 
                (programme_id, code, nom, nombre_unites, session, heures_theorie, heures_laboratoire, heures_travail_maison)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (programme_id, code, nom, nombre_unites, session, heures_theorie, heures_laboratoire, heures_travail_maison))
            conn.commit()
            cours_id = cursor.lastrowid  # Récupérer l'ID du cours nouvellement créé
    
            # Insérer les relations ElementCompetenceParCours avec statut
            for ec in elements_competence_data:
                element_id = ec.get('element_competence')
                status = ec.get('status')
                if element_id and status:
                    cursor.execute('''
                        INSERT INTO ElementCompetenceParCours (cours_id, element_competence_id, status)
                        VALUES (?, ?, ?)
                    ''', (cours_id, element_id, status))
                else:
                    flash('Chaque élément de compétence doit avoir un élément sélectionné et un statut.', 'warning')
            
            conn.commit()
            conn.close()
            flash('Cours ajouté avec succès!', 'success')
            return redirect(url_for('programme.view_programme', programme_id=programme_id))
        except sqlite3.IntegrityError as e:
            flash(f'Erreur d\'intégrité de la base de données : {e}', 'danger')
            return redirect(url_for('main.add_cours'))
        except sqlite3.Error as e:
            flash(f'Erreur lors de l\'ajout du cours : {e}', 'danger')
            return redirect(url_for('main.add_cours'))
    
    # Afficher les erreurs du formulaire si validation échoue
    elif request.method == 'POST':
        if form.errors:
            for field, errors in form.errors.items():
                for error in errors:
                    flash(f'Erreur dans le champ "{getattr(form, field).label.text}": {error}', 'danger')
    
    return render_template('add_cours.html', form=form, elements_competence=elements_competence)


# --------------------- CoursPrealable Routes ---------------------

@main.route('/add_cours_prealable', methods=('GET', 'POST'))
@role_required('admin')
def add_cours_prealable():
    form = CoursPrealableForm()
    conn = get_db_connection()
    cours = conn.execute('SELECT id, nom FROM Cours').fetchall()
    conn.close()
    form.cours.choices = [(c['id'], c['nom']) for c in cours]
    form.cours_prealable.choices = [(c['id'], c['nom']) for c in cours]

    if form.validate_on_submit():
        cours_id = form.cours.data
        cours_prealable_id = form.cours_prealable.data
        note_necessaire = form.note_necessaire.data
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO CoursPrealable (cours_id, cours_prealable_id, note_necessaire)
            VALUES (?, ?, ?)
        ''', (cours_id, cours_prealable_id, note_necessaire))
        conn.commit()
        conn.close()
        flash('Cours préalable ajouté avec succès!')
        return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))
    return render_template('add_cours_prealable.html', form=form)

# --------------------- CoursCorequis Routes ---------------------

@main.route('/add_cours_corequis', methods=('GET', 'POST'))
@role_required('admin')
def add_cours_corequis():
    form = CoursCorequisForm()
    conn = get_db_connection()
    cours = conn.execute('SELECT id, nom FROM Cours').fetchall()
    conn.close()
    form.cours.choices = [(c['id'], c['nom']) for c in cours]
    form.cours_corequis.choices = [(c['id'], c['nom']) for c in cours]

    if form.validate_on_submit():
        cours_id = form.cours.data
        cours_corequis_id = form.cours_corequis.data
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO CoursCorequis (cours_id, cours_corequis_id)
            VALUES (?, ?)
        ''', (cours_id, cours_corequis_id))
        conn.commit()
        conn.close()
        flash('Cours corequis ajouté avec succès!')
        return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))
    return render_template('add_cours_corequis.html', form=form)

# --------------------- CompetenceParCours Routes ---------------------

@main.route('/add_competence_par_cours', methods=('GET', 'POST'))
@role_required('admin')
def add_competence_par_cours():
    form = CompetenceParCoursForm()
    conn = get_db_connection()
    cours = conn.execute('SELECT id, nom FROM Cours').fetchall()
    competences = conn.execute('SELECT id, nom FROM Competence').fetchall()
    conn.close()
    form.cours.choices = [(c['id'], c['nom']) for c in cours]
    form.competence_developpee.choices = [(c['id'], c['nom']) for c in competences]
    form.competence_atteinte.choices = [(c['id'], c['nom']) for c in competences]

    if form.validate_on_submit():
        cours_id = form.cours.data
        competence_developpee_id = form.competence_developpee.data
        competence_atteinte_id = form.competence_atteinte.data
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO CompetenceParCours (cours_id, competence_developpee_id, competence_atteinte_id)
            VALUES (?, ?, ?)
        ''', (cours_id, competence_developpee_id, competence_atteinte_id))
        conn.commit()
        conn.close()
        flash('Relation Compétence par Cours ajoutée avec succès!')
        return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))
    return render_template('add_competence_par_cours.html', form=form)

# --------------------- ElementCompetenceParCours Routes ---------------------

@main.route('/add_element_competence_par_cours', methods=('GET', 'POST'))
@role_required('admin')
def add_element_competence_par_cours():
    form = ElementCompetenceParCoursForm()
    conn = get_db_connection()
    cours = conn.execute('SELECT id, nom FROM Cours').fetchall()
    elements = conn.execute('SELECT id, nom FROM ElementCompetence').fetchall()
    conn.close()
    form.cours.choices = [(c['id'], c['nom']) for c in cours]
    form.element_developpe.choices = [(e['id'], e['nom']) for e in elements]
    form.element_reinvesti.choices = [(e['id'], e['nom']) for e in elements]
    form.element_atteint.choices = [(e['id'], e['nom']) for e in elements]

    if form.validate_on_submit():
        cours_id = form.cours.data
        element_developpe_id = form.element_developpe.data
        element_reinvesti_id = form.element_reinvesti.data
        element_atteint_id = form.element_atteint.data
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO ElementCompetenceParCours 
            (cours_id, element_developpe_id, element_reinvesti_id, element_atteint_id)
            VALUES (?, ?, ?, ?)
        ''', (cours_id, element_developpe_id, element_reinvesti_id, element_atteint_id))
        conn.commit()
        conn.close()
        flash('Relation Élément de Compétence par Cours ajoutée avec succès!')
        return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))
    return render_template('add_element_competence_par_cours.html', form=form)


@main.route('/element_competence/<int:element_id>/edit', methods=['GET', 'POST'])
@role_required('admin')
def edit_element_competence(element_id):
    conn = get_db_connection()
    element = conn.execute('SELECT * FROM ElementCompetence WHERE id = ?', (element_id,)).fetchone()
    if element is None:
        flash('Élément de compétence non trouvé.', 'danger')
        conn.close()
        return redirect(url_for('main.index'))

    # Récupérer les compétences pour le choix du champ competence
    competences = conn.execute('SELECT id, nom FROM Competence').fetchall()
    conn.close()

    form = ElementCompetenceForm()
    form.competence.choices = [(c['id'], c['nom']) for c in competences]

    # Pré-remplir le formulaire s'il s'agit d'une requête GET
    if request.method == 'GET':
        form.competence.data = element['competence_id']
        form.nom.data = element['nom']

        # Récupérer les critères pour cet élément
        conn = get_db_connection()
        criteres_rows = conn.execute('SELECT criteria FROM ElementCompetenceCriteria WHERE element_competence_id = ?', (element_id,)).fetchall()
        conn.close()

        form.criteres_de_performance.entries = []
        for critere in criteres_rows:
            form.criteres_de_performance.append_entry(critere['criteria'])

    if form.validate_on_submit():
        competence_id = form.competence.data
        nom = form.nom.data
        criteres_data = form.criteres_de_performance.data

        # Mettre à jour l'élément de compétence
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE ElementCompetence SET competence_id = ?, nom = ? WHERE id = ?', (competence_id, nom, element_id))

        # Supprimer les anciens critères
        cursor.execute('DELETE FROM ElementCompetenceCriteria WHERE element_competence_id = ?', (element_id,))

        # Insérer les nouveaux critères
        for crit in criteres_data:
            if crit.strip():
                cursor.execute('INSERT INTO ElementCompetenceCriteria (element_competence_id, criteria) VALUES (?, ?)', (element_id, crit.strip()))

        conn.commit()
        conn.close()

        flash('Élément de compétence mis à jour avec succès!', 'success')
        return redirect(url_for('programme.view_competence', competence_id=competence_id))

    return render_template('edit_element_competence.html', form=form)

@main.route('/edit_cours/<int:cours_id>', methods=('GET', 'POST'))
@role_required('admin')
def edit_cours(cours_id):
    conn = get_db_connection()
    cours = conn.execute('SELECT * FROM Cours WHERE id = ?', (cours_id,)).fetchone()
    if cours is None:
        conn.close()
        flash('Cours non trouvé.', 'danger')
        return redirect(url_for('main.index'))

    # Récupérer tous les cours pour préalables et corequis
    all_cours = conn.execute('SELECT id, nom FROM Cours WHERE id != ?', (cours_id,)).fetchall()
    cours_choices = [(c['id'], c['nom']) for c in all_cours]

    # Récupérer les préalables existants
    prealables_rows = conn.execute('SELECT cours_prealable_id, note_necessaire FROM CoursPrealable WHERE cours_id = ?', (cours_id,)).fetchall()
    prealables_existants = [{'id': p['cours_prealable_id'], 'note': p['note_necessaire']} for p in prealables_rows]

    # Récupérer les corequis existants
    corequis_rows = conn.execute('SELECT cours_corequis_id FROM CoursCorequis WHERE cours_id = ?', (cours_id,)).fetchall()
    corequis_existants = [c['cours_corequis_id'] for c in corequis_rows]

    # Récupérer les éléments de compétence
    elements_competence_rows = conn.execute('SELECT id, nom FROM ElementCompetence').fetchall()
    elements_competence = [dict(row) for row in elements_competence_rows]

    ec_assoc_rows = conn.execute('SELECT element_competence_id, status FROM ElementCompetenceParCours WHERE cours_id = ?', (cours_id,)).fetchall()
    ec_assoc = [dict(row) for row in ec_assoc_rows]

    programmes_rows = conn.execute('SELECT id, nom FROM Programme').fetchall()
    programmes = [dict(row) for row in programmes_rows]

    # Récupérer les fils conducteurs
    fils_conducteurs_rows = conn.execute('SELECT id, description FROM FilConducteur').fetchall()
    fils_conducteurs = [(fc['id'], fc['description']) for fc in fils_conducteurs_rows]

    conn.close()

    form = CoursForm()
    form.programme.choices = [(p['id'], p['nom']) for p in programmes]
    ec_choices = [(e['id'], e['nom']) for e in elements_competence]

    # Définir les choix pour corequis et fils conducteurs
    form.corequis.choices = cours_choices
    form.fil_conducteur.choices = fils_conducteurs  # Ajouter les fils conducteurs ici

    if request.method == 'GET':
        # Pré-remplir le formulaire
        form.programme.data = cours['programme_id']
        form.code.data = cours['code']
        form.nom.data = cours['nom']
        form.session.data = cours['session']
        form.heures_theorie.data = cours['heures_theorie']
        form.heures_laboratoire.data = cours['heures_laboratoire']
        form.heures_travail_maison.data = cours['heures_travail_maison']
        form.corequis.data = corequis_existants

        # Pré-remplir le fil conducteur (s'il est associé au cours)
        if 'fil_conducteur_id' in cours:
            form.fil_conducteur.data = cours['fil_conducteur_id']
        else:
            form.fil_conducteur.data = None  # Ou une autre valeur par défaut
        # Vider les entrées existantes d'éléments de compétence
        form.elements_competence.entries = []
        for ec in ec_assoc:
            subform = form.elements_competence.append_entry()
            subform.element_competence.choices = ec_choices
            subform.element_competence.data = ec['element_competence_id']
            subform.status.data = ec['status']

        if not ec_assoc:
            subform = form.elements_competence.append_entry()
            subform.element_competence.choices = ec_choices
            subform.element_competence.data = None
            subform.status.data = None

        # Pré-remplir les préalables avec note
        form.prealables.entries = []  # Au cas où
        for p in prealables_existants:
            p_subform = form.prealables.append_entry()
            p_subform.cours_prealable_id.choices = cours_choices
            p_subform.cours_prealable_id.data = p['id']
            p_subform.note_necessaire.data = p['note']

    else:
        # Pour les POST, redéfinir les choices
        for subform in form.elements_competence:
            subform.element_competence.choices = ec_choices
        
        for p_subform in form.prealables:
            p_subform.cours_prealable_id.choices = cours_choices

    if form.validate_on_submit():
        # Récupérer les données
        programme_id = form.programme.data
        code = form.code.data
        nom = form.nom.data
        session_num = form.session.data
        heures_theorie = form.heures_theorie.data
        heures_laboratoire = form.heures_laboratoire.data
        heures_travail_maison = form.heures_travail_maison.data
        fil_conducteur_id = form.fil_conducteur.data  # Récupérer le fil conducteur sélectionné

        elements_competence_data = form.elements_competence.data or []

        # Nouvelles données de préalables
        nouveaux_prealables_data = form.prealables.data or []
        # Nouvelles données de corequis
        nouveaux_corequis = form.corequis.data

        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Mise à jour du cours
            cursor.execute('''
                UPDATE Cours
                SET programme_id = ?, code = ?, nom = ?, session = ?, heures_theorie = ?, heures_laboratoire = ?, heures_travail_maison = ?, fil_conducteur_id = ?
                WHERE id = ?
            ''', (programme_id, code, nom, session_num, heures_theorie, heures_laboratoire, heures_travail_maison, fil_conducteur_id, cours_id))

            # Mise à jour des éléments de compétence
            cursor.execute('DELETE FROM ElementCompetenceParCours WHERE cours_id = ?', (cours_id,))
            for ec in elements_competence_data:
                element_id = ec['element_competence']
                status = ec['status']
                if element_id and status:
                    cursor.execute('''
                        INSERT INTO ElementCompetenceParCours (cours_id, element_competence_id, status)
                        VALUES (?, ?, ?)
                    ''', (cours_id, element_id, status))

            # Mise à jour des préalables (avec la note)
            cursor.execute('DELETE FROM CoursPrealable WHERE cours_id = ?', (cours_id,))
            for p_data in nouveaux_prealables_data:
                p_id = p_data['cours_prealable_id']
                note = p_data['note_necessaire']
                if p_id and note is not None:
                    cursor.execute('''
                        INSERT INTO CoursPrealable (cours_id, cours_prealable_id, note_necessaire)
                        VALUES (?, ?, ?)
                    ''', (cours_id, p_id, note))

            # Mise à jour des corequis
            cursor.execute('DELETE FROM CoursCorequis WHERE cours_id = ?', (cours_id,))
            for c_id in nouveaux_corequis:
                cursor.execute('''
                    INSERT INTO CoursCorequis (cours_id, cours_corequis_id)
                    VALUES (?, ?)
                ''', (cours_id, c_id))

            conn.commit()
            conn.close()
            flash('Cours mis à jour avec succès!', 'success')
            return redirect(url_for('programme.view_programme', programme_id=programme_id))
        except sqlite3.Error as e:
            flash(f'Erreur lors de la mise à jour du cours : {e}', 'danger')
            return redirect(url_for('main.edit_cours', cours_id=cours_id))

    return render_template('edit_cours.html', form=form, elements_competence=elements_competence, cours_choices=cours_choices)
