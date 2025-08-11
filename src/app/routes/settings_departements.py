from flask import render_template, redirect, url_for, request, flash
from flask_login import login_required

from .settings import settings_bp
from ...utils.decorator import roles_required, ensure_profile_completed

from ..forms import DepartmentForm, DepartmentRegleForm, DepartmentPIEAForm, DeleteForm
from ..models import db, ListeCegep, Department, DepartmentRegles, DepartmentPIEA


@settings_bp.route('/gestion_departements', methods=['GET', 'POST'])
@roles_required('admin')
@login_required
@ensure_profile_completed
def gestion_departements():
    department_form = DepartmentForm()
    delete_department_form = DeleteForm()
    delete_rule_form = DeleteForm()
    delete_piea_form = DeleteForm()

    cegeps = ListeCegep.query.order_by(ListeCegep.nom).all()
    department_form.cegep_id.choices = [(c.id, c.nom) for c in cegeps]

    if request.method == 'POST':
        if 'ajouter_depart' in request.form:
            if department_form.validate_on_submit():
                nouveau_dep = Department(nom=department_form.nom.data, cegep_id=department_form.cegep_id.data)
                try:
                    db.session.add(nouveau_dep)
                    db.session.commit()
                    flash("Département ajouté avec succès.", 'success')
                    return redirect(url_for('settings.gestion_departements'))
                except Exception as e:
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
                        return redirect(url_for('settings.gestion_departements'))
                    except Exception as e:
                        db.session.rollback()
                        flash(f"Erreur lors de la modification du département : {e}", 'danger')
                else:
                    flash("Département non trouvé.", 'danger')
            else:
                flash("ID du département manquant.", 'danger')

        if 'ajouter_regle' in request.form:
            department_id = request.form.get('department_id')
            regle_form = DepartmentRegleForm()
            if regle_form.regle.data and regle_form.contenu.data:
                department = Department.query.get(department_id)
                if department:
                    nouvelle_regle = DepartmentRegles(regle=regle_form.regle.data, contenu=regle_form.contenu.data, department_id=department.id)
                    db.session.add(nouvelle_regle)
                    try:
                        db.session.commit()
                        flash("Règle ajoutée avec succès.", 'success')
                        return redirect(url_for('settings.gestion_departements'))
                    except Exception as e:
                        db.session.rollback()
                        flash(f"Erreur lors de l'ajout de la règle : {e}", 'danger')
                else:
                    flash("Département non trouvé.", 'danger')
            else:
                flash("Veuillez remplir tous les champs.", 'danger')

        elif 'ajouter_piea' in request.form:
            department_id = request.form.get('department_id')
            piea_form = DepartmentPIEAForm()
            if piea_form.article.data and piea_form.contenu.data:
                department = Department.query.get(department_id)
                if department:
                    nouvelle_piea = DepartmentPIEA(article=piea_form.article.data, contenu=piea_form.contenu.data, department_id=department.id)
                    db.session.add(nouvelle_piea)
                    try:
                        db.session.commit()
                        flash("Règle de PIEA ajoutée avec succès.", 'success')
                        return redirect(url_for('settings.gestion_departements'))
                    except Exception as e:
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
        cegeps=cegeps
    )


@settings_bp.route('/gestion_departements/supprimer/<int:departement_id>', methods=['POST'])
@roles_required('admin')
@login_required
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
    return redirect(url_for('settings.gestion_departements'))


@settings_bp.route('/gestion_departements/supprimer_regle/<int:regle_id>', methods=['POST'])
@roles_required('admin')
@login_required
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
    return redirect(url_for('settings.gestion_departements'))


@settings_bp.route('/gestion_departements/supprimer_piea/<int:piea_id>', methods=['POST'])
@roles_required('admin')
@login_required
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
    return redirect(url_for('settings.gestion_departements'))


@settings_bp.route('/gestion_departements/edit_regle/<int:regle_id>', methods=['GET', 'POST'])
@roles_required('admin')
@login_required
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
            return redirect(url_for('settings.gestion_departements'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour de la règle : {e}', 'danger')
            return redirect(url_for('settings.gestion_departements'))

    if request.method == 'GET':
        form.regle.data = regle.regle
        form.contenu.data = regle.contenu

    return render_template('edit_regle.html', form=form, regle=regle, title='Modifier la Règle')


@settings_bp.route('/gestion_departements/edit_piea/<int:piea_id>', methods=['GET', 'POST'])
@roles_required('admin')
@login_required
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
            return redirect(url_for('settings.gestion_departements'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour de la règle PIEA : {e}', 'danger')
            return redirect(url_for('settings.gestion_departements'))

    if request.method == 'GET':
        form.article.data = piea.article
        form.contenu.data = piea.contenu

    return render_template('edit_piea.html', form=form, piea=piea, title='Modifier la Règle PIEA')
