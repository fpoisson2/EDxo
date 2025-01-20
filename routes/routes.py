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
    LoginForm,
    CreateUserForm, 
    DeleteUserForm,
    DepartmentForm, 
    DepartmentRegleForm, 
    DepartmentPIEAForm,
    DeleteForm,
    EditUserForm,
    ProgrammeMinisterielForm,
    ProgrammeForm,
    CreditManagementForm
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
from utils import get_db_connection, get_programme_id, parse_html_to_list, parse_html_to_nested_list, get_cegep_details_data, get_plan_cadre_data, replace_tags_jinja2, process_ai_prompt, generate_docx_with_template, get_all_cegeps, get_all_departments, get_all_programmes, get_programmes_by_user
from models import User, db, Department, DepartmentRegles, DepartmentPIEA, ListeProgrammeMinisteriel, Programme



main = Blueprint('main', __name__)

# Define the markdown filter
@main.app_template_filter('markdown')
def markdown_filter(text):
    return markdown.markdown(text)

@main.route('/gestion_programmes_cegep', methods=['GET', 'POST'])
@roles_required('admin')
def gestion_programmes_cegep():
    # Récupérer la liste des cégeps
    cegeps = get_all_cegeps()  # Ex.: [{'id': 1, 'nom': 'Cégep A'}, {'id': 2, 'nom': 'Cégep B'}]
    
    # Récupérer la liste des départements et des programmes ministériels
    # Adaptez ces fonctions à votre code – ici on part d'une requête via SQLAlchemy
    departments = [ (d.id, d.nom) for d in Department.query.order_by(Department.nom).all() ]
    # Ajouter une option par défaut pour Programme ministériel
    programmes_ministeriels = [(0, 'Aucun')] + [(pm.id, pm.nom) for pm in ListeProgrammeMinisteriel.query.order_by(ListeProgrammeMinisteriel.nom).all()]
    
    form = ProgrammeForm()
    # Alimenter les menus déroulants
    form.cegep_id.choices = [(c['id'], c['nom']) for c in cegeps]
    form.department_id.choices = departments
    form.liste_programme_ministeriel_id.choices = programmes_ministeriels

    # Si un cégep est sélectionné dans la query string, on le récupère;
    # sinon, on prend le premier dans la liste (si disponible)
    selected_cegep = request.args.get('cegep_id', type=int)
    if not selected_cegep and form.cegep_id.choices:
        selected_cegep = form.cegep_id.choices[0][0]  # Choix par défaut (premier cégep)
    form.cegep_id.data = selected_cegep

    # Si le formulaire est soumis, créer le nouveau programme associé à ce cégep
    if form.validate_on_submit():
        nouveau_programme = Programme(
            nom=form.nom.data,
            department_id=form.department_id.data,
            liste_programme_ministeriel_id=form.liste_programme_ministeriel_id.data or None,
            cegep_id=form.cegep_id.data,
            variante=form.variante.data or None
        )
        try:
            db.session.add(nouveau_programme)
            db.session.commit()
            flash("Programme ajouté avec succès.", "success")
            # Rediriger en passant le cégep sélectionné dans l'URL pour conserver le filtre
            return redirect(url_for('main.gestion_programmes_cegep', cegep_id=form.cegep_id.data))
        except Exception as e:
            db.session.rollback()
            flash("Erreur lors de l'ajout du programme: " + str(e), "danger")

    # Récupérer les programmes pour le cégep sélectionné (via le modèle Programme)
    programmes = Programme.query.filter_by(cegep_id=selected_cegep).all() if selected_cegep else []

    return render_template(
        'gestion_programmes_cegep.html',
        form=form,
        programmes=programmes,
        selected_cegep=selected_cegep,
        cegeps=cegeps
    )





