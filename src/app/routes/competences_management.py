import bleach
from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user

from ..forms import CompetenceForm, ElementCompetenceForm
from ..models import db, Programme, Competence, ElementCompetence, ElementCompetenceCriteria
from .routes import main
from ...utils.decorator import roles_required, ensure_profile_completed


@main.route('/add_competence', methods=['GET', 'POST'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def add_competence():
    form = CompetenceForm()
    if current_user.role == 'admin':
        programmes = Programme.query.all()
    elif current_user.role == 'coordo':
        programmes = current_user.programmes
    else:
        programmes = []

    # Utilise le champ multi-sélection "programmes" pour rester cohérent
    form.programmes.choices = [(p.id, p.nom) for p in programmes]

    if form.validate_on_submit():
        programme_ids = form.programmes.data or []
        # Sélectionne le premier programme comme programme principal (colonne programme_id)
        programme_id = programme_ids[0] if programme_ids else None
        code = form.code.data
        nom = form.nom.data
        criteria_de_performance = form.criteria_de_performance.data or ""
        contexte_de_realisation = form.contexte_de_realisation.data or ""

        allowed_tags = ['ul', 'ol', 'li', 'strong', 'em', 'p', 'br', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']
        allowed_attributes = {'a': ['href', 'title', 'target']}

        criteria_clean = bleach.clean(criteria_de_performance, tags=allowed_tags, attributes=allowed_attributes, strip=True)
        context_clean = bleach.clean(contexte_de_realisation, tags=allowed_tags, attributes=allowed_attributes, strip=True)

        new_comp = Competence(
            programme_id=programme_id,
            code=code,
            nom=nom,
            criteria_de_performance=criteria_clean,
            contexte_de_realisation=context_clean
        )
        try:
            db.session.add(new_comp)
            db.session.flush()
            # Associe la compétence aux programmes sélectionnés (relation many-to-many)
            if programme_ids:
                new_comp.programmes = Programme.query.filter(Programme.id.in_(programme_ids)).all()
            db.session.commit()
            flash('Compétence ajoutée avec succès!', 'success')
            return redirect(url_for('programme.view_programme', programme_id=programme_id))
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de l'ajout de la compétence : {e}", 'danger')

    return render_template('add_competence.html', form=form)


@main.route('/add_element_competence', methods=['GET', 'POST'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def add_element_competence():
    form = ElementCompetenceForm()

    if current_user.role == 'admin':
        competences = Competence.query.all()
    elif current_user.role == 'coordo':
        allowed_programmes = [p.id for p in current_user.programmes]
        competences = Competence.query.filter(Competence.programme_id.in_(allowed_programmes)).all()
    else:
        competences = []

    form.competence.choices = [(c.id, f"{c.code} - {c.nom}") for c in competences]

    if form.validate_on_submit():
        competence_id = form.competence.data
        nom = form.nom.data
        criteres = form.criteres_de_performance.data

        new_elem = ElementCompetence(competence_id=competence_id, nom=nom)
        try:
            db.session.add(new_elem)
            db.session.commit()
            for crit in criteres:
                if crit.strip():
                    new_crit = ElementCompetenceCriteria(element_competence_id=new_elem.id, criteria=crit.strip())
                    db.session.add(new_crit)
            db.session.commit()
            flash("Élément de compétence et critères de performance ajoutés avec succès!", 'success')
            return redirect(url_for('programme.view_programme', programme_id=new_elem.competence.programme_id))
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de l'ajout de l'élément de compétence : {e}", 'danger')

    return render_template('add_element_competence.html', form=form)


@main.route('/element_competence/<int:element_id>/edit', methods=['GET', 'POST'])
@roles_required('admin', 'coordo')
@ensure_profile_completed
def edit_element_competence(element_id):
    element = db.session.get(ElementCompetence, element_id)
    if not element:
        flash('Élément de compétence non trouvé.', 'danger')
        return redirect(url_for('main.index'))

    competences = Competence.query.all()
    form = ElementCompetenceForm()
    form.competence.choices = [(c.id, c.nom) for c in competences]

    if request.method == 'GET':
        form.competence.data = element.competence_id
        form.nom.data = element.nom
        criteres_rows = element.criteria
        form.criteres_de_performance.entries = []
        for critere_obj in criteres_rows:
            form.criteres_de_performance.append_entry(critere_obj.criteria)

    if form.validate_on_submit():
        element.competence_id = form.competence.data
        element.nom = form.nom.data
        for old_crit in element.criteria:
            db.session.delete(old_crit)
        db.session.commit()

        for crit in form.criteres_de_performance.data:
            if crit.strip():
                new_crit = ElementCompetenceCriteria(element_competence_id=element.id, criteria=crit.strip())
                db.session.add(new_crit)
        try:
            db.session.commit()
            flash('Élément de compétence mis à jour avec succès!', 'success')
            return redirect(url_for('programme.view_competence', competence_id=element.competence.id))
        except Exception as e:
            db.session.rollback()
            flash(f"Erreur lors de la mise à jour de l'élément : {e}", 'danger')

    return render_template('edit_element_competence.html', form=form)
