# app.py
import logging
from datetime import datetime

from collections import OrderedDict

import bleach
import markdown
import requests
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func  # Add this at the top with your other imports
from werkzeug.security import generate_password_hash, check_password_hash

from ..forms import (
    ProgrammeForm,
    CompetenceForm,
    ElementCompetenceForm,
    FilConducteurForm,
    CoursForm,
    CoursCorequisForm,
    CompetenceParCoursForm,
    ElementCompetenceParCoursForm,
    DeleteForm,
    CoursPrealableForm,
    ChangePasswordForm,
    LoginForm,
    CreateUserForm,
    DeleteUserForm,
    DepartmentForm,
    DepartmentRegleForm,
    DepartmentPIEAForm,
    EditUserForm,
    ProgrammeMinisterielForm,
    CreditManagementForm,
    CegepForm,
    CombinedWelcomeForm,
    ForgotPasswordForm,
    ResetPasswordForm

)
from ..models import (
    db,
    User,
    Department,
    DepartmentRegles,
    DepartmentPIEA,
    ListeProgrammeMinisteriel,
    Programme,
    Competence,
    ElementCompetence,
    ElementCompetenceCriteria,
    FilConducteur,
    CoursPrealable,
    CoursCorequis,
    CompetenceParCours,
    ElementCompetenceParCours,
    Cours,
    CoursProgramme,
    ListeCegep
)
from extensions import limiter
from utils.decorator import role_required, roles_required, ensure_profile_completed
from utils.utils import (
    get_all_cegeps,
    get_cegep_details_data,
    send_reset_email
)

logger = logging.getLogger(__name__)

main = Blueprint('main', __name__)

@main.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        # Vérification du token reCAPTCHA v3
        recaptcha_token = form.recaptcha_token.data.strip() if form.recaptcha_token.data else None
        if not recaptcha_token:
            flash("Le token reCAPTCHA est manquant. Veuillez réessayer.", "danger")
            return redirect(url_for('main.forgot_password'))
        verify_url = "https://www.google.com/recaptcha/api/siteverify"
        payload = {
            'secret': current_app.config['RECAPTCHA_SECRET_KEY'],
            'response': recaptcha_token,
            'remoteip': request.remote_addr
        }
        response = requests.post(verify_url, data=payload)
        result = response.json()
        if not result.get('success', False) or result.get('score', 0) < 0.5:
            flash("La vérification reCAPTCHA a échoué. Veuillez réessayer.", "danger")
            return redirect(url_for('main.forgot_password'))

        user = User.query.filter_by(email=form.email.data).first()
        if user:
            token = user.get_reset_token()
            send_reset_email(user.email, token)
        # On affiche toujours le message pour ne pas révéler si l'email existe ou non
        flash("Si un compte existe avec cette adresse, un email de réinitialisation a été envoyé.", "info")
        return redirect(url_for('main.login'))
    return render_template('forgot_password.html', form=form)



@main.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    user = User.verify_reset_token(token)
    if not user:
        flash("Le lien est invalide ou a expiré.", "warning")
        return redirect(url_for('main.forgot_password'))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        # Vérification du token reCAPTCHA v3
        recaptcha_token = form.recaptcha_token.data.strip() if form.recaptcha_token.data else None
        if not recaptcha_token:
            flash("Le token reCAPTCHA est manquant. Veuillez réessayer.", "danger")
            return redirect(url_for('main.reset_password', token=token))
        verify_url = "https://www.google.com/recaptcha/api/siteverify"
        payload = {
            'secret': current_app.config['RECAPTCHA_SECRET_KEY'],
            'response': recaptcha_token,
            'remoteip': request.remote_addr
        }
        response = requests.post(verify_url, data=payload)
        result = response.json()
        if not result.get('success', False) or result.get('score', 0) < 0.5:
            flash("La vérification reCAPTCHA a échoué. Veuillez réessayer.", "danger")
            return redirect(url_for('main.reset_password', token=token))

        user.password = generate_password_hash(form.password.data, method='scrypt')
        # Invalider le token en incrémentant reset_version
        user.reset_version = (user.reset_version or 0) + 1
        db.session.commit()
        flash("Votre mot de passe a été mis à jour. Vous pouvez vous connecter.", "success")
        return redirect(url_for('main.login'))
    return render_template('reset_password.html', form=form)



@main.route('/task_status/<task_id>', methods=['GET'])
def task_status(task_id):
    from celery_app import celery
    from celery.result import AsyncResult

    res = AsyncResult(task_id, app=celery)
    current_state = res.state
    # Récupération du meta si présent, sinon message par défaut
    meta = res.info if res.info else {}
    current_message = meta.get('message', '')
    logger.info("Task %s state: %s, meta: %s", task_id, current_state, meta)
    
    return jsonify({
        'state': current_state,
        'message': current_message,
        'result': res.result if current_state == 'SUCCESS' else None
    })



@main.route('/clear_task_id', methods=['POST'])
def clear_task_id():
    session.pop('task_id', None)
    return jsonify(success=True)

@main.route('/gestion_cegeps', methods=['GET', 'POST'])
def gestion_cegeps():
    form = CegepForm()
    
    if form.validate_on_submit():
        # Ajouter un nouveau cégep
        nouveau_cegep = ListeCegep(
            nom=form.nom.data,
            type=form.type.data,
            region=form.region.data
        )
        db.session.add(nouveau_cegep)
        db.session.commit()
        flash('Cégep ajouté avec succès!', 'success')
        return redirect(url_for('main.gestion_cegeps'))
    
    # Récupérer tous les cégeps pour affichage
    cegeps = ListeCegep.query.all()
    return render_template('gestion_cegeps.html', form=form, cegeps=cegeps)

@main.route('/supprimer_cegep/<int:id>', methods=['POST'])
def supprimer_cegep(id):
    cegep = ListeCegep.query.get_or_404(id)
    db.session.delete(cegep)
    db.session.commit()
    flash('Cégep supprimé avec succès!', 'success')
    return redirect(url_for('main.gestion_cegeps'))

