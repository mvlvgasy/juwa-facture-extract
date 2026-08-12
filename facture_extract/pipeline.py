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
    Correction,
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

# Avertissements qui decrivent la LECTURE du document et non ses valeurs : une
# correction humaine ne les invalide pas, ils sont donc reportes tels quels sur
# le document corrige. Ceux qui viennent des controles arithmetiques, eux, sont
# entierement recalcules.
CODES_DE_LECTURE = frozenset({
    "CHAMP_ILLISIBLE", "REMARQUE_LECTURE", "CONFIANCE_OCR_FAIBLE", "ENCODAGE_SUSPECT",
})


def _confiance_valeur(valeur: str, mots) -> float | None:
    """Confiance la plus basse parmi les fragments OCR qui composent la valeur.

    Deux formes de correspondance seulement, pour eviter les rapprochements
    fortuits (releves a l'audit : un fragment « 2026 » a 0,40 sans rapport
    faisait ecarter une date correcte) :

    - le fragment contient la valeur entiere : correspondance sure ;
    - le fragment est un morceau de la valeur, a condition d'en couvrir une
      part substantielle (au moins 5 caracteres ET 60 % de la longueur de la
      cible). Un token court partage par hasard ne suffit plus.

    En l'absence de correspondance, on ne conclut rien plutot que de supposer.
    """
    cible = "".join(valeur.split()).lower()
    if not cible:
        return None
    longueur_minimale = max(5, -(-len(cible) * 6 // 10))  # plafond entier de 60 %
    scores = []
    for m in mots:
        nettoye = "".join(m.texte.split()).lower()
        if not nettoye:
            continue
        if cible in nettoye:
            scores.append(m.confiance)
        elif nettoye in cible and len(nettoye) >= longueur_minimale:
            scores.append(m.confiance)
    return min(scores) if scores else None


def _normalise_nom_champ(nom: str) -> str:
    """Ramene « Numéro de facture » a `numero_facture`.

    Le modele recopie parfois le libelle humain au lieu du nom technique dans
    `champs_illisibles`. Sans normalisation, le champ passerait silencieusement
    d'illisible a absent, et l'alerte se perdrait.
    """
    import unicodedata

    plat = unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode()
    plat = plat.lower().strip().replace("-", " ").replace("'", " ")
    plat = "_".join(plat.split())
    return {"numero": "numero_facture", "numero_de_facture": "numero_facture",
            "fournisseur": "nom_fournisseur", "nom_du_fournisseur": "nom_fournisseur",
            "lignes": "lignes_produits", "lignes_de_produits": "lignes_produits",
            "total_ht": "total_HT", "total_ttc": "total_TTC"}.get(plat, plat)


def _etats_champs(lue: FactureLue) -> dict[str, EtatChamp]:
    """Determine, champ par champ, pourquoi il vaut ce qu'il vaut.

    Un champ renseigne est `lu`. Un champ vide que le modele a signale comme
    non lisible est `illisible`. Un champ vide non signale est `absent`, donc
    considere comme legitimement inexistant sur ce document.
    """
    signales = {_normalise_nom_champ(c) for c in lue.champs_illisibles}
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


def _texte(valeur) -> str | None:
    """Normalise une saisie libre : la chaine vide vaut absence, pas chaine vide."""
    if valeur is None:
        return None
    return str(valeur).strip() or None


# Separateurs de milliers et symboles a retirer avant conversion. Les trois
# espaces autres que l'espace ordinaire (insecable, fine insecable, fine) sont
# ce que produisent Word, Excel et les claviers francais : invisibles a la
# relecture, elles feraient echouer float() sans explication comprehensible.
PARASITES_NUMERIQUES = (" ", "\xa0", "\u202f", "\u2009", "\u20ac", "EUR")


def _nombre(valeur) -> float | None:
    """Lit un montant saisi a la main, en acceptant les usages francais.

    « 1 040,50 », « 1040.5 » et « 1040,50 € » designent le meme montant.
    Refuser la virgule decimale a un comptable francais serait un defaut
    d'interface, pas une rigueur.
    """
    if valeur is None:
        return None
    if isinstance(valeur, (int, float)):
        return float(valeur)
    plat = str(valeur).strip()
    for parasite in PARASITES_NUMERIQUES:
        plat = plat.replace(parasite, "")
    plat = plat.replace(",", ".")
    if not plat:
        return None
    try:
        return float(plat)
    except ValueError:
        # Message rendu a l'utilisateur tel quel : il doit nommer la saisie
        # fautive, pas la representation interne apres nettoyage.
        raise ValueError(f"« {valeur} » n'est pas un montant lisible.") from None


def revalider(facture: Facture, saisies: dict) -> Facture:
    """Rejoue les controles apres qu'un humain a corrige des valeurs.

    Une correction ne relance ni l'OCR ni le modele : on ne relit pas le
    document, on remplace une valeur lue par une valeur tranchee sur pieces,
    puis on repasse **exactement les memes controles deterministes**. Le chemin
    corrige n'est donc pas moins verifie que le chemin automatique, ce qui
    evite le travers habituel de ce genre d'ecran, ou la saisie manuelle est
    reputee juste parce qu'elle vient d'un humain.

    `saisies` porte les champs a plat et, optionnellement, `lignes_produits`
    sous forme de liste de dictionnaires. Un champ absent de `saisies` n'est
    pas touche.
    """
    corrige = facture.model_copy(deep=True)
    corrections: list[Correction] = []

    for champ in CHAMPS_SIMPLES:
        if champ not in saisies:
            continue
        avant = getattr(corrige, champ)
        apres = (_nombre(saisies[champ]) if champ in ("total_HT", "total_TTC")
                 else _texte(saisies[champ]))
        if apres == avant:
            continue
        setattr(corrige, champ, apres)
        corrections.append(Correction(champ=champ, valeur_lue=avant, valeur_retenue=apres))
        # Vider un champ, c'est declarer qu'il n'y a rien a en tirer ; le
        # renseigner, c'est prendre la responsabilite de la valeur.
        corrige.meta.etats_champs[champ] = (
            EtatChamp.CORRIGE if apres is not None else EtatChamp.ABSENT)

    if "lignes_produits" in saisies:
        anciennes = corrige.lignes_produits
        nouvelles: list[LigneProduit] = []
        for i, brute in enumerate(saisies["lignes_produits"] or []):
            designation = _texte(brute.get("designation"))
            quantite = _nombre(brute.get("quantite"))
            prix = _nombre(brute.get("prix_unitaire"))
            nouvelles.append(LigneProduit(
                designation=designation, quantite=quantite, prix_unitaire=prix,
                total_ligne=(round(quantite * prix, 2)
                             if quantite is not None and prix is not None else None)))
            ancienne = anciennes[i] if i < len(anciennes) else None
            for cle in ("designation", "quantite", "prix_unitaire"):
                avant = getattr(ancienne, cle) if ancienne else None
                apres = getattr(nouvelles[-1], cle)
                if apres != avant:
                    corrections.append(Correction(
                        champ=f"ligne {i + 1} · {cle}", valeur_lue=avant, valeur_retenue=apres))
        if nouvelles != anciennes:
            corrige.lignes_produits = nouvelles
            corrige.meta.etats_champs["lignes_produits"] = EtatChamp.CORRIGE

    controles, avertissements = controler(
        lignes=corrige.lignes_produits,
        total_ht=corrige.total_HT,
        total_ttc=corrige.total_TTC,
        date_facture=corrige.date,
        # Le texte OCR n'est pas conserve entre deux appels : le controle
        # d'encodage est repris de la lecture d'origine juste apres, plutot que
        # recalcule a vide, ce qui le ferait passer au vert a tort.
        textes=[],
    )
    origine = {c.nom: c for c in facture.meta.controles}
    controles = [origine[c.nom] if c.nom == "encodage_texte" and c.nom in origine else c
                 for c in controles]

    champs_corriges = {c.champ for c in corrections}
    reportes = [a for a in facture.avertissements
                if a.code in CODES_DE_LECTURE and a.champ not in champs_corriges]

    corrige.avertissements = reportes + avertissements
    corrige.meta.controles = controles
    corrige.meta.statut_global = statut_global(corrige.avertissements, corrige.meta.etats_champs)
    corrige.meta.corrections = [*facture.meta.corrections, *corrections]
    return corrige


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
        refus = valeurs_refusees.get(champ)
        avertissements.append(Avertissement(
            code="CHAMP_ILLISIBLE", champ=champ, gravite=Gravite.ALERTE, message=message,
            valeur_ecartee=refus[0] if refus else None,
            confiance=refus[1] if refus else None,
            seuil=SEUIL_CONFIANCE_MOT if refus else None))

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
