from flask import render_template, redirect, url_for, request
from flask_login import current_user
from ...utils.decorator import roles_required, ensure_profile_completed

from ..forms import FilConducteurForm, DeleteForm
from ..models import db, Programme, FilConducteur
from .routes import main


@main.route('/edit_fil_conducteur/<int:fil_id>', methods=['GET', 'POST'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def edit_fil_conducteur(fil_id):
    fil = FilConducteur.query.get_or_404(fil_id)
    form = FilConducteurForm(obj=fil)
    programmes = Programme.query.all()
    form.programme.choices = [(p.id, p.nom) for p in programmes]

    if request.method == 'GET':
        form.programme.data = fil.programme_id

    if form.validate_on_submit():
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

    fil = FilConducteur.query.get_or_404(fil_id)
    programme_id = fil.programme_id

    # Détacher les cours associés pour éviter les contraintes d'intégrité
    for cours in list(fil.cours_list or []):
        cours.fil_conducteur = None

    db.session.delete(fil)
    db.session.commit()

    return redirect(url_for('programme.view_programme', programme_id=programme_id))