@main.route('/modifier_cegep/<int:id>', methods=['GET', 'POST'])
def modifier_cegep(id):
    cegep = ListeCegep.query.get_or_404(id)
    form = CegepForm(obj=cegep)
    
    if form.validate_on_submit():
        cegep.nom = form.nom.data
        cegep.type = form.type.data
        cegep.region = form.region.data
        db.session.commit()
        flash('Cégep modifié avec succès!', 'success')
        return redirect(url_for('main.gestion_cegeps'))
    
    return render_template('modifier_cegep.html', form=form, cegep=cegep)

# Define the markdown filter
@main.app_template_filter('markdown')
def markdown_filter(text):
    return markdown.markdown(text)

@main.route('/gestion_programmes_cegep', methods=['GET', 'POST'])
@roles_required('admin')
def gestion_programmes_cegep():
    # Récupérer la liste des cégeps
    cegeps = get_all_cegeps()  # Ex.: [{'id': 1, 'nom': 'Cégep A'}, {'id': 2, 'nom': 'Cégep B'}]
    
    # Récupérer la liste des départements et des programmes ministériels via SQLAlchemy
    departments = [(d.id, d.nom) for d in Department.query.order_by(Department.nom).all()]
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

    # Récupérer les programmes pour le cégep sélectionné
    if selected_cegep:
        programmes = Programme.query.filter_by(cegep_id=selected_cegep).all()
    else:
        programmes = []

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
        nouveau_programme_min = ListeProgrammeMinisteriel(
            nom=form.nom.data,
            code=form.code.data
        )
        try:
            db.session.add(nouveau_programme_min)
            db.session.commit()
            flash("Programme ministériel ajouté avec succès.", "success")
            return redirect(url_for('main.liste_programmes_ministeriels'))
        except Exception as e:
            db.session.rollback()
            flash("Erreur lors de l'ajout du programme ministériel : " + str(e), "danger")
    
    return render_template('ajouter_programme_ministeriel.html', form=form)

@main.route('/liste_programmes_ministeriels')
@roles_required('admin')
def liste_programmes_ministeriels():
    programmes = ListeProgrammeMinisteriel.query.all()
    return render_template('liste_programmes_ministeriels.html', programmes=programmes)

@main.route('/get_credit_balance', methods=['GET'])
@login_required
def get_credit_balance():
    if not current_user.is_authenticated:
        return jsonify({'error': 'Not authenticated'}), 401
        
    try:
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
            'credit': "0.00"
        }), 500

@main.route('/get_cegep_details')
@role_required('admin')
def get_cegep_details():
    cegep_id = request.args.get('cegep_id', type=int)
    if not cegep_id:
        return jsonify({'departments': [], 'programmes': []})
    
    departments = Department.query.filter_by(cegep_id=cegep_id).all()
    programmes = Programme.query.filter_by(cegep_id=cegep_id).all()

    return jsonify({
        'departments': [{'id': d.id, 'nom': d.nom} for d in departments],
        'programmes': [{'id': p.id, 'nom': p.nom} for p in programmes]
    })

@main.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = LoginForm()
    if form.validate_on_submit():
        # Vérification du token reCAPTCHA v3
        recaptcha_token = form.recaptcha_token.data.strip() if form.recaptcha_token.data else None
        if not recaptcha_token:
            flash("Le token reCAPTCHA est manquant. Veuillez réessayer.", "danger")
            return redirect(url_for('main.login'))

        verify_url = "https://www.google.com/recaptcha/api/siteverify"
        payload = {
            'secret': current_app.config['RECAPTCHA_SECRET_KEY'],
            'response': recaptcha_token,
            'remoteip': request.remote_addr
        }
        response = requests.post(verify_url, data=payload)
        result = response.json()

        # Seuil à ajuster selon vos besoins (ex. 0.5)
        if not result.get('success', False) or result.get('score', 0) < 0.5:
            flash("La vérification reCAPTCHA a échoué. Veuillez réessayer.", "danger")
            return redirect(url_for('main.login'))

        # Authentification de l'utilisateur
        username = form.username.data.lower()
        password = form.password.data

        user_row = User.query.filter(func.lower(User.username) == username).first()
        if user_row and check_password_hash(user_row.password, password):
            user_row.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user_row, remember=True)
            session.permanent = True

            if user_row.is_first_connexion:
                return redirect(url_for('main.welcome'))

            next_page = request.args.get('next')
            if not next_page or not next_page.startswith('/'):
                next_page = url_for('main.index')

            return redirect(next_page)
        else:
            flash("Nom d'utilisateur ou mot de passe incorrect.", "danger")

    return render_template('login.html', form=form)


def get_avatar_url(image_identifier):
    # Nouvelle logique pour générer l'URL de l'avatar
    return image_identifier