@main.route('/gestion_programmes_ministeriels', methods=['GET', 'POST'])
@roles_required('admin')
def gestion_programmes_ministeriels():
    form = ProgrammeMinisterielForm()  # Crée le formulaire
    if form.validate_on_submit():
        nouveau_programme_min = ListeProgrammeMinisteriel(
            nom=form.nom.data,
            code=form.code.data
        )
        try:
            db.session.add(nouveau_programme_min)
            db.session.commit()
            flash("Programme ministériel ajouté avec succès.", "success")
            return redirect(url_for('main.gestion_programmes_ministeriels'))
        except Exception as e:
            db.session.rollback()
            flash("Erreur lors de l'ajout du programme ministériel : " + str(e), "danger")
    programmes = ListeProgrammeMinisteriel.query.all()
    return render_template('gestion_programmes_ministeriels.html', programmes=programmes, form=form)


@main.route('/ajouter_programme_ministeriel', methods=['GET', 'POST'])
@roles_required('admin')
def ajouter_programme_ministeriel():
    form = ProgrammeMinisterielForm()
    if form.validate_on_submit():
        # Création de l'objet ListeProgrammeMinisteriel
        nouveau_programme_min = ListeProgrammeMinisteriel(
            nom=form.nom.data,
            code=form.code.data
        )
        try:
            db.session.add(nouveau_programme_min)
            db.session.commit()
            flash("Programme ministériel ajouté avec succès.", "success")
            # Redirigez vers une page de liste ou l'accueil, par exemple.
            return redirect(url_for('liste_programmes_ministeriels'))
        except Exception as e:
            db.session.rollback()
            flash("Erreur lors de l'ajout du programme ministériel : " + str(e), "danger")
    
    return render_template('ajouter_programme_ministeriel.html', form=form)

# Exemple d'une route de listing
@main.route('/liste_programmes_ministeriels')
@roles_required('admin')
def liste_programmes_ministeriels():
    programmes = ListeProgrammeMinisteriel.query.all()
    return render_template('liste_programmes_ministeriels.html', programmes=programmes)

@main.route('/get_credit_balance', methods=['GET'])
@roles_required('admin')
def get_credit_balance():
    if not current_user.is_authenticated:
        return jsonify({'error': 'Not authenticated'}), 401
        
    try:
        # Si on utilise SQLAlchemy
        user = User.query.get(current_user.id)
        if user is None:
            return jsonify({'error': 'User not found'}), 404
            
        credit_value = user.credits if user.credits is not None else 0.0
        return jsonify({
            'success': True,
            'credit': "{:.2f}".format(float(credit_value))
        })
    except Exception as e:
        print(f"Error in get_credit_balance: {str(e)}")  # Log l'erreur
        return jsonify({
            'error': str(e),
            'credit': "0.00"  # Valeur par défaut en cas d'erreur
        }), 500

