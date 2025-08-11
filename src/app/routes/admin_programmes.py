from flask import render_template, redirect, url_for, flash

from ..models import db, ListeProgrammeMinisteriel
from ..forms import ProgrammeMinisterielForm, ProgrammeForm
from .routes import main
from ...utils.decorator import roles_required
from flask import request
from ..models import Programme


@main.route('/gestion_programmes_ministeriels', methods=['GET', 'POST'])
@roles_required('admin')
def gestion_programmes_ministeriels():
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


@main.route('/add_programme', methods=('GET', 'POST'))
@roles_required('admin')
def add_programme():
    form = ProgrammeForm()
    if form.validate_on_submit():
        nom = form.nom.data
        new_prog = Programme(nom=nom, department_id=1)
        try:
            db.session.add(new_prog)
            db.session.commit()
            flash('Programme ajouté avec succès!')
            return redirect(url_for('main.index'))
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de l'ajout du programme : {e}", 'danger')
    return render_template('add_programme.html', form=form)
