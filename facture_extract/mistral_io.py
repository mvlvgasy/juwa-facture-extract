"""Tout ce qui parle a Mistral, et rien d'autre.

Le fournisseur de modeles est volontairement isole dans ce seul module. Le
reste du programme ne connait que des structures Python : changer de
fournisseur revient a reecrire ce fichier, sans toucher au schema, aux
controles, a la CLI ni a l'interface.

Le pipeline se fait en deux temps plutot qu'en un appel unique :

1. OCR    : le document devient du texte et des tableaux. C'est de la
            perception, et l'API renvoie au passage un score de confiance.
2. Extraction : ce texte devient une structure typee, via une sortie
            structuree contrainte par le schema Pydantic.

Deux temps plutot qu'un, pour trois raisons : on peut montrer et auditer le
texte intermediaire, on peut rejouer l'extraction sans repayer l'OCR, et une
erreur de lecture se distingue d'une erreur de structuration.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path

from mistralai.client import Mistral

from .schema import FactureLue

MODELE_OCR = "mistral-ocr-latest"
MODELE_EXTRACTION = "mistral-small-latest"

_CONSIGNE = """\
Tu recois le texte d'une facture fournisseur, obtenu par OCR, suivi de ses \
tableaux. Ta seule tache est de reporter ce qui est ecrit.

Regles imperatives :
- Ne calcule jamais une valeur. Si le total HT est imprime, reporte-le tel \
quel, meme s'il ne correspond pas a la somme des lignes. La verification des \
totaux est faite ailleurs, par du code.
- N'invente jamais. Si une information ne figure pas dans le document, laisse \
le champ a null.
- Distingue deux situations. Si un champ est absent du document, laisse-le a \
null sans rien signaler. Si un champ est present mais que tu ne parviens pas a \
le lire de facon sure, laisse-le a null ET ajoute son nom dans \
`champs_illisibles`.
- Recopie les libelles et les numeros caractere pour caractere, sans corriger \
l'orthographe, sans developper les abreviations, sans reformuler.
- Les montants sont des nombres decimaux au point. Convertis « 1 234,56 EUR » \
en 1234.56.
- La date va au format AAAA-MM-JJ. Si le document est au format JJ/MM/AAAA, \
convertis. Si l'annee est ambigue, laisse null et signale-le.
- Signale dans `remarques` toute anomalie de lecture : texte corrompu, zone \
raturee, tampon illisible, colonne tronquee.
"""


@dataclass
class MotLu:
    """Un fragment de texte et la confiance que l'OCR lui accorde."""
    texte: str
    confiance: float


@dataclass
class ResultatOcr:
    texte: str
    tableaux: list[str]
    confiance_moyenne: float | None
    confiance_minimum: float | None
    modele: str
    mots: list[MotLu]

    @property
    def texte_complet(self) -> str:
        if not self.tableaux:
            return self.texte
        blocs = "\n\n".join(f"[Tableau {i + 1}]\n{t}" for i, t in enumerate(self.tableaux))
        return f"{self.texte}\n\n{blocs}"


def cle_api() -> str:
    """Lit la cle dans l'environnement, avec repli sur un fichier .env local.

    La cle n'est jamais ecrite dans le code ni versionnee : cf. .env.example.
    """
    cle = os.environ.get("MISTRAL_API_KEY")
    if cle:
        return cle.strip()

    for chemin in (Path.cwd() / ".env", Path(__file__).resolve().parents[1] / ".env"):
        if chemin.exists():
            for ligne in chemin.read_text(encoding="utf-8", errors="ignore").splitlines():
                ligne = ligne.strip()
                if ligne.startswith("MISTRAL_API_KEY=") and not ligne.startswith("#"):
                    return ligne.split("=", 1)[1].strip().strip('"').strip("'")

    raise RuntimeError(
        "MISTRAL_API_KEY introuvable. Definis la variable d'environnement, ou cree "
        "un fichier .env a partir de .env.example. Voir le README."
    )


def client() -> Mistral:
    return Mistral(api_key=cle_api())


def ocr(pdf: Path, cli: Mistral | None = None) -> ResultatOcr:
    """Envoie le PDF a l'OCR et rend le texte, les tableaux et la confiance.

    Le fichier est transmis en base64 plutot qu'uploade : le document ne
    survit pas a l'appel cote fournisseur, ce qui evite d'avoir a gerer une
    suppression ulterieure.

    `table_format="markdown"` est demande explicitement, car les tableaux ne
    figurent PAS dans le markdown de la page : celle-ci ne contient qu'une
    reference du type [tbl-0.md]. Le contenu reel est dans `page.tables`. Ne
    lire que le markdown ferait perdre toutes les lignes de produits.
    """
    cli = cli or client()
    donnees = base64.b64encode(pdf.read_bytes()).decode()

    reponse = cli.ocr.process(
        model=MODELE_OCR,
        document={"type": "document_url",
                  "document_url": f"data:application/pdf;base64,{donnees}"},
        table_format="markdown",
        # Granularite au mot, et non a la page : c'est ce qui permet de reperer
        # une valeur precise que l'OCR a devinee. Une confiance moyenne de page
        # reste excellente meme quand un champ isole est invente.
        confidence_scores_granularity="word",
    )

    textes, tableaux, moyennes, minima, mots = [], [], [], [], []
    for page in reponse.pages:
        if page.markdown:
            textes.append(page.markdown)
        for t in (page.tables or []):
            contenu = getattr(t, "content", None)
            if contenu:
                tableaux.append(str(contenu))
        scores = getattr(page, "confidence_scores", None)
        if scores is not None:
            if getattr(scores, "average_page_confidence_score", None) is not None:
                moyennes.append(scores.average_page_confidence_score)
            if getattr(scores, "minimum_page_confidence_score", None) is not None:
                minima.append(scores.minimum_page_confidence_score)
            for m in (getattr(scores, "word_confidence_scores", None) or []):
                texte_mot = getattr(m, "text", None)
                score = getattr(m, "confidence", None)
                if texte_mot and score is not None:
                    mots.append(MotLu(texte=texte_mot.strip(), confiance=float(score)))

    return ResultatOcr(
        texte="\n\n".join(textes),
        tableaux=tableaux,
        confiance_moyenne=sum(moyennes) / len(moyennes) if moyennes else None,
        confiance_minimum=min(minima) if minima else None,
        modele=reponse.model or MODELE_OCR,
        mots=mots,
    )


def extraire(texte: str, cli: Mistral | None = None) -> FactureLue:
    """Transforme le texte OCR en structure typee.

    La sortie est contrainte par le schema `FactureLue` : le modele ne peut
    pas renvoyer un champ hors schema ni un type inattendu, la validation est
    faite par le SDK avant de nous rendre la main. Temperature a 0 pour
    limiter la variabilite entre deux executions sur le meme document.
    """
    cli = cli or client()
    reponse = cli.chat.parse(
        model=MODELE_EXTRACTION,
        response_format=FactureLue,
        temperature=0,
        messages=[
            {"role": "system", "content": _CONSIGNE},
            {"role": "user", "content": texte},
        ],
    )
    resultat = reponse.choices[0].message.parsed
    if resultat is None:
        raise RuntimeError("Le modele n'a pas renvoye de structure exploitable.")
    return resultat