@main.route('/get_cegep_details')
@role_required('admin')
def get_cegep_details():
    cegep_id = request.args.get('cegep_id', type=int)
    if not cegep_id:
        return jsonify({'departments': [], 'programmes': []})

    conn = get_db_connection()
    departments = conn.execute('SELECT id, nom FROM Department WHERE cegep_id = ?', (cegep_id,)).fetchall()
    programmes = conn.execute('SELECT id, nom FROM Programme WHERE cegep_id = ?', (cegep_id,)).fetchall()
    conn.close()

    return jsonify({
        'departments': [{'id': d['id'], 'nom': d['nom']} for d in departments],
        'programmes': [{'id': p['id'], 'nom': p['nom']} for p in programmes]
    })



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
    if current_user.role != 'admin':
        flash('Accès interdit.', 'danger')
        return redirect(url_for('settings.parametres'))

    conn = get_db_connection()
    users = conn.execute('SELECT * FROM User').fetchall()
    conn.close()

    create_form = CreateUserForm(prefix='create')
    delete_forms = {user['id']: DeleteUserForm(prefix=f'delete_{user["id"]}') for user in users}
    credit_forms = {user['id']: CreditManagementForm(prefix=f'credit_{user["id"]}') for user in users}
    

    if request.method == 'POST':
        if 'create-submit' in request.form and create_form.validate_on_submit():
            username = create_form.username.data
            password = create_form.password.data
            role = create_form.role.data

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

        # Handle delete user forms
        for user in users:
            form = delete_forms[user['id']]
            if f'delete-submit-{user["id"]}' in request.form and form.validate_on_submit():
                user_id = form.user_id.data

                if str(user_id) == str(current_user.id):
                    flash('Vous ne pouvez pas supprimer votre propre compte.', 'danger')
                    return redirect(url_for('main.manage_users'))

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

            if f'credit-submit-{user["id"]}' in request.form:
                form = credit_forms[user['id']]
                if form.validate_on_submit():
                    try:
                        conn = get_db_connection()
                        amount = form.amount.data
                        operation = form.operation.data
                        
                        # Récupérer les crédits actuels
                        current_credits = conn.execute(
                            'SELECT credits FROM User WHERE id = ?', 
                            (user['id'],)
                        ).fetchone()['credits']
                        
                        # Calculer les nouveaux crédits
                        new_credits = current_credits + amount if operation == 'add' else current_credits - amount
                        
                        # Vérifier que les crédits ne deviennent pas négatifs
                        if new_credits < 0:
                            flash('Les crédits ne peuvent pas être négatifs.', 'danger')
                            return redirect(url_for('main.manage_users'))
                        
                        # Mettre à jour les crédits
                        conn.execute(
                            'UPDATE User SET credits = ? WHERE id = ?',
                            (new_credits, user['id'])
                        )
                        conn.commit()
                        
                        operation_text = "ajoutés à" if operation == 'add' else "retirés de"
                        flash(f'{amount} crédits ont été {operation_text} {user["username"]}.', 'success')
                        
                    except Exception as e:
                        flash(f'Erreur lors de la modification des crédits : {e}', 'danger')
                    finally:
                        conn.close()
                    return redirect(url_for('main.manage_users'))

    return render_template('manage_users.html', users=users, credit_forms=credit_forms, create_form=create_form, delete_forms=delete_forms, current_user_id=current_user.id)

