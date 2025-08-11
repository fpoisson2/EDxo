from flask import render_template, request, redirect, url_for, flash, jsonify

from ..forms import ProgrammeForm
from ..models import db, Department, ListeProgrammeMinisteriel, Programme
from .routes import main
from ...utils.decorator import roles_required, role_required
from ...utils import get_all_cegeps


@main.route('/gestion_programmes_cegep', methods=['GET', 'POST'])
@roles_required('admin')
def gestion_programmes_cegep():
    cegeps = get_all_cegeps()
    departments = [(d.id, d.nom) for d in Department.query.order_by(Department.nom).all()]
    programmes_ministeriels = [(0, 'Aucun')] + [
        (pm.id, pm.nom) for pm in ListeProgrammeMinisteriel.query.order_by(ListeProgrammeMinisteriel.nom).all()
    ]

    form = ProgrammeForm()
    form.cegep_id.choices = [(c['id'], c['nom']) for c in cegeps]
    form.department_id.choices = departments
    form.liste_programme_ministeriel_id.choices = programmes_ministeriels

    selected_cegep = request.args.get('cegep_id', type=int)
    if not selected_cegep and form.cegep_id.choices:
        selected_cegep = form.cegep_id.choices[0][0]
    form.cegep_id.data = selected_cegep

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
            return redirect(url_for('main.gestion_programmes_cegep', cegep_id=form.cegep_id.data))
        except Exception as e:
            db.session.rollback()
            flash("Erreur lors de l'ajout du programme: " + str(e), "danger")

    programmes = Programme.query.filter_by(cegep_id=selected_cegep).all() if selected_cegep else []

    return render_template(
        'gestion_programmes_cegep.html',
        form=form,
        programmes=programmes,
        selected_cegep=selected_cegep,
        cegeps=cegeps
    )


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
