from flask import render_template, redirect, url_for, flash

from ..models import db, ListeCegep
from ..forms import CegepForm
from .routes import main


@main.route('/gestion_cegeps', methods=['GET', 'POST'])
def gestion_cegeps():
    form = CegepForm()

    if form.validate_on_submit():
        nouveau_cegep = ListeCegep(
            nom=form.nom.data,
            type=form.type.data,
            region=form.region.data
        )
        db.session.add(nouveau_cegep)
        db.session.commit()
        flash('Cégep ajouté avec succès!', 'success')
        return redirect(url_for('main.gestion_cegeps'))

    cegeps = ListeCegep.query.all()
    return render_template('gestion_cegeps.html', form=form, cegeps=cegeps)


@main.route('/supprimer_cegep/<int:id>', methods=['POST'])
def supprimer_cegep(id):
    cegep = db.session.get(ListeCegep, id) or abort(404)
    db.session.delete(cegep)
    db.session.commit()
    flash('Cégep supprimé avec succès!', 'success')
    return redirect(url_for('main.gestion_cegeps'))


@main.route('/modifier_cegep/<int:id>', methods=['GET', 'POST'])
def modifier_cegep(id):
    cegep = db.session.get(ListeCegep, id) or abort(404)
    form = CegepForm(obj=cegep)

    if form.validate_on_submit():
        cegep.nom = form.nom.data
        cegep.type = form.type.data
        cegep.region = form.region.data
        db.session.commit()
        flash('Cégep modifié avec succès!', 'success')
        return redirect(url_for('main.gestion_cegeps'))

    return render_template('modifier_cegep.html', form=form, cegep=cegep)
