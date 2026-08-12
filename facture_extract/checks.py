"""Controles deterministes.

Aucun appel a un modele ici, et c'est volontaire : ce module est l'endroit ou
l'on arrete l'IA. Un modele de langage sait lire un document, il n'est pas
l'outil pour verifier une addition. Tout ce qui est arithmetiquement
verifiable l'est par du code, dont le comportement est reproductible et
testable.

Consequence pratique : si le modele lit un total qui ne correspond pas a la
somme des lignes, on ne corrige rien en silence. On leve un avertissement et
on laisse les deux valeurs visibles. C'est a l'humain de trancher.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .schema import Avertissement, Controle, Gravite, LigneProduit, ResultatControle

# Tolerance sur les comparaisons monetaires : un centime, pour absorber les
# arrondis de calcul en virgule flottante.
CENTIME = 0.011

# Taux de TVA francais applicables, historiques compris. Le taux normal est
# passe de 19,6 % a 20 % au 1er janvier 2014 : une facture anterieure a cette
# date porte donc legitimement 19,6 %. Coder 20 % en dur produirait un faux
# positif sur toutes les archives anciennes.
TAUX_TVA_CONNUS = {
    20.0: "taux normal depuis 2014",
    19.6: "ancien taux normal, jusqu'au 31/12/2013",
    10.0: "taux intermediaire",
    8.5: "taux particulier outre-mer",
    7.0: "ancien taux intermediaire, 2012-2013",
    5.5: "taux reduit",
    2.1: "taux super-reduit",
    0.0: "exoneration ou autoliquidation",
}

# Signature d'un double encodage UTF-8 lu comme du latin-1 : les octets d'un
# caractere accentue se retrouvent affiches sous forme de deux caracteres.
MOTIF_DOUBLE_ENCODAGE = re.compile(r"[ÃÂ][\x80-\xbf -ÿ]")


def _arrondi(x: float) -> float:
    return round(x + 0.0, 2)


def controler(
    lignes: list[LigneProduit],
    total_ht: float | None,
    total_ttc: float | None,
    date_facture: str | None,
    textes: list[str],
    aujourdhui: date | None = None,
) -> tuple[list[Controle], list[Avertissement]]:
    """Execute tous les controles et retourne (controles, avertissements)."""

    controles: list[Controle] = []
    avert: list[Avertissement] = []
    aujourdhui = aujourdhui or date.today()

    def ajoute(c: Controle, av: Avertissement | None = None) -> None:
        controles.append(c)
        if av is not None:
            avert.append(av)

    # --- 1. Somme des lignes contre total HT imprime -----------------------
    calculables = [l for l in lignes
                   if l.quantite is not None and l.prix_unitaire is not None]
    if not calculables or total_ht is None:
        ajoute(Controle(
            nom="somme_lignes_vs_total_ht",
            resultat=ResultatControle.NON_APPLICABLE,
            detail="Lignes chiffrees ou total HT manquants, comparaison impossible."))
    else:
        somme = _arrondi(sum(l.quantite * l.prix_unitaire for l in calculables))
        ecart = _arrondi(total_ht - somme)
        if abs(ecart) <= CENTIME:
            ajoute(Controle(
                nom="somme_lignes_vs_total_ht", resultat=ResultatControle.OK,
                detail="La somme des lignes correspond au total HT imprime.",
                attendu=somme, trouve=total_ht, ecart=0.0))
        else:
            ajoute(
                Controle(
                    nom="somme_lignes_vs_total_ht", resultat=ResultatControle.ECHEC,
                    detail=(f"La somme des lignes vaut {somme:.2f} alors que le total HT imprime "
                            f"indique {total_ht:.2f}. Aucune des deux valeurs n'est corrigee."),
                    attendu=somme, trouve=total_ht, ecart=ecart),
                Avertissement(
                    code="ECART_SOMME_LIGNES", champ="total_HT", gravite=Gravite.ALERTE,
                    message=(f"Ecart de {abs(ecart):.2f} entre la somme des lignes ({somme:.2f}) "
                             f"et le total HT imprime ({total_ht:.2f}). A verifier avant paiement.")))

    # --- 2. Taux de TVA deduit, jamais suppose -----------------------------
    if total_ht is None or total_ttc is None or total_ht == 0:
        ajoute(Controle(
            nom="taux_tva", resultat=ResultatControle.NON_APPLICABLE,
            detail="Total HT ou TTC manquant, taux non deductible."))
    else:
        taux = _arrondi((total_ttc / total_ht - 1) * 100)
        proche = min(TAUX_TVA_CONNUS, key=lambda t: abs(t - taux))
        if abs(proche - taux) <= 0.05:
            ajoute(Controle(
                nom="taux_tva", resultat=ResultatControle.OK,
                detail=f"Taux deduit {taux:.2f} %, correspond au {TAUX_TVA_CONNUS[proche]}.",
                trouve=taux, attendu=proche))
        else:
            ajoute(
                Controle(
                    nom="taux_tva", resultat=ResultatControle.ECHEC,
                    detail=(f"Taux deduit {taux:.2f} %, ne correspond a aucun taux francais connu. "
                            f"Le plus proche est {proche} %."),
                    trouve=taux, attendu=proche, ecart=_arrondi(taux - proche)),
                Avertissement(
                    code="TAUX_TVA_INCONNU", champ="total_TTC", gravite=Gravite.ALERTE,
                    message=(f"Le rapport TTC/HT donne un taux de {taux:.2f} %, qui ne correspond a "
                             f"aucun taux de TVA francais. Un des deux totaux est probablement mal lu.")))

    # --- 3. TTC superieur ou egal au HT ------------------------------------
    if total_ht is None or total_ttc is None:
        ajoute(Controle(nom="ttc_superieur_ht", resultat=ResultatControle.NON_APPLICABLE,
                        detail="Un des deux totaux est manquant."))
    elif total_ttc + CENTIME >= total_ht:
        ajoute(Controle(nom="ttc_superieur_ht", resultat=ResultatControle.OK,
                        detail="Le total TTC est bien superieur ou egal au total HT."))
    else:
        ajoute(
            Controle(nom="ttc_superieur_ht", resultat=ResultatControle.ECHEC,
                     detail=f"TTC ({total_ttc:.2f}) inferieur au HT ({total_ht:.2f}).",
                     attendu=total_ht, trouve=total_ttc),
            Avertissement(code="TTC_INFERIEUR_HT", champ="total_TTC", gravite=Gravite.BLOQUANT,
                          message="Le total TTC est inferieur au total HT, les deux valeurs sont incoherentes."))

    # --- 4. Plausibilite de la date ----------------------------------------
    if not date_facture:
        ajoute(Controle(nom="date_plausible", resultat=ResultatControle.NON_APPLICABLE,
                        detail="Date absente ou illisible."))
    else:
        try:
            d = datetime.strptime(date_facture, "%Y-%m-%d").date()
        except ValueError:
            ajoute(
                Controle(nom="date_plausible", resultat=ResultatControle.ECHEC,
                         detail=f"Date « {date_facture} » non conforme au format AAAA-MM-JJ.",
                         trouve=date_facture),
                Avertissement(code="DATE_INVALIDE", champ="date", gravite=Gravite.ALERTE,
                              message=f"Date illisible ou mal formee : « {date_facture} »."))
        else:
            if d > aujourdhui:
                ajoute(
                    Controle(nom="date_plausible", resultat=ResultatControle.ECHEC,
                             detail=f"Date {d.isoformat()} posterieure a aujourd'hui.", trouve=d.isoformat()),
                    Avertissement(code="DATE_FUTURE", champ="date", gravite=Gravite.ALERTE,
                                  message=f"La date {d.isoformat()} est dans le futur."))
            elif d.year < 1990:
                ajoute(
                    Controle(nom="date_plausible", resultat=ResultatControle.ECHEC,
                             detail=f"Date {d.isoformat()} anterieure a 1990, probablement mal lue.",
                             trouve=d.isoformat()),
                    Avertissement(code="DATE_ABERRANTE", champ="date", gravite=Gravite.ALERTE,
                                  message=f"La date {d.isoformat()} est invraisemblable pour une facture."))
            else:
                ajoute(Controle(nom="date_plausible", resultat=ResultatControle.OK,
                                detail=f"Date {d.isoformat()} plausible.", trouve=d.isoformat()))

    # --- 5. Quantites et prix positifs -------------------------------------
    anomalies = [
        f"ligne {i + 1}" for i, l in enumerate(lignes)
        if (l.quantite is not None and l.quantite <= 0)
        or (l.prix_unitaire is not None and l.prix_unitaire < 0)
    ]
    if not lignes:
        ajoute(Controle(nom="lignes_positives", resultat=ResultatControle.NON_APPLICABLE,
                        detail="Aucune ligne extraite."))
    elif anomalies:
        ajoute(
            Controle(nom="lignes_positives", resultat=ResultatControle.ECHEC,
                     detail=f"Quantite nulle ou prix negatif sur : {', '.join(anomalies)}."),
            Avertissement(code="LIGNE_ABERRANTE", champ="lignes_produits", gravite=Gravite.ALERTE,
                          message=f"Valeurs aberrantes detectees sur {', '.join(anomalies)}."))
    else:
        ajoute(Controle(nom="lignes_positives", resultat=ResultatControle.OK,
                        detail=f"{len(lignes)} ligne(s), quantites et prix coherents."))

    # --- 6. Integrite de l'encodage du texte source ------------------------
    suspects = sorted({m.group(0) for t in textes for m in MOTIF_DOUBLE_ENCODAGE.finditer(t)})
    if suspects:
        ajoute(
            Controle(nom="encodage_texte", resultat=ResultatControle.ECHEC,
                     detail=f"Sequences de double encodage detectees : {', '.join(suspects[:6])}.",
                     trouve=", ".join(suspects[:6])),
            Avertissement(code="ENCODAGE_SUSPECT", champ=None, gravite=Gravite.INFO,
                          message=("Caracteres inhabituels detectes dans le texte source, evocateurs d'un "
                                   "probleme d'encodage. Les libelles peuvent etre alteres ; les montants, eux, "
                                   "restent verifies par les controles arithmetiques.")))
    else:
        ajoute(Controle(nom="encodage_texte", resultat=ResultatControle.OK,
                        detail="Aucune sequence de double encodage detectee."))

    return controles, avert


def statut_global(avertissements: list[Avertissement], etats: dict) -> str:
    """Resume exploitable en un mot, pour trier sans lire le detail."""
    from .schema import EtatChamp

    if any(a.gravite == Gravite.BLOQUANT for a in avertissements):
        return "non_exploitable"
    if any(a.gravite == Gravite.ALERTE for a in avertissements):
        return "a_verifier"
    if any(e == EtatChamp.ILLISIBLE for e in etats.values()):
        return "a_verifier"
    return "fiable"
