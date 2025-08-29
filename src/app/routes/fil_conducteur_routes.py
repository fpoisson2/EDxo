from flask import render_template, redirect, url_for, request, flash, abort
from flask_login import current_user
from ...utils.decorator import roles_required, ensure_profile_completed

from ..forms import FilConducteurForm, DeleteForm
from ..models import db, Programme, FilConducteur
from .routes import main


@main.route('/edit_fil_conducteur/<int:fil_id>', methods=['GET', 'POST'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def edit_fil_conducteur(fil_id):
    fil = db.session.get(FilConducteur, fil_id) or abort(404)
    form = FilConducteurForm(obj=fil)
    # Restreindre la liste des programmes
    if current_user.role == 'admin':
        programmes = Programme.query.all()
    else:
        programmes = Programme.query.filter(Programme.id.in_([p.id for p in current_user.programmes])).all()
        # Vérifier l'accès au fil existant
        if fil.programme_id not in [p.id for p in current_user.programmes]:
            flash("Vous n'avez pas accès à ce programme.", 'danger')
            return redirect(url_for('main.index'))
    form.programme.choices = [(p.id, p.nom) for p in programmes]

    if request.method == 'GET':
        form.programme.data = fil.programme_id

    if form.validate_on_submit():
        # Protéger contre une sélection en dehors des choix autorisés
        allowed_ids = {pid for pid, _ in form.programme.choices}
        if form.programme.data not in allowed_ids:
            flash("Sélection de programme non autorisée.", 'danger')
            return redirect(url_for('main.index'))
        fil.programme_id = form.programme.data
        fil.description = form.description.data
        fil.couleur = form.couleur.data or '#FFFFFF'
        db.session.commit()
        return redirect(url_for('programme.view_programme', programme_id=fil.programme_id))

    return render_template('edit_fil_conducteur.html', form=form, fil=fil)


@main.route('/add_fil_conducteur', methods=['GET', 'POST'])
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
        new_fil = FilConducteur(programme_id=programme_id, description=description, couleur=couleur)
        db.session.add(new_fil)
        db.session.commit()
        return redirect(url_for('programme.view_programme', programme_id=programme_id))

    return render_template('add_fil_conducteur.html', form=form)


@main.route('/delete_fil_conducteur/<int:fil_id>', methods=['POST'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def delete_fil_conducteur(fil_id):
    """Supprime un fil conducteur après validation CSRF et détache les cours associés."""
    form = DeleteForm(prefix=f"fil-{fil_id}")
    if not form.validate_on_submit():
        return redirect(url_for('main.index'))

    fil = db.session.get(FilConducteur, fil_id) or abort(404)
    # Vérifier l'accès pour les non-admin
    if current_user.role != 'admin' and fil.programme_id not in [p.id for p in current_user.programmes]:
        flash("Vous n'avez pas accès à ce programme.", 'danger')
        return redirect(url_for('main.index'))
    programme_id = fil.programme_id

    # Détacher les cours associés pour éviter les contraintes d'intégrité
    for cours in list(fil.cours_list or []):
        cours.fil_conducteur = None

    db.session.delete(fil)
    db.session.commit()

    return redirect(url_for('programme.view_programme', programme_id=programme_id))
