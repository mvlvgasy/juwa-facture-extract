"""Assemblage : OCR, extraction, controles, document final.

C'est le seul endroit qui connait l'enchainement complet. Il tient en une
fonction, volontairement lisible de haut en bas, parce que c'est elle qu'on
parcourt quand on veut comprendre ce que fait le programme.
"""

from __future__ import annotations

import time
from pathlib import Path

from mistralai.client import Mistral

from . import mistral_io
from .checks import controler, statut_global
from .schema import (
    Avertissement,
    EtatChamp,
    Facture,
    FactureLue,
    Gravite,
    LigneProduit,
    Meta,
)

CHAMPS_SIMPLES = ("nom_fournisseur", "date", "numero_facture", "total_HT", "total_TTC")

# Seuil de confiance OCR moyenne en dessous duquel on demande une relecture
# humaine. Cale empiriquement : les documents propres du jeu de test sortent
# a 0,98, un scan degrade devrait tomber nettement plus bas.
SEUIL_CONFIANCE_OCR = 0.85


def _etats_champs(lue: FactureLue) -> dict[str, EtatChamp]:
    """Determine, champ par champ, pourquoi il vaut ce qu'il vaut.

    Un champ renseigne est `lu`. Un champ vide que le modele a signale comme
    non lisible est `illisible`. Un champ vide non signale est `absent`, donc
    considere comme legitimement inexistant sur ce document.
    """
    signales = {c.strip() for c in lue.champs_illisibles}
    etats: dict[str, EtatChamp] = {}
    for champ in CHAMPS_SIMPLES:
        valeur = getattr(lue, champ)
        if valeur not in (None, ""):
            etats[champ] = EtatChamp.LU
        elif champ in signales:
            etats[champ] = EtatChamp.ILLISIBLE
        else:
            etats[champ] = EtatChamp.ABSENT
    etats["lignes_produits"] = EtatChamp.LU if lue.lignes_produits else (
        EtatChamp.ILLISIBLE if "lignes_produits" in signales else EtatChamp.ABSENT)
    return etats


def traiter(pdf: Path, cli: Mistral | None = None) -> Facture:
    """Traite une facture de bout en bout et rend le document final."""
    debut = time.perf_counter()
    cli = cli or mistral_io.client()

    # 1. Perception : le document devient du texte.
    resultat_ocr = mistral_io.ocr(pdf, cli)

    # 2. Structuration : le texte devient une structure typee.
    lue = mistral_io.extraire(resultat_ocr.texte_complet, cli)

    # 3. Le total de chaque ligne est calcule ici, jamais lu. Une valeur lue et
    #    une valeur calculee ne se melangent pas.
    lignes = [
        LigneProduit(
            designation=l.designation,
            quantite=l.quantite,
            prix_unitaire=l.prix_unitaire,
            total_ligne=(round(l.quantite * l.prix_unitaire, 2)
                         if l.quantite is not None and l.prix_unitaire is not None else None),
        )
        for l in lue.lignes_produits
    ]

    # 4. Verifications deterministes.
    controles, avertissements = controler(
        lignes=lignes,
        total_ht=lue.total_HT,
        total_ttc=lue.total_TTC,
        date_facture=lue.date,
        textes=[resultat_ocr.texte, *resultat_ocr.tableaux],
    )

    etats = _etats_champs(lue)

    # 5. Un champ illisible vaut null, mais ce null doit se voir.
    for champ, etat in etats.items():
        if etat is EtatChamp.ILLISIBLE:
            avertissements.append(Avertissement(
                code="CHAMP_ILLISIBLE", champ=champ, gravite=Gravite.ALERTE,
                message=(f"Le champ « {champ} » figure sur le document mais n'a pas pu etre lu "
                         f"de facon fiable. Aucune valeur n'a ete supposee.")))

    # 6. Remarques de lecture remontees par le modele.
    for remarque in lue.remarques:
        avertissements.append(Avertissement(
            code="REMARQUE_LECTURE", champ=None, gravite=Gravite.INFO, message=remarque))

    # 7. Confiance OCR faible.
    #    On se fonde sur la moyenne, pas sur le minimum : le minimum est bas
    #    (0,19 a 0,25) y compris sur des documents parfaitement propres, sans
    #    doute porte par un jeton isole. L'utiliser comme declencheur produit
    #    une alerte sur chaque facture, donc du bruit qui masque les vraies.
    if resultat_ocr.confiance_moyenne is not None and resultat_ocr.confiance_moyenne < SEUIL_CONFIANCE_OCR:
        avertissements.append(Avertissement(
            code="CONFIANCE_OCR_FAIBLE", champ=None, gravite=Gravite.ALERTE,
            message=(f"Confiance moyenne de lecture a {resultat_ocr.confiance_moyenne:.0%}, sous le seuil de "
                     f"{SEUIL_CONFIANCE_OCR:.0%}. Le document est probablement degrade : verifier les montants "
                     f"a la main avant tout paiement.")))

    # 8. Un document dont on n'a tire ni total ni ligne n'est pas exploitable,
    #    meme si aucun controle n'a echoue : il n'y avait rien a controler.
    if not lignes and lue.total_HT is None and lue.total_TTC is None:
        avertissements.append(Avertissement(
            code="AUCUNE_DONNEE_EXPLOITABLE", champ=None, gravite=Gravite.BLOQUANT,
            message=("Aucune ligne ni total n'a pu etre extrait de ce document. Il ne s'agit peut-etre pas "
                     "d'une facture, ou la lecture a echoue.")))

    return Facture(
        nom_fournisseur=lue.nom_fournisseur,
        date=lue.date,
        numero_facture=lue.numero_facture,
        lignes_produits=lignes,
        total_HT=lue.total_HT,
        total_TTC=lue.total_TTC,
        avertissements=avertissements,
        meta=Meta(
            fichier=pdf.name,
            statut_global=statut_global(avertissements, etats),
            etats_champs=etats,
            controles=controles,
            confiance_ocr_moyenne=resultat_ocr.confiance_moyenne,
            confiance_ocr_minimum=resultat_ocr.confiance_minimum,
            modele_ocr=resultat_ocr.modele,
            modele_extraction=mistral_io.MODELE_EXTRACTION,
            duree_ms=int((time.perf_counter() - debut) * 1000),
        ),
    )
