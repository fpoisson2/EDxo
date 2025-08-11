from flask import render_template, redirect, url_for, request, flash
from flask_login import current_user

from ..forms import (
    CoursForm,
    CoursPrealableForm,
    CoursCorequisForm,
    CompetenceParCoursForm,
    ElementCompetenceParCoursForm,
)
from ..models import (
    db,
    Programme,
    ElementCompetence,
    Competence,
    Cours,
    CoursProgramme,
    CoursPrealable,
    CoursCorequis,
    CompetenceParCours,
    ElementCompetenceParCours,
)
from .routes import main
from ...utils.decorator import roles_required, ensure_profile_completed


@main.route('/add_cours', methods=('GET', 'POST'))
@roles_required('admin', 'coordo')
@ensure_profile_completed
def add_cours():
    form = CoursForm()

    accessible_programmes = Programme.query.filter(
        Programme.id.in_([p.id for p in current_user.programmes])
    ).all()

    programme_id = accessible_programmes[0].id if accessible_programmes else None

    selected_programme = request.args.get('programme_id', None)
    if selected_programme is not None:
        try:
            selected_programme = int(selected_programme)
        except ValueError:
            selected_programme = None
    if not selected_programme and accessible_programmes:
        selected_programme = accessible_programmes[0].id

    form.programmes_associes.choices = [(p.id, p.nom) for p in accessible_programmes]

    elements_competence_rows = (
        ElementCompetence.query
        .join(Competence)
        .filter(Competence.programme_id == selected_programme)
        .all()
    )

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
            db.session.add(new_cours)
            db.session.commit()

            programmes_ids = form.programmes_associes.data or []
            for pid in programmes_ids:
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

    elements_competence_dicts = [ec.to_dict() for ec in elements_competence_rows]
    return render_template('add_cours.html', form=form, elements_competence=elements_competence_dicts)


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

        # Note: Persist according to your schema; here we only redirect after commit attempt
        try:
            db.session.commit()
            flash('Association des éléments de compétence mise à jour!', 'success')
            return redirect(url_for('cours_bp.view_cours', cours_id=cours_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour : {e}', 'danger')

    return render_template('add_element_competence_par_cours.html', form=form)


@main.route('/edit_cours/<int:cours_id>', methods=('GET', 'POST'))
@roles_required('admin', 'coordo')
@ensure_profile_completed
def edit_cours(cours_id):
    cours = Cours.query.get_or_404(cours_id)

    user_prog_ids = [p.id for p in current_user.programmes]
    accessible_programmes = Programme.query \
        .filter(Programme.id.in_(user_prog_ids)) \
        .order_by(Programme.nom) \
        .all()

    assoc_prog_ids = [p.id for p in cours.programmes]

    programme_courses = [
        (c.id, f"{c.code} – {c.nom}")
        for c in Cours.query
                     .join(Cours.programmes)
                     .filter(Programme.id.in_(assoc_prog_ids))
                     .filter(Cours.id != cours_id)
                     .order_by(Cours.code)
                     .all()
    ]

    elements_query = (
        ElementCompetence.query
        .join(Competence)
        .join(Competence.programmes)
        .filter(Programme.id.in_(assoc_prog_ids))
        .order_by(Competence.code, ElementCompetence.nom)
        .all()
    )

    existing_status = {
        assoc.element_competence_id: assoc.status
        for assoc in ElementCompetenceParCours.query.filter_by(cours_id=cours_id)
    }

    corequis_existants   = CoursCorequis.query.filter_by(cours_id=cours_id).all()
    prealables_existants = CoursPrealable.query.filter_by(cours_id=cours_id).all()
    fils_conducteurs     = FilConducteur.query \
        .filter(FilConducteur.programme_id.in_(user_prog_ids)) \
        .order_by(FilConducteur.description) \
        .all()

    form = CoursForm()
    form.corequis.choices            = programme_courses
    form.fil_conducteur.choices      = [(f.id, f.description) for f in fils_conducteurs]
    form.programmes_associes.choices = [(p.id, p.nom) for p in accessible_programmes]
    for sub in form.prealables:
        sub.cours_prealable_id.choices = programme_courses

    if request.method == 'GET':
        form.code.data                   = cours.code
        form.nom.data                    = cours.nom
        form.heures_theorie.data         = cours.heures_theorie
        form.heures_laboratoire.data     = cours.heures_laboratoire
        form.heures_travail_maison.data  = cours.heures_travail_maison
        form.programmes_associes.data = assoc_prog_ids
        form.corequis.data       = [c.cours_corequis_id for c in corequis_existants]
        form.fil_conducteur.data = cours.fil_conducteur_id
        form.prealables.entries = []
        for pre in prealables_existants:
            p = form.prealables.append_entry()
            p.cours_prealable_id.choices = programme_courses
            p.cours_prealable_id.data    = pre.cours_prealable_id
            p.note_necessaire.data        = pre.note_necessaire

    if form.validate_on_submit():
        cours.code                   = form.code.data
        cours.nom                    = form.nom.data
        cours.heures_theorie         = form.heures_theorie.data
        cours.heures_laboratoire     = form.heures_laboratoire.data
        cours.heures_travail_maison  = form.heures_travail_maison.data
        cours.fil_conducteur_id      = form.fil_conducteur.data

        nouveaux_ids = set(form.programmes_associes.data or [])
        CoursProgramme.query.filter_by(cours_id=cours_id).delete()
        for pid in nouveaux_ids:
            sess_val = request.form.get(f'session_{pid}')
            try:
                sess = int(sess_val)
            except (TypeError, ValueError):
                sess = 0
            db.session.add(CoursProgramme(cours_id=cours_id, programme_id=pid, session=sess))

        ElementCompetenceParCours.query.filter_by(cours_id=cours_id).delete()
        for ec in elements_query:
            st = request.form.get(f'status_{ec.id}')
            if st and st != 'Non traité':
                db.session.add(ElementCompetenceParCours(cours_id=cours_id, element_competence_id=ec.id, status=st))

        CoursPrealable.query.filter_by(cours_id=cours_id).delete()
        for p in form.prealables.data or []:
            pid, note = p.get('cours_prealable_id'), p.get('note_necessaire')
            if pid and note is not None:
                db.session.add(CoursPrealable(cours_id=cours_id, cours_prealable_id=pid, note_necessaire=note))

        CoursCorequis.query.filter_by(cours_id=cours_id).delete()
        for cid in form.corequis.data or []:
            db.session.add(CoursCorequis(cours_id=cours_id, cours_corequis_id=cid))

        try:
            db.session.commit()
            flash('Cours mis à jour avec succès !', 'success')
            return redirect(url_for('cours.view_cours', cours_id=cours_id))
        except Exception as e:
            db.session.rollback()
            flash(f'Erreur lors de la mise à jour : {e}', 'danger')

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

    return render_template('edit_cours.html', form=form, grouped_elements=grouped_elements, existing_status=existing_status, programme_courses=programme_courses, cours=cours)
