# app.py
import logging
from datetime import datetime

from collections import OrderedDict

import bleach
import markdown
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify, session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func  # Add this at the top with your other imports
from sqlalchemy import text
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
from ...extensions import limiter
from ...utils.decorator import role_required, roles_required, ensure_profile_completed
from ...utils.decorator import public_route
from ...utils import (
    get_all_cegeps,
    get_cegep_details_data,
    send_reset_email,
)
from ...utils.recaptcha import verify_recaptcha

logger = logging.getLogger(__name__)

main = Blueprint('main', __name__)

# Public: Version endpoint
@main.route('/version')
@public_route
def version():
    from ...config.version import __version__
    return jsonify({'version': __version__})

# Public: Health endpoint
@main.route('/health')
@public_route
def health():
    try:
        from ..models import db
        db.session.execute(text('SELECT 1'))
        db.session.commit()
        return jsonify({'status': 'ok'}), 200
    except Exception:
        return jsonify({'status': 'degraded'}), 200


@main.route('/help/api')
@login_required
def api_help_page():
    return render_template('help/api.html')

@main.route('/forgot-password', methods=['GET', 'POST'])
@public_route
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
        if not verify_recaptcha(recaptcha_token):
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
@public_route
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
        if not verify_recaptcha(recaptcha_token):
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
    from ...celery_app import celery
    from celery.result import AsyncResult

    res = AsyncResult(task_id, app=celery)
    current_state = res.state
    # Récupération du meta si présent, sinon message par défaut
    meta = res.info
    if isinstance(meta, dict):
        current_message = meta.get('message', '')
    elif meta is None:
        meta = {}
        current_message = ''
    else:
        # Peut être une Exception (ex.: NotRegistered)
        current_message = str(meta)

    # En mode succès, certains backends peuvent ne pas exposer res.result ;
    # on se rabat alors sur meta pour éviter un résultat vide côté client.
    result_payload = res.result if current_state == 'SUCCESS' else None
    if current_state == 'SUCCESS' and not result_payload:
        result_payload = meta if isinstance(meta, dict) else None

    logger.info("Task %s state: %s, meta: %s", task_id, current_state, meta)

    return jsonify({
        'state': current_state,
        'message': current_message,
        'meta': meta,
        'result': result_payload
    })



@main.route('/clear_task_id', methods=['POST'])
def clear_task_id():
    """Retire l'identifiant de tâche de la session sans supprimer
    immédiatement le résultat côté Celery."""
    session.pop('task_id', None)
    return jsonify(success=True)

## moved to admin_cegeps.py

# Define the markdown filter
@main.app_template_filter('markdown')
def markdown_filter(text):
    return markdown.markdown(text)

## moved to programmes_cegep.py

## moved to admin_programmes.py

## moved to admin_programmes.py

## moved to admin_programmes.py

@main.route('/get_credit_balance', methods=['GET'])
@public_route
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

## moved to programmes_cegep.py

@main.route('/login', methods=['GET', 'POST'])
@public_route
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

        if not verify_recaptcha(recaptcha_token):
            flash("La vérification reCAPTCHA a échoué. Veuillez réessayer.", "danger")
            return redirect(url_for('main.login'))

        # Authentification de l'utilisateur
        username = form.username.data.lower()
        password = form.password.data

        user_row = User.query.filter(func.lower(User.username) == username).first()
        if user_row and check_password_hash(user_row.password, password):
            from datetime import timezone
            user_row.last_login = datetime.now(timezone.utc)
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

## moved to admin_users.py

## moved to admin_users.py


## moved to admin_users.py

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


## moved to admin_programmes.py

## moved to competences_management.py


## moved to competences_management.py



## moved to fil_conducteur_routes.py


## moved to courses_management.py


## moved to courses_management.py

## moved to courses_management.py

## moved to courses_management.py

## moved to courses_management.py

## moved to competences_management.py


## moved to courses_management.py



from flask import redirect
@main.route('/parametres/gestion_departements', methods=['GET', 'POST'])
def gestion_departements():
    return redirect(url_for('settings.gestion_departements'))


@main.route('/parametres/gestion_departements/supprimer/<int:departement_id>', methods=['POST'])
def supprimer_departement(departement_id):
    return redirect(url_for('settings.supprimer_departement', departement_id=departement_id))

@main.route('/parametres/gestion_departements/supprimer_regle/<int:regle_id>', methods=['POST'])
def supprimer_regle(regle_id):
    return redirect(url_for('settings.supprimer_regle', regle_id=regle_id))

@main.route('/parametres/gestion_departements/supprimer_piea/<int:piea_id>', methods=['POST'])
def supprimer_piea(piea_id):
    return redirect(url_for('settings.supprimer_piea', piea_id=piea_id))

@main.route('/parametres/gestion_departements/edit_regle/<int:regle_id>', methods=['GET', 'POST'])
def edit_regle(regle_id):
    return redirect(url_for('settings.edit_regle', regle_id=regle_id))

@main.route('/parametres/gestion_departements/edit_piea/<int:piea_id>', methods=['GET', 'POST'])
def edit_piea(piea_id):
    return redirect(url_for('settings.edit_piea', piea_id=piea_id))