@main.route('/welcome', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
@login_required
def welcome():
    if not current_user.is_first_connexion:
        return redirect(url_for('main.index'))

    form = CombinedWelcomeForm()

    # Remplir les choix des sélecteurs
    seed = current_user.email or str(current_user.id)
    dicebear_styles = ["pixel-art", "bottts", "adventurer", "lorelei", "identicon"]
    avatar_choices = [
        (f"https://api.dicebear.com/7.x/{style}/svg?seed={seed}&backgroundColor=b6e3f4", style.capitalize()) 
        for style in dicebear_styles
    ]
    form.image.choices = avatar_choices
    form.cegep.choices = [(cegep.id, cegep.nom) for cegep in ListeCegep.query.order_by(ListeCegep.nom).all()]
    form.department.choices = [(dept.id, dept.nom) for dept in Department.query.order_by(Department.nom).all()]
    form.programmes.choices = [(prog.id, prog.nom) for prog in Programme.query.order_by(Programme.nom).all()]

    current_section = 0  # Par défaut, première section

    if form.validate_on_submit():
        # Premièrement, vérifier la correspondance des mots de passe
        if form.new_password.data or form.confirm_password.data:
            if form.new_password.data != form.confirm_password.data:
                form.confirm_password.errors.append('Les nouveaux mots de passe ne correspondent pas.')
                current_section = 5  # 6ème section, index 5
                #flash('Les nouveaux mots de passe ne correspondent pas.', 'danger')
                avatar_url = current_user.image or avatar_choices[0][0]
                return render_template('welcome.html', form=form, avatar_url=avatar_url, current_section=current_section)
        
        # Toutes les validations sont passées, procéder à la mise à jour des données
        try:
            # Traitement du formulaire de profil
            current_user.prenom = form.prenom.data
            current_user.nom = form.nom.data
            current_user.email = form.email.data
            current_user.image = form.image.data
            current_user.cegep_id = form.cegep.data
            current_user.department_id = form.department.data
            current_user.programmes = Programme.query.filter(Programme.id.in_(form.programmes.data)).all()

            # Traitement du formulaire de changement de mot de passe
            if form.new_password.data and form.confirm_password.data:
                current_user.password = generate_password_hash(form.new_password.data, method='scrypt')

            # Désactiver la première connexion
            current_user.is_first_connexion = False

            db.session.commit()
            #flash('Profil et mot de passe mis à jour avec succès.', 'success')
            logger.info(f"Utilisateur {current_user.email} a complété la première connexion depuis {request.remote_addr}.")
            return redirect(url_for('main.index'))
        except Exception as e:
            db.session.rollback()
            logger.error(f"Erreur lors de la mise à jour du profil pour l'utilisateur {current_user.email}: {e}")
            #flash('Une erreur est survenue. Veuillez réessayer plus tard.', 'danger')
            # Déterminer la section actuelle en fonction des erreurs du formulaire
            if form.prenom.errors or form.nom.errors:
                current_section = 0
            elif form.email.errors:
                current_section = 1
            elif form.image.errors:
                current_section = 2
            elif form.cegep.errors or form.department.errors:
                current_section = 3
            elif form.programmes.errors:
                current_section = 4
            elif form.new_password.errors or form.confirm_password.errors:
                current_section = 5
            avatar_url = current_user.image or avatar_choices[0][0]
            return render_template('welcome.html', form=form, avatar_url=avatar_url, current_section=current_section)
    else:
        if request.method == 'POST':
            #flash('Veuillez corriger les erreurs dans le formulaire.', 'danger')
            # Déterminer la section actuelle en fonction des erreurs du formulaire
            if form.prenom.errors or form.nom.errors:
                current_section = 0
            elif form.email.errors:
                current_section = 1
            elif form.image.errors:
                current_section = 2
            elif form.cegep.errors or form.department.errors:
                current_section = 3
            elif form.programmes.errors:
                current_section = 4
            elif form.new_password.errors or form.confirm_password.errors:
                current_section = 5

    if request.method == 'GET':
        # Pré-remplir les formulaires avec les données actuelles de l'utilisateur
        form.prenom.data = current_user.prenom
        form.nom.data = current_user.nom
        form.email.data = current_user.email
        form.image.data = current_user.image
        form.cegep.data = current_user.cegep_id
        form.department.data = current_user.department_id
        form.programmes.data = [programme.id for programme in current_user.programmes]

    avatar_url = current_user.image or avatar_choices[0][0]

    return render_template('welcome.html', form=form, avatar_url=avatar_url, current_section=current_section)




@main.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Déconnexion réussie.', 'success')
    return redirect(url_for('main.login'))

@main.route('/manage_users', methods=['GET', 'POST'])
@role_required('admin')
@ensure_profile_completed
def manage_users():
    if current_user.role != 'admin':
        flash('Accès interdit.', 'danger')
        return redirect(url_for('settings.parametres'))

    users = User.query.all()

    create_form = CreateUserForm(prefix='create')
    delete_forms = {u.id: DeleteUserForm(prefix=f'delete_{u.id}') for u in users}
    credit_forms = {u.id: CreditManagementForm(prefix=f'credit_{u.id}') for u in users}
    
    if request.method == 'POST':
        if 'create-submit' in request.form and create_form.validate_on_submit():
            from sqlalchemy import func
            username = create_form.username.data.strip().lower()
            password = create_form.password.data
            role = create_form.role.data

            existing_user = User.query.filter(func.lower(User.username) == username).first()
            if existing_user:
                flash("Ce nom d'utilisateur est déjà pris.", "danger")
                return redirect(url_for('main.manage_users'))

            hashed_password = generate_password_hash(password, method='scrypt')
            new_user = User(username=username, password=hashed_password, role=role, credits=0)
            try:
                db.session.add(new_user)
                db.session.commit()
                flash('Utilisateur créé avec succès.', 'success')
            except Exception as e:
                db.session.rollback()
                print(f"Erreur lors de la création d'utilisateur : {e}")
                flash("Une erreur s'est produite lors de la création de l'utilisateur.", "danger")

            return redirect(url_for('main.manage_users'))

        # Handle delete user forms
        for user in users:
            form = delete_forms[user.id]
            if f'delete-submit-{user.id}' in request.form and form.validate_on_submit():
                user_id = form.user_id.data

                if str(user_id) == str(current_user.id):
                    flash('Vous ne pouvez pas supprimer votre propre compte.', 'danger')
                    return redirect(url_for('main.manage_users'))

                user_to_delete = User.query.get(user_id)
                if user_to_delete:
                    try:
                        db.session.delete(user_to_delete)
                        db.session.commit()
                        flash('Utilisateur supprimé avec succès.', 'success')
                    except Exception as e:
                        db.session.rollback()
                        flash(f'Erreur lors de la suppression : {e}', 'danger')
                return redirect(url_for('main.manage_users'))

            # Handle credit management forms
            if f'credit-submit-{user.id}' in request.form:
                form = credit_forms[user.id]
                if form.validate_on_submit():
                    try:
                        amount = form.amount.data
                        operation = form.operation.data
                        
                        current_credits = user.credits
                        new_credits = current_credits + amount if operation == 'add' else current_credits - amount
                        
                        if new_credits < 0:
                            flash('Les crédits ne peuvent pas être négatifs.', 'danger')
                            return redirect(url_for('main.manage_users'))
                        
                        user.credits = new_credits
                        db.session.commit()
                        
                        operation_text = "ajoutés à" if operation == 'add' else "retirés de"
                        flash(f'{amount} crédits ont été {operation_text} {user.username}.', 'success')
                        
                    except Exception as e:
                        db.session.rollback()
                        flash(f'Erreur lors de la modification des crédits : {e}', 'danger')
                    return redirect(url_for('main.manage_users'))

    return render_template('manage_users.html', users=users, credit_forms=credit_forms, create_form=create_form, delete_forms=delete_forms, current_user_id=current_user.id)

@main.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@role_required('admin')
@ensure_profile_completed
def edit_user(user_id):
    user = User.query.get(user_id)
    if not user:
        flash("Utilisateur non trouvé.", "danger")
        return redirect(url_for('main.manage_users'))

    # Charger les programmes de l'utilisateur
    user_programmes = [prog.id for prog in user.programmes]

    form = EditUserForm()

    cegeps = get_all_cegeps()
    form.cegep_id.choices = [(0, 'Aucun')] + [(c['id'], c['nom']) for c in cegeps]

    if request.method == 'GET':
        # Pré-remplir les champs
        form.user_id.data = user.id
        form.username.data = user.username
        form.email.data = user.email  # Ajout du courriel
        form.role.data = user.role
        form.cegep_id.data = user.cegep_id if user.cegep_id else 0
        form.department_id.data = user.department_id if user.department_id else 0
        form.openai_key.data = user.openai_key

        # Charger la liste programmes pour le cégep sélectionné (s'il y en a un)
        if user.cegep_id:
            details = get_cegep_details_data(user.cegep_id)
            form.department_id.choices = [(0, 'Aucun')] + [(d['id'], d['nom']) for d in details['departments']]
            form.programmes.choices = [(p['id'], p['nom']) for p in details['programmes']]
        else:
            form.department_id.choices = [(0, 'Aucun')]
            form.programmes.choices = []

        form.programmes.data = user_programmes

    else:
        submitted_cegep_id = request.form.get('cegep_id', type=int)
        if submitted_cegep_id and submitted_cegep_id != 0:
            details = get_cegep_details_data(submitted_cegep_id)
            form.department_id.choices = [(0, 'Aucun')] + [(d['id'], d['nom']) for d in details['departments']]
            form.programmes.choices = [(p['id'], p['nom']) for p in details['programmes']]
        else:
            form.department_id.choices = [(0, 'Aucun')]
            form.programmes.choices = []

    if form.validate_on_submit():
        try:
            user.username = form.username.data
            user.email = form.email.data  # Mise à jour du courriel
            # Si un nouveau mot de passe est fourni
            if form.password.data:
                user.password = generate_password_hash(form.password.data, method='scrypt')
            user.role = form.role.data
            user.cegep_id = form.cegep_id.data if form.cegep_id.data != 0 else None
            user.department_id = form.department_id.data if form.department_id.data != 0 else None
            user.openai_key = form.openai_key.data

            # Vider la relation programmes et re-insérer
            user.programmes.clear()

            submitted_programmes = request.form.getlist('programmes')
            for prog_id in submitted_programmes:
                prog_obj = Programme.query.get(int(prog_id))
                if prog_obj:
                    user.programmes.append(prog_obj)

            db.session.commit()
            flash('Utilisateur mis à jour avec succès.', 'success')
            return redirect(url_for('main.manage_users'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour : {e}', 'danger')

    return render_template('edit_user.html', form=form, user=user)


@main.route('/get_departments_and_programmes/<int:cegep_id>')
@login_required
@ensure_profile_completed
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
@ensure_profile_completed
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        current_password = form.current_password.data
        new_password = form.new_password.data

        if not check_password_hash(current_user.password, current_password):
            flash('Mot de passe actuel incorrect.', 'danger')
            return redirect(url_for('main.change_password'))

        hashed_new_password = generate_password_hash(new_password, method='scrypt')
        try:
            current_user.password = hashed_new_password
            db.session.commit()
            flash('Votre mot de passe a été mis à jour avec succès.', 'success')
            return redirect(url_for('main.profile'))  # Remplacez par la route souhaitée
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour du mot de passe : {e}', 'danger')
            return redirect(url_for('main.change_password'))

    return render_template('change_password.html', form=form)

@main.route('/')
@login_required
@ensure_profile_completed
def index():
    # Récupérer l'utilisateur connecté
    user = current_user
    
    # Vérifier si l'utilisateur est associé à un programme
    if user.programmes:
        default_programme_id = user.programmes[0].id
        return redirect(url_for('programme.view_programme', programme_id=default_programme_id))
    
    # Si l'utilisateur n'a pas de programme, vérifier les programmes disponibles
    programmes = Programme.query.all()
    if programmes:
        # There are available programmes, redirect to the first one
        return redirect(url_for('programme.view_programme', programme_id=programmes[0].id))
    elif user.role == 'admin':
        # No programmes available and user is admin
        flash("Aucun programme disponible. Veuillez en ajouter un.", "warning")
        return redirect(url_for('main.add_programme'))
    else:
        # No programmes available and user is not admin
        flash("Vous n'avez accès à aucun programme. Veuillez contacter un administrateur.", "warning")
        return render_template('no_access.html')


@main.route('/add_programme', methods=('GET', 'POST'))
@role_required('admin')
@ensure_profile_completed
def add_programme():
    form = ProgrammeForm()
    if form.validate_on_submit():
        nom = form.nom.data
        new_prog = Programme(nom=nom, department_id=1)  # Must set department_id or handle it
        try:
            db.session.add(new_prog)
            db.session.commit()
            flash('Programme ajouté avec succès!')
            return redirect(url_for('main.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'ajout du programme : {e}', 'danger')
    return render_template('add_programme.html', form=form)

@main.route('/add_competence', methods=['GET', 'POST'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def add_competence():
    form = CompetenceForm()
    if current_user.role == 'admin':
        # Admin: voir tous les programmes
        programmes = Programme.query.all()
    elif current_user.role == 'coordo':
        # Coordo: voir seulement les programmes auxquels il a accès.
        # Assure-toi que tu as une relation ou une méthode qui te fournit ça.
        programmes = current_user.programmes  
    else:
        programmes = []

    form.programme.choices = [(p.id, p.nom) for p in programmes]

    if form.validate_on_submit():
        programme_id = form.programme.data
        code = form.code.data
        nom = form.nom.data
        criteria_de_performance = form.criteria_de_performance.data or ""
        contexte_de_realisation = form.contexte_de_realisation.data or ""

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

        new_comp = Competence(
            programme_id=programme_id,
            code=code,
            nom=nom,
            criteria_de_performance=criteria_clean,
            contexte_de_realisation=context_clean
        )
        try:
            db.session.add(new_comp)
            db.session.commit()
            flash('Compétence ajoutée avec succès!', 'success')
            return redirect(url_for('programme.view_programme', programme_id=programme_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'ajout de la compétence : {e}', 'danger')

    return render_template('add_competence.html', form=form)


@main.route('/add_element_competence', methods=('GET', 'POST'))
@roles_required('admin', 'coordo')
@ensure_profile_completed
def add_element_competence():
    form = ElementCompetenceForm()
    
    # Si c'est un admin, il voit toutes les compétences,
    # sinon, on filtre selon les programmes auxquels le coordo a accès.
    if current_user.role == 'admin':
        competences = Competence.query.all()
    elif current_user.role == 'coordo':
        # On récupère les id des programmes auxquels le coordo a accès
        allowed_programmes = [p.id for p in current_user.programmes]
        competences = Competence.query.filter(Competence.programme_id.in_(allowed_programmes)).all()
    else:
        competences = []
    
    form.competence.choices = [(c.id, f"{c.code} - {c.nom}") for c in competences]

    if form.validate_on_submit():
        competence_id = form.competence.data
        nom = form.nom.data
        criteres = form.criteres_de_performance.data  # Liste des critères

        new_elem = ElementCompetence(
            competence_id=competence_id,
            nom=nom
        )
        try:
            db.session.add(new_elem)
            db.session.commit()
            # Insérer chaque critère de performance
            for crit in criteres:
                if crit.strip():
                    new_crit = ElementCompetenceCriteria(
                        element_competence_id=new_elem.id,
                        criteria=crit.strip()
                    )
                    db.session.add(new_crit)
            db.session.commit()
            flash('Élément de compétence et critères de performance ajoutés avec succès!', 'success')
            return redirect(url_for('programme.view_programme', programme_id=new_elem.competence.programme_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'ajout de l\'élément de compétence : {e}', 'danger')

    return render_template('add_element_competence.html', form=form)



@main.route('/edit_fil_conducteur/<int:fil_id>', methods=['GET', 'POST'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def edit_fil_conducteur(fil_id):
    fil = FilConducteur.query.get_or_404(fil_id)
    form = FilConducteurForm(obj=fil)  # initialise description/couleur
    
    # Charger la liste de programmes
    programmes = Programme.query.all()
    form.programme.choices = [(p.id, p.nom) for p in programmes]
    
    # S’assurer que l’affichage initial a la bonne valeur de SelectField
    if request.method == 'GET':
        form.programme.data = fil.programme_id

    if form.validate_on_submit():
        fil.programme_id = form.programme.data
        fil.description = form.description.data
        fil.couleur = form.couleur.data or '#FFFFFF'
        
        db.session.commit()
        return redirect(url_for('programme.view_programme', programme_id=fil.programme_id))
    
    return render_template('edit_fil_conducteur.html', form=form, fil=fil)

@main.route('/add_fil_conducteur', methods=('GET', 'POST'))
@roles_required('admin', 'coordo')
@ensure_profile_completed
def add_fil_conducteur():
    form = FilConducteurForm()
    accessible_programmes = Programme.query.filter(
        Programme.id.in_([p.id for p in current_user.programmes])
    ).all()
    form.programme.choices = [(p.id, p.nom) for p in accessible_programmes]

    if form.validate_on_submit():
        programme_id = form.programme.data
        description = form.description.data
        couleur = form.couleur.data or '#FFFFFF'

        new_fil = FilConducteur(
            programme_id=programme_id,
            description=description,
            couleur=couleur
        )
        try:
            db.session.add(new_fil)
            db.session.commit()
            flash('Fil conducteur ajouté avec succès!')
            return redirect(url_for('programme.view_programme', programme_id=programme_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'ajout du fil conducteur : {e}', 'danger')

    return render_template('add_fil_conducteur.html', form=form)


@main.route('/add_cours', methods=('GET', 'POST'))
@roles_required('admin', 'coordo')
@ensure_profile_completed
def add_cours():
    form = CoursForm()
    
    # Filtrer les programmes accessibles par l'utilisateur courant.
    # Remplacez cette ligne par la méthode appropriée pour récupérer les programmes auxquels current_user a accès.
    accessible_programmes = Programme.query.filter(
        Programme.id.in_([p.id for p in current_user.programmes])
    ).all()

    programme_id = accessible_programmes[0].id if accessible_programmes else None


    # Récupération du programme par défaut à partir des paramètres GET (ex: ?programme_id=2)
    # ou utilisation du premier programme accessible si aucun n'est spécifié.
    selected_programme = request.args.get('programme_id', None)
    if selected_programme is not None:
        try:
            selected_programme = int(selected_programme)
        except ValueError:
            selected_programme = None
    if not selected_programme and accessible_programmes:
        selected_programme = accessible_programmes[0].id

    # Définir les choix du menu déroulant pour le champ programme

    # ----------------------------------------------
    # Programmes associés (many-to-many)
    # ----------------------------------------------
    # Même liste que pour le programme principal, mais on laisse l'utilisateur
    # en sélectionner plusieurs. On retirera toutefois le programme principal
    # au moment de la persistance afin d'éviter les doublons inutiles.
    form.programmes_associes.choices = [(p.id, p.nom) for p in accessible_programmes]

    # Filtrer les éléments de compétence pour n'inclure que ceux associés au programme sélectionné.
    # On suppose ici que le modèle Competence possède un attribut programme_id.
    elements_competence_rows = (
        ElementCompetence.query
        .join(Competence)
        .filter(Competence.programme_id == selected_programme)
        .all()
    )

    # Préparer les choix pour chaque sous-formulaire d'élément de compétence.
    for subform in form.elements_competence:
        subform.element_competence.choices = [
            (ec.id, f"{ec.competence.code} - {ec.nom}") for ec in elements_competence_rows
        ]

    if form.validate_on_submit():
        code = form.code.data
        nom = form.nom.data
        heures_theorie = form.heures_theorie.data
        heures_laboratoire = form.heures_laboratoire.data
        heures_travail_maison = form.heures_travail_maison.data
        nombre_unites = (heures_theorie + heures_laboratoire + heures_travail_maison) / 3

        new_cours = Cours(
            code=code,
            nom=nom,
            nombre_unites=nombre_unites,
            heures_theorie=heures_theorie,
            heures_laboratoire=heures_laboratoire,
            heures_travail_maison=heures_travail_maison
        )

        try:
            # Enregistrer le nouveau cours
            db.session.add(new_cours)
            db.session.commit()
            # ----------------------------------------------------------
            # Ajout des associations many-to-many via CoursProgramme
            # ----------------------------------------------------------
            programmes_ids = form.programmes_associes.data or []
            for pid in programmes_ids:
                # Lire la session spécifique
                sess_val = request.form.get(f'session_{pid}')
                try:
                    sess = int(sess_val)
                except (TypeError, ValueError):
                    sess = 0
                db.session.add(CoursProgramme(
                    cours_id=new_cours.id,
                    programme_id=pid,
                    session=sess
                ))
            db.session.commit()

            elements_competence_data = form.elements_competence.data or []
            for ec in elements_competence_data:
                element_id = ec.get('element_competence')
                status = ec.get('status')
                if element_id and status:
                    new_ec_assoc = ElementCompetenceParCours(
                        cours_id=new_cours.id,
                        element_competence_id=element_id,
                        status=status
                    )
                    db.session.add(new_ec_assoc)
            db.session.commit()
            flash('Cours ajouté avec succès!', 'success')
            return redirect(url_for('programme.view_programme', programme_id=programme_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'ajout du cours : {e}', 'danger')

    # Conversion des objets ElementCompetence en dictionnaires pour la sérialisation JSON
    elements_competence_dicts = [ec.to_dict() for ec in elements_competence_rows]
    return render_template(
        'add_cours.html',
        form=form,
        elements_competence=elements_competence_dicts
    )


@main.route('/add_cours_prealable', methods=('GET', 'POST'))
@roles_required('admin', 'coordo')
@ensure_profile_completed
def add_cours_prealable():
    form = CoursPrealableForm()
    cours_all = Cours.query.all()
    form.cours.choices = [(c.id, c.nom) for c in cours_all]
    form.cours_prealable.choices = [(c.id, c.nom) for c in cours_all]

    if form.validate_on_submit():
        cours_id = form.cours.data
        cours_prealable_id = form.cours_prealable.data
        note_necessaire = form.note_necessaire.data

        new_pre = CoursPrealable(
            cours_id=cours_id,
            cours_prealable_id=cours_prealable_id,
            note_necessaire=note_necessaire
        )
        try:
            db.session.add(new_pre)
            db.session.commit()
            flash('Cours préalable ajouté avec succès!')
            return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'ajout du cours préalable : {e}', 'danger')

    return render_template('add_cours_prealable.html', form=form)

@main.route('/add_cours_corequis', methods=('GET', 'POST'))
@roles_required('admin', 'coordo')
@ensure_profile_completed
def add_cours_corequis():
    form = CoursCorequisForm()
    cours_all = Cours.query.all()
    form.cours.choices = [(c.id, c.nom) for c in cours_all]
    form.cours_corequis.choices = [(c.id, c.nom) for c in cours_all]

    if form.validate_on_submit():
        cours_id = form.cours.data
        cours_corequis_id = form.cours_corequis.data

        new_coreq = CoursCorequis(
            cours_id=cours_id,
            cours_corequis_id=cours_corequis_id
        )
        try:
            db.session.add(new_coreq)
            db.session.commit()
            flash('Cours corequis ajouté avec succès!')
            return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'ajout du cours corequis : {e}', 'danger')

    return render_template('add_cours_corequis.html', form=form)

@main.route('/add_competence_par_cours', methods=('GET', 'POST'))
@roles_required('admin', 'coordo')
@ensure_profile_completed
def add_competence_par_cours():
    form = CompetenceParCoursForm()
    cours_all = Cours.query.all()
    competences_all = Competence.query.all()
    form.cours.choices = [(c.id, c.nom) for c in cours_all]
    form.competence_developpee.choices = [(c.id, c.nom) for c in competences_all]
    form.competence_atteinte.choices = [(c.id, c.nom) for c in competences_all]

    if form.validate_on_submit():
        cours_id = form.cours.data
        competence_developpee_id = form.competence_developpee.data
        competence_atteinte_id = form.competence_atteinte.data

        new_comp_pc = CompetenceParCours(
            cours_id=cours_id,
            competence_developpee_id=competence_developpee_id,
            competence_atteinte_id=competence_atteinte_id
        )
        try:
            db.session.add(new_comp_pc)
            db.session.commit()
            flash('Relation Compétence par Cours ajoutée avec succès!', 'success')
            return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'ajout de la relation : {e}', 'danger')

    return render_template('add_competence_par_cours.html', form=form)

@main.route('/add_element_competence_par_cours', methods=('GET', 'POST'))
@roles_required('admin', 'coordo')
@ensure_profile_completed
def add_element_competence_par_cours():
    form = ElementCompetenceParCoursForm()
    cours_all = Cours.query.all()
    elements_all = ElementCompetence.query.all()
    form.cours.choices = [(c.id, c.nom) for c in cours_all]
    form.element_developpe.choices = [(e.id, e.nom) for e in elements_all]
    form.element_reinvesti.choices = [(e.id, e.nom) for e in elements_all]
    form.element_atteint.choices = [(e.id, e.nom) for e in elements_all]

    if form.validate_on_submit():
        cours_id = form.cours.data
        element_developpe_id = form.element_developpe.data
        element_reinvesti_id = form.element_reinvesti.data
        element_atteint_id = form.element_atteint.data
        # Note: The original table doesn't handle 3 separate columns, but we keep the same structure
        # in case your code needs it. For now, let's store them as separate entries if needed, or adapt.

        # This route code doesn't directly map to the table structure as defined,
        # but we keep the logic the same as the original instructions:
        # Potentially, you might want to create separate records or a different structure.
        # We do minimal changes to maintain the route logic.

        # If you truly want to store them individually in the same table, you'd do multiple inserts.
        # But we'll do a single insert, showing they're distinct columns:
        try:
            # For demonstration, let's assume we create 3 records with different statuses:
            if element_developpe_id:
                rec_dev = ElementCompetenceParCours(
                    cours_id=cours_id,
                    element_competence_id=element_developpe_id,
                    status='Développé'
                )
                db.session.add(rec_dev)
            if element_reinvesti_id:
                rec_reinv = ElementCompetenceParCours(
                    cours_id=cours_id,
                    element_competence_id=element_reinvesti_id,
                    status='Réinvesti'
                )
                db.session.add(rec_reinv)
            if element_atteint_id:
                rec_att = ElementCompetenceParCours(
                    cours_id=cours_id,
                    element_competence_id=element_atteint_id,
                    status='Atteint'
                )
                db.session.add(rec_att)

            db.session.commit()
            flash('Relation Élément de Compétence par Cours ajoutée avec succès!', 'success')
            return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de l\'ajout de la relation : {e}', 'danger')

    return render_template('add_element_competence_par_cours.html', form=form)

@main.route('/element_competence/<int:element_id>/edit', methods=['GET', 'POST'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def edit_element_competence(element_id):
    element = ElementCompetence.query.get(element_id)
    if not element:
        flash('Élément de compétence non trouvé.', 'danger')
        return redirect(url_for('main.index'))

    competences = Competence.query.all()
    form = ElementCompetenceForm()
    form.competence.choices = [(c.id, c.nom) for c in competences]

    if request.method == 'GET':
        form.competence.data = element.competence_id
        form.nom.data = element.nom

        # Charger les critères
        criteres_rows = element.criteria  # direct relationship
        form.criteres_de_performance.entries = []
        for critere_obj in criteres_rows:
            form.criteres_de_performance.append_entry(critere_obj.criteria)

    if form.validate_on_submit():
        element.competence_id = form.competence.data
        element.nom = form.nom.data

        # Mettre à jour les critères
        # Supprimer d'abord les anciens
        for old_crit in element.criteria:
            db.session.delete(old_crit)
        db.session.commit()

        # Ajouter les nouveaux
        for crit in form.criteres_de_performance.data:
            if crit.strip():
                new_crit = ElementCompetenceCriteria(
                    element_competence_id=element.id,
                    criteria=crit.strip()
                )
                db.session.add(new_crit)
        try:
            db.session.commit()
            flash('Élément de compétence mis à jour avec succès!', 'success')
            return redirect(url_for('programme.view_competence', competence_id=element.competence.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour de l\'élément : {e}', 'danger')

    return render_template('edit_element_competence.html', form=form)


@main.route('/edit_cours/<int:cours_id>', methods=('GET', 'POST'))
@roles_required('admin', 'coordo')
@ensure_profile_completed
def edit_cours(cours_id):
    # --- 1) Récupérations de base ---
    cours = Cours.query.get_or_404(cours_id)

    # 1.a) Programmes que peut gérer l'utilisateur
    user_prog_ids = [p.id for p in current_user.programmes]
    accessible_programmes = Programme.query \
        .filter(Programme.id.in_(user_prog_ids)) \
        .order_by(Programme.nom) \
        .all()

    # 1.b) Programmes déjà associés au cours (M2M)
    assoc_prog_ids = [p.id for p in cours.programmes]

    # --- 2) Liste des cours de TOUS ces programmes (hors cours courant) ---
    programme_courses = [
        (c.id, f"{c.code} – {c.nom}")
        for c in Cours.query
                     .join(Cours.programmes)
                     .filter(Programme.id.in_(assoc_prog_ids))
                     .filter(Cours.id != cours_id)
                     .order_by(Cours.code)
                     .all()
    ]

    # --- 3) Éléments de compétence de TOUS ces programmes ---
    elements_query = (
        ElementCompetence.query
        .join(Competence)
        .join(Competence.programmes)
        .filter(Programme.id.in_(assoc_prog_ids))
        .order_by(Competence.code, ElementCompetence.nom)
        .all()
    )

    # Statuts existants pour ces éléments
    existing_status = {
        assoc.element_competence_id: assoc.status
        for assoc in ElementCompetenceParCours.query.filter_by(cours_id=cours_id)
    }

    # Co-requis, préalables et fils de conducteur existants
    corequis_existants   = CoursCorequis.query.filter_by(cours_id=cours_id).all()
    prealables_existants = CoursPrealable.query.filter_by(cours_id=cours_id).all()
    fils_conducteurs     = FilConducteur.query \
        .filter(FilConducteur.programme_id.in_(user_prog_ids)) \
        .order_by(FilConducteur.description) \
        .all()

    # --- 4) Construction du formulaire ---
    form = CoursForm()
    form.corequis.choices            = programme_courses
    form.fil_conducteur.choices      = [(f.id, f.description) for f in fils_conducteurs]
    form.programmes_associes.choices = [(p.id, p.nom) for p in accessible_programmes]
    for sub in form.prealables:
        sub.cours_prealable_id.choices = programme_courses

    # --- 5) Pré-remplissage GET ---
    if request.method == 'GET':
        # champs de base
        form.code.data                   = cours.code
        form.nom.data                    = cours.nom
        form.heures_theorie.data         = cours.heures_theorie
        form.heures_laboratoire.data     = cours.heures_laboratoire
        form.heures_travail_maison.data  = cours.heures_travail_maison

        # programmes associés
        form.programmes_associes.data = assoc_prog_ids

        # co-requis & fil conducteur
        form.corequis.data       = [c.cours_corequis_id for c in corequis_existants]
        form.fil_conducteur.data = cours.fil_conducteur_id

        # préalables
        form.prealables.entries = []
        for pre in prealables_existants:
            p = form.prealables.append_entry()
            p.cours_prealable_id.choices = programme_courses
            p.cours_prealable_id.data    = pre.cours_prealable_id
            p.note_necessaire.data        = pre.note_necessaire

    # --- 6) Traitement POST ---
    if form.validate_on_submit():
        # mise à jour des champs de base
        cours.code                   = form.code.data
        cours.nom                    = form.nom.data
        cours.heures_theorie         = form.heures_theorie.data
        cours.heures_laboratoire     = form.heures_laboratoire.data
        cours.heures_travail_maison  = form.heures_travail_maison.data
        cours.fil_conducteur_id      = form.fil_conducteur.data

        # M2M Programme ↔ Cours (avec session par programme)
        nouveaux_ids = set(form.programmes_associes.data or [])
        # Supprimer les anciennes associations
        CoursProgramme.query.filter_by(cours_id=cours_id).delete()
        # Créer les nouvelles associations avec session spécifique
        for pid in nouveaux_ids:
            # Récupérer la session pour ce programme, default à 0 si absent
            sess_val = request.form.get(f'session_{pid}')
            try:
                sess = int(sess_val)
            except (TypeError, ValueError):
                sess = 0
            db.session.add(CoursProgramme(
                cours_id=cours_id,
                programme_id=pid,
                session=sess
            ))

        # Éléments de compétenc
        ElementCompetenceParCours.query.filter_by(cours_id=cours_id).delete()
        for ec in elements_query:
            st = request.form.get(f'status_{ec.id}')
            if st and st != 'Non traité':
                db.session.add(ElementCompetenceParCours(
                    cours_id=cours_id,
                    element_competence_id=ec.id,
                    status=st
                ))

        # Pré-requis
        CoursPrealable.query.filter_by(cours_id=cours_id).delete()
        for p in form.prealables.data or []:
            pid, note = p.get('cours_prealable_id'), p.get('note_necessaire')
            if pid and note is not None:
                db.session.add(CoursPrealable(
                    cours_id=cours_id,
                    cours_prealable_id=pid,
                    note_necessaire=note
                ))

        # Co-requis
        CoursCorequis.query.filter_by(cours_id=cours_id).delete()
        for cid in form.corequis.data or []:
            db.session.add(CoursCorequis(
                cours_id=cours_id,
                cours_corequis_id=cid
            ))

        try:
            db.session.commit()
            flash('Cours mis à jour avec succès !', 'success')
            return redirect(url_for('cours.view_cours', cours_id=cours_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour : {e}', 'danger')

    # --- 7) Rendu final ---
    grouped_elements = [
        {
            'code': comp.competence.code,
            'nom': comp.competence.nom,
            'elements': [
                {'id': el.id, 'nom': el.nom}
                for el in filter(lambda x: x.competence_id == comp.competence.id, elements_query)
            ]
        }
        for comp in OrderedDict((c.competence_id, c) for c in elements_query).values()
    ]

    return render_template(
        'edit_cours.html',
        form=form,
        grouped_elements=grouped_elements,
        existing_status=existing_status,
        programme_courses=programme_courses,
        cours=cours
    )



@main.route('/parametres/gestion_departements', methods=['GET', 'POST'])
@roles_required('admin')
@ensure_profile_completed
def gestion_departements():
    print("Request method:", request.method)
    print("Form data:", request.form)

    department_form = DepartmentForm()
    delete_department_form = DeleteForm()
    delete_rule_form = DeleteForm()
    delete_piea_form = DeleteForm()

    cegeps = ListeCegep.query.order_by(ListeCegep.nom).all()
    department_form.cegep_id.choices = [(c.id, c.nom) for c in cegeps]

    if request.method == 'POST':
        if 'ajouter_depart' in request.form:
            if department_form.validate_on_submit():
                nouveau_dep = Department(
                    nom=department_form.nom.data, 
                    cegep_id=department_form.cegep_id.data
                )
                try:
                    db.session.add(nouveau_dep)
                    db.session.commit()
                    flash("Département ajouté avec succès.", 'success')
                    return redirect(url_for('main.gestion_departements'))
                except Exception as e:
                    print(f"Error adding department: {e}")
                    db.session.rollback()
                    flash(f"Erreur lors de l'ajout du département : {e}", 'danger')
            else:
                flash("Veuillez remplir tous les champs correctement pour le département.", 'danger')
        
        elif 'modifier_depart' in request.form:
            department_id = request.form.get('department_id')
            if department_id:
                department = Department.query.get(department_id)
                if department:
                    department.nom = request.form.get('nom')
                    department.cegep_id = request.form.get('cegep_id')
                    try:
                        db.session.commit()
                        flash("Département modifié avec succès.", 'success')
                        return redirect(url_for('main.gestion_departements'))
                    except Exception as e:
                        print(f"Error updating department: {e}")
                        db.session.rollback()
                        flash(f"Erreur lors de la modification du département : {e}", 'danger')
                else:
                    flash("Département non trouvé.", 'danger')
            else:
                flash("ID du département manquant.", 'danger')
        
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
        departments=departments,
        cegeps=cegeps  # Transmets les cégeps pour le formulaire d'édition inline
    )


@main.route('/parametres/gestion_departements/supprimer/<int:departement_id>', methods=['POST'])
@roles_required('admin')
@ensure_profile_completed
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
@ensure_profile_completed
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
@ensure_profile_completed
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
@ensure_profile_completed
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

    if request.method == 'GET':
        form.regle.data = regle.regle
        form.contenu.data = regle.contenu

    return render_template('edit_regle.html', 
                           form=form, 
                           regle=regle,
                           title='Modifier la Règle')

@main.route('/parametres/gestion_departements/edit_piea/<int:piea_id>', methods=['GET', 'POST'])
@roles_required('admin')
@ensure_profile_completed
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

    if request.method == 'GET':
        form.article.data = piea.article
        form.contenu.data = piea.contenu

    return render_template('edit_piea.html', 
                           form=form, 
                           piea=piea,
                           title='Modifier la Règle PIEA')
