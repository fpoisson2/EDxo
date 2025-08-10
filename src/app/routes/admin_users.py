from flask import render_template, redirect, url_for, request, flash, jsonify
from flask_login import current_user, login_required

from ..models import db, User, Programme
from ..forms import CreateUserForm, DeleteUserForm, CreditManagementForm, EditUserForm
from .routes import main
from utils.decorator import role_required, ensure_profile_completed
from utils import get_all_cegeps, get_cegep_details_data
from werkzeug.security import generate_password_hash


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

    user_programmes = [prog.id for prog in user.programmes]
    form = EditUserForm()
    cegeps = get_all_cegeps()
    form.cegep_id.choices = [(0, 'Aucun')] + [(c['id'], c['nom']) for c in cegeps]

    if request.method == 'GET':
        form.user_id.data = user.id
        form.username.data = user.username
        form.email.data = user.email
        form.role.data = user.role
        form.cegep_id.data = user.cegep_id if user.cegep_id else 0
        form.department_id.data = user.department_id if user.department_id else 0
        form.openai_key.data = user.openai_key

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
            user.email = form.email.data
            if form.password.data:
                user.password = generate_password_hash(form.password.data, method='scrypt')
            user.role = form.role.data
            user.cegep_id = form.cegep_id.data if form.cegep_id.data != 0 else None
            user.department_id = form.department_id.data if form.department_id.data != 0 else None
            user.openai_key = form.openai_key.data

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