@main.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@role_required('admin')
def edit_user(user_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM User WHERE id = ?', (user_id,)).fetchone()
    if user:
        user = dict(user)
        # Get user's programmes immediately
        user_programmes = conn.execute('''
            SELECT programme_id 
            FROM User_Programme 
            WHERE user_id = ?
        ''', (user_id,)).fetchall()
        user['programmes'] = [p['programme_id'] for p in user_programmes]
        print("User programmes loaded:", user['programmes'])  # Debug print
    conn.close()

    if not user:
        flash("Utilisateur non trouvé.", "danger")
        return redirect(url_for('main.manage_users'))
    
    form = EditUserForm()

    # Set initial choices for all dropdowns
    cegeps = get_all_cegeps()
    form.cegep_id.choices = [(0, 'Aucun')] + [(c['id'], c['nom']) for c in cegeps]

    # Handle GET request first (for initial load)
    if request.method == 'GET':
        if user['cegep_id']:
            details = get_cegep_details_data(user['cegep_id'])
            form.department_id.choices = [(0, 'Aucun')] + [(d['id'], d['nom']) for d in details['departments']]
            form.programmes.choices = [(p['id'], p['nom']) for p in details['programmes']]
        else:
            form.department_id.choices = [(0, 'Aucun')]
            form.programmes.choices = []

        # Pre-fill form data
        form.user_id.data = user['id']
        form.username.data = user['username']
        form.role.data = user['role']
        form.cegep_id.data = user['cegep_id'] if user['cegep_id'] else 0
        form.department_id.data = user['department_id'] if user['department_id'] else 0
        form.programmes.data = user['programmes']  # Set the programmes data here
        form.openai_key.data = user['openai_key']
        
        print("GET request - form.programmes.data:", form.programmes.data)
        print("GET request - form.programmes.choices:", form.programmes.choices)

    # Handle POST request
    else:
        submitted_cegep_id = request.form.get('cegep_id', type=int)
        if submitted_cegep_id and submitted_cegep_id != 0:
            details = get_cegep_details_data(submitted_cegep_id)
            form.department_id.choices = [(0, 'Aucun')] + [(d['id'], d['nom']) for d in details['departments']]
            form.programmes.choices = [(p['id'], p['nom']) for p in details['programmes']]
        else:
            form.department_id.choices = [(0, 'Aucun')]
            form.programmes.choices = []
        
        print("POST request - submitted data:", request.form.getlist('programmes'))

    if form.validate_on_submit():
        try:
            conn = get_db_connection()
            
            # Update user info
            conn.execute(
                '''UPDATE User SET 
                    username = ?, 
                    password = ?, 
                    role = ?, 
                    cegep_id = ?, 
                    department_id = ? ,
                    openai_key = ?
                WHERE id = ?''',
                (
                    form.username.data,
                    generate_password_hash(form.password.data, method='scrypt') if form.password.data else user['password'],
                    form.role.data,
                    form.cegep_id.data if form.cegep_id.data != 0 else None,
                    form.department_id.data if form.department_id.data != 0 else None,
                    form.openai_key.data,  # Ajout de l'openai_key
                    user_id
                )
            )
            
            # Update programmes - get directly from form submission
            submitted_programmes = request.form.getlist('programmes')
            print("Submitted programmes:", submitted_programmes)  # Debug print
            
            conn.execute('DELETE FROM User_Programme WHERE user_id = ?', (user_id,))
            
            if submitted_programmes:
                for prog_id in submitted_programmes:
                    prog_id = int(prog_id)  # Convert to integer
                    print(f"Inserting programme {prog_id} for user {user_id}")  # Debug print
                    conn.execute(
                        'INSERT INTO User_Programme (user_id, programme_id) VALUES (?, ?)', 
                        (user_id, prog_id)
                    )
            
            conn.commit()
            flash('Utilisateur mis à jour avec succès.', 'success')
            return redirect(url_for('main.manage_users'))
            
        except Exception as e:
            conn.rollback()
            flash(f'Erreur lors de la mise à jour : {e}', 'danger')
        finally:
            conn.close()

    print("Final form.programmes.data:", form.programmes.data)
    print("Final form.programmes.choices:", form.programmes.choices)

    return render_template('edit_user.html', form=form, user=user)

@main.route('/get_departments_and_programmes/<int:cegep_id>')
@login_required
def get_departments_and_programmes(cegep_id):
    if cegep_id == 0:
        return jsonify({
            'departments': [{'id': 0, 'nom': 'Aucun'}],
            'programmes': []
        })
    
    details = get_cegep_details_data(cegep_id)
    return jsonify({
        'departments': [{'id': 0, 'nom': 'Aucun'}] + details['departments'],
        'programmes': details['programmes']
    })




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
    competences = conn.execute('SELECT id, code, nom FROM Competence').fetchall()
    conn.close()
    form.competence.choices = [(c['id'], f"{c['code']} - {c['nom']}") for c in competences]


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
    # Modifier la requête initiale pour inclure le fil_conducteur_id
    cours = conn.execute('''
        SELECT c.*, fc.id as fil_conducteur_id 
        FROM Cours c 
        LEFT JOIN FilConducteur fc ON c.fil_conducteur_id = fc.id 
        WHERE c.id = ?
    ''', (cours_id,)).fetchone()
    
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
    # Modifier la requête pour inclure le code de la compétence
    elements_competence_rows = conn.execute('''
        SELECT ec.id, c.code || ' - ' || ec.nom as nom 
        FROM ElementCompetence ec
        JOIN Competence c ON ec.competence_id = c.id
        ORDER BY c.code, ec.nom
    ''').fetchall()
    elements_competence = [dict(row) for row in elements_competence_rows]

    ec_assoc_rows = conn.execute('SELECT element_competence_id, status FROM ElementCompetenceParCours WHERE cours_id = ?', (cours_id,)).fetchall()
    ec_assoc = [dict(row) for row in ec_assoc_rows]

    programmes_rows = conn.execute('SELECT id, nom FROM Programme').fetchall()
    programmes = [dict(row) for row in programmes_rows]

    # Récupérer les fils conducteurs
    fils_conducteurs_rows = conn.execute('SELECT id, description FROM FilConducteur').fetchall()
    fils_conducteurs = [(fc['id'], fc['description']) for fc in fils_conducteurs_rows]

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

        cours = conn.execute('''
            SELECT c.*, fc.id as fil_conducteur_id 
            FROM Cours c 
            LEFT JOIN FilConducteur fc ON c.fil_conducteur_id = fc.id 
            WHERE c.id = ?
        ''', (cours_id,)).fetchone()

        form.fil_conducteur.data = cours['fil_conducteur_id'] if cours['fil_conducteur_id'] else None

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

    conn.close()
    
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

@main.route('/parametres/gestion_departements', methods=['GET', 'POST'])
@roles_required('admin')
def gestion_departements():
    print("Request method:", request.method)
    print("Form data:", request.form)

    department_form = DepartmentForm()
    delete_department_form = DeleteForm()
    delete_rule_form = DeleteForm()
    delete_piea_form = DeleteForm()

    if request.method == 'POST':
        if 'ajouter_depart' in request.form:
            # Traitement pour ajouter un département
            if department_form.validate_on_submit():
                nouveau_dep = Department(
                    nom=department_form.nom.data
                )
                db.session.add(nouveau_dep)
                try:
                    db.session.commit()
                    flash("Département ajouté avec succès.", 'success')
                    return redirect(url_for('main.gestion_departements'))
                except Exception as e:
                    print(f"Error adding department: {e}")
                    db.session.rollback()
                    flash(f"Erreur lors de l'ajout du département : {e}", 'danger')
            else:
                flash("Veuillez remplir tous les champs correctement pour le département.", 'danger')

        if 'ajouter_regle' in request.form:
            department_id = request.form.get('department_id')
            print(f"Processing rule addition for department {department_id}")
            
            regle_form = DepartmentRegleForm()
            if regle_form.regle.data and regle_form.contenu.data:
                department = Department.query.get(department_id)
                if department:
                    nouvelle_regle = DepartmentRegles(
                        regle=regle_form.regle.data,
                        contenu=regle_form.contenu.data,
                        department_id=department.id
                    )
                    db.session.add(nouvelle_regle)
                    try:
                        db.session.commit()
                        flash("Règle ajoutée avec succès.", 'success')
                        return redirect(url_for('main.gestion_departements'))
                    except Exception as e:
                        print(f"Error adding rule: {e}")
                        db.session.rollback()
                        flash(f"Erreur lors de l'ajout de la règle : {e}", 'danger')
                else:
                    flash("Département non trouvé.", 'danger')
            else:
                flash("Veuillez remplir tous les champs.", 'danger')

        elif 'ajouter_piea' in request.form:
            department_id = request.form.get('department_id')
            print(f"Processing PIEA addition for department {department_id}")
            
            piea_form = DepartmentPIEAForm()
            if piea_form.article.data and piea_form.contenu.data:
                department = Department.query.get(department_id)
                if department:
                    nouvelle_piea = DepartmentPIEA(
                        article=piea_form.article.data,
                        contenu=piea_form.contenu.data,
                        department_id=department.id
                    )
                    db.session.add(nouvelle_piea)
                    try:
                        db.session.commit()
                        flash("Règle de PIEA ajoutée avec succès.", 'success')
                        return redirect(url_for('main.gestion_departements'))
                    except Exception as e:
                        print(f"Error adding PIEA: {e}")
                        db.session.rollback()
                        flash(f"Erreur lors de l'ajout de la règle de PIEA : {e}", 'danger')
                else:
                    flash("Département non trouvé.", 'danger')
            else:
                flash("Veuillez remplir tous les champs.", 'danger')

    # Pour le GET request ou si la validation échoue
    regle_form = DepartmentRegleForm()
    piea_form = DepartmentPIEAForm()
    departments = Department.query.order_by(Department.nom).all()
    
    return render_template(
        'gestion_departements.html',
        department_form=department_form,
        regle_form=regle_form,
        piea_form=piea_form,
        delete_department_form=delete_department_form,
        delete_rule_form=delete_rule_form,
        delete_piea_form=delete_piea_form,
        departments=departments
    )

@main.route('/parametres/gestion_departements/supprimer/<int:departement_id>', methods=['POST'])
@roles_required('admin')
def supprimer_departement(departement_id):
    department = Department.query.get_or_404(departement_id)
    try:
        db.session.delete(department)
        db.session.commit()
        flash(f"Département '{department.nom}' supprimé avec succès.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors de la suppression du département : {e}", 'danger')
    return redirect(url_for('main.gestion_departements'))

@main.route('/parametres/gestion_departements/supprimer_regle/<int:regle_id>', methods=['POST'])
@roles_required('admin')
def supprimer_regle(regle_id):
    regle = DepartmentRegles.query.get_or_404(regle_id)
    try:
        db.session.delete(regle)
        db.session.commit()
        flash("Règle supprimée avec succès.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors de la suppression de la règle : {e}", 'danger')
    return redirect(url_for('main.gestion_departements'))

@main.route('/parametres/gestion_departements/supprimer_piea/<int:piea_id>', methods=['POST'])
@roles_required('admin')
def supprimer_piea(piea_id):
    piea = DepartmentPIEA.query.get_or_404(piea_id)
    try:
        db.session.delete(piea)
        db.session.commit()
        flash("Règle de PIEA supprimée avec succès.", 'success')
    except Exception as e:
        db.session.rollback()
        flash(f"Erreur lors de la suppression de la règle de PIEA : {e}", 'danger')
    return redirect(url_for('main.gestion_departements'))

@main.route('/parametres/gestion_departements/edit_regle/<int:regle_id>', methods=['GET', 'POST'])
@roles_required('admin')
def edit_regle(regle_id):
    regle = DepartmentRegles.query.get_or_404(regle_id)
    form = DepartmentRegleForm()

    if form.validate_on_submit():
        regle.regle = form.regle.data
        regle.contenu = form.contenu.data
        try:
            db.session.commit()
            flash('Règle mise à jour avec succès.', 'success')
            return redirect(url_for('main.gestion_departements'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour de la règle : {e}', 'danger')
            return redirect(url_for('main.gestion_departements'))

    # Pré-remplir le formulaire avec les données existantes
    if request.method == 'GET':
        form.regle.data = regle.regle
        form.contenu.data = regle.contenu

    return render_template('edit_regle.html', 
                         form=form, 
                         regle=regle,
                         title='Modifier la Règle')

@main.route('/parametres/gestion_departements/edit_piea/<int:piea_id>', methods=['GET', 'POST'])
@roles_required('admin')
def edit_piea(piea_id):
    piea = DepartmentPIEA.query.get_or_404(piea_id)
    form = DepartmentPIEAForm()

    if form.validate_on_submit():
        piea.article = form.article.data
        piea.contenu = form.contenu.data
        try:
            db.session.commit()
            flash('Règle PIEA mise à jour avec succès.', 'success')
            return redirect(url_for('main.gestion_departements'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour de la règle PIEA : {e}', 'danger')
            return redirect(url_for('main.gestion_departements'))

    # Pré-remplir le formulaire avec les données existantes
    if request.method == 'GET':
        form.article.data = piea.article
        form.contenu.data = piea.contenu

    return render_template('edit_piea.html', 
                         form=form, 
                         piea=piea,
                         title='Modifier la Règle PIEA')