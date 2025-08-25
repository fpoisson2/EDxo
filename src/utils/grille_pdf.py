from collections import defaultdict
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle


def generate_programme_grille_pdf(programme):
    """Génère un PDF représentant la grille de cours d'un programme.

    Les cours sont regroupés par numéro de session et disposés dans un tableau.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))

    sessions = defaultdict(list)
    for cours in programme.cours:
        session_num = cours.sessions_map.get(programme.id)
        if session_num:
            sessions[session_num].append(cours)

    if not sessions:
        doc.build([])
        pdf = buffer.getvalue()
        buffer.close()
        return pdf

    max_session = max(sessions.keys())
    header = [f"Session {i}" for i in range(1, max_session + 1)]
    data = [header]

    max_rows = max(len(v) for v in sessions.values())
    styles = getSampleStyleSheet()
    for i in range(max_rows):
        row = []
        for session in range(1, max_session + 1):
            cours_list = sessions.get(session, [])
            if i < len(cours_list):
                c = cours_list[i]
                text = f"{c.code} - {c.nom}"
                row.append(Paragraph(text, styles['Normal']))
            else:
                row.append('')
        data.append(row)

    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))

    doc.build([table])
    pdf = buffer.getvalue()
    buffer.close()
    return pdf
