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

# Seuil de confiance, au mot, en dessous duquel une valeur lue est refusee.
# Cale sur une observation : sur une facture dont le numero avait ete rendu
# volontairement illisible, l'OCR a produit « FL2026-0001 » avec une confiance
# de 0,68, quand tous les autres fragments du document depassaient 0,99. Le
# moteur signale donc lui-meme ce qu'il a devine, encore faut-il le regarder.
SEUIL_CONFIANCE_MOT = 0.90

# Champs textuels sans redondance interne : un total se recalcule depuis les
# lignes, un numero de facture ne se verifie contre rien. Pour ceux-la, la
# confiance de lecture est la seule protection disponible.
CHAMPS_SANS_REDONDANCE = ("nom_fournisseur", "date", "numero_facture")


def _confiance_valeur(valeur: str, mots) -> float | None:
    """Confiance la plus basse parmi les fragments OCR qui composent la valeur.

    Le rapprochement est textuel et volontairement tolerant : on retient tout
    fragment contenu dans la valeur, ou qui la contient. En l'absence de
    correspondance, on ne conclut rien plutot que de supposer.
    """
    cible = "".join(valeur.split()).lower()
    if not cible:
        return None
    scores = [
        m.confiance for m in mots
        if (nettoye := "".join(m.texte.split()).lower())
        and len(nettoye) >= 3
        and (nettoye in cible or cible in nettoye)
    ]
    return min(scores) if scores else None


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
    valeurs_refusees: dict[str, tuple[str, float]] = {}

    # 5. Une valeur peut etre lue avec assurance et etre fausse. On confronte
    #    donc chaque champ non verifiable arithmetiquement a la confiance que
    #    l'OCR accorde aux fragments dont il provient, et on refuse ce qui est
    #    trop incertain plutot que de laisser passer une valeur devinee.
    for champ in CHAMPS_SANS_REDONDANCE:
        valeur = getattr(lue, champ)
        if not isinstance(valeur, str) or etats.get(champ) is not EtatChamp.LU:
            continue
        confiance = _confiance_valeur(valeur, resultat_ocr.mots)
        if confiance is not None and confiance < SEUIL_CONFIANCE_MOT:
            etats[champ] = EtatChamp.ILLISIBLE
            valeurs_refusees[champ] = (valeur, confiance)

    # 6. Un champ illisible vaut null, mais ce null doit se voir. Quand la
    #    valeur a ete refusee pour cause d'incertitude, on dit ce qui avait ete
    #    lu : l'information sert a l'humain qui ira verifier sur le document.
    for champ, etat in etats.items():
        if etat is not EtatChamp.ILLISIBLE:
            continue
        if champ in valeurs_refusees:
            lecture, confiance = valeurs_refusees[champ]
            message = (f"Le champ « {champ} » a ete lu « {lecture} » avec une confiance de "
                       f"{confiance:.0%}, sous le seuil de {SEUIL_CONFIANCE_MOT:.0%}. La valeur est "
                       f"ecartee plutot que retenue : elle est probablement devinee. A verifier sur "
                       f"le document d'origine.")
        else:
            message = (f"Le champ « {champ} » figure sur le document mais n'a pas pu etre lu "
                       f"de facon fiable. Aucune valeur n'a ete supposee.")
        avertissements.append(Avertissement(
            code="CHAMP_ILLISIBLE", champ=champ, gravite=Gravite.ALERTE, message=message))

    # 7. Remarques de lecture remontees par le modele.
    for remarque in lue.remarques:
        avertissements.append(Avertissement(
            code="REMARQUE_LECTURE", champ=None, gravite=Gravite.INFO, message=remarque))

    # 8. Confiance OCR faible.
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

    # 9. Un document dont on n'a tire ni total ni ligne n'est pas exploitable,
    #    meme si aucun controle n'a echoue : il n'y avait rien a controler.
    if lue.total_HT is None and lue.total_TTC is None:
        avertissements.append(Avertissement(
            code="AUCUN_TOTAL", champ=None, gravite=Gravite.BLOQUANT,
            message=("Aucun total n'a pu etre extrait de ce document. Un bon de livraison ou un devis "
                     "porte des lignes sans montants : ce n'est pas une facture exploitable. Verifier la "
                     "nature du document.")))

    def valeur_retenue(champ: str):
        """Une valeur ecartee pour incertitude ne ressort pas : elle vaut null."""
        return None if champ in valeurs_refusees else getattr(lue, champ)

    return Facture(
        nom_fournisseur=valeur_retenue("nom_fournisseur"),
        date=valeur_retenue("date"),
        numero_facture=valeur_retenue("numero_facture"),
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
