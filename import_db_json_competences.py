import json
from sqlalchemy import create_engine, Column, Integer, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Création de la base de données SQLite
engine = create_engine('sqlite:///programme.db')
Base = declarative_base()

# Modèles de base de données
class Competence(Base):
    __tablename__ = 'Competence'
    id = Column(Integer, primary_key=True)
    programme_id = Column(Integer, nullable=False)
    code = Column(Text, nullable=False)
    nom = Column(Text, nullable=False)
    contexte_de_realisation = Column(Text, nullable=True)
    criteria_de_performance = Column(Text, nullable=True)
    elements = relationship("ElementCompetence", back_populates="competence", cascade="all, delete-orphan")

class ElementCompetence(Base):
    __tablename__ = 'ElementCompetence'
    id = Column(Integer, primary_key=True)
    competence_id = Column(Integer, ForeignKey('Competence.id'), nullable=False)
    nom = Column(Text, nullable=False)
    criteres = relationship("ElementCompetenceCriteria", back_populates="element", cascade="all, delete-orphan")
    competence = relationship("Competence", back_populates="elements")

class ElementCompetenceCriteria(Base):
    __tablename__ = 'ElementCompetenceCriteria'
    id = Column(Integer, primary_key=True)
    element_competence_id = Column(Integer, ForeignKey('ElementCompetence.id'), nullable=False)
    criteria = Column(Text, nullable=False)
    element = relationship("ElementCompetence", back_populates="criteres")

# Création des tables
Base.metadata.create_all(engine)

# Création de la session
Session = sessionmaker(bind=engine)
session = Session()

# Charger le JSON et insérer les données
with open('competences_structure.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

programme_id = 3  # À ajuster selon ton contexte

for comp in data['competences']:
    competence = Competence(
        programme_id=programme_id,  # Ajout de programme_id
        code=comp['code'],
        nom=comp['objectif']['enonce'],
        contexte_de_realisation=comp['objectif']['contexte_realisation'],
        criteria_de_performance=comp['objectif']['criteres_performance_ensemble']
    )
    session.add(competence)

    for elem in comp['elements_competence']:
        element = ElementCompetence(
            nom=elem['titre'],
            competence=competence
        )
        session.add(element)

        for crit in elem['criteres_performance']:
            criteria = ElementCompetenceCriteria(
                criteria=crit,
                element=element
            )
            session.add(criteria)

# Commit des changements
session.commit()

print("Les données ont été insérées avec succès !")
