"""Schema de donnees.

Principe directeur : le modele ne remplit que ce qu'il lit reellement dans le
document. Tout le reste (totaux recalcules, controles, statut global) est
produit par du code deterministe. La frontiere entre les deux est explicite et
visible dans le JSON de sortie, ce qui permet de savoir, pour chaque valeur,
si elle vient d'une lecture ou d'un calcul.

Deux modeles distincts :

- `FactureLue`  : ce que le modele de langage a le droit de renseigner. C'est
  ce schema qui lui est impose en sortie structuree.
- `Facture`     : le document final. Il reprend a plat les champs demandes par
  le sujet, et y ajoute un bloc `meta` qui porte l'etat de chaque champ, les
  controles executes et le statut global.

Point de conception important : un champ absent et un champ illisible valent
tous les deux `null`, mais ce ne sont pas la meme chose. Une facture de
prestation de service n'a legitimement pas de quantite ; un scan trop degrade
pour etre lu est un probleme. L'enum `EtatChamp` porte cette distinction, que
la seule valeur `null` ne permettrait pas d'exprimer.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class EtatChamp(str, Enum):
    """Pourquoi un champ vaut ce qu'il vaut."""

    LU = "lu"                # valeur trouvee et jugee fiable
    ILLISIBLE = "illisible"  # le champ existe dans le document mais n'est pas lisible de facon sure
    ABSENT = "absent"        # le champ ne figure pas dans ce document
    CORRIGE = "corrige"      # valeur saisie par un humain, qui a tranche sur pieces


class Gravite(str, Enum):
    INFO = "info"          # signale, sans consequence sur l'exploitation
    ALERTE = "alerte"      # a verifier par un humain avant utilisation
    BLOQUANT = "bloquant"  # le document ne peut pas etre exploite en l'etat


class ResultatControle(str, Enum):
    OK = "ok"
    ECHEC = "echec"
    NON_APPLICABLE = "non_applicable"


# --------------------------------------------------------------------------
# Ce que le modele a le droit de remplir
# --------------------------------------------------------------------------

class LigneLue(BaseModel):
    """Une ligne de produit ou de prestation, telle que lue.

    Aucun champ ne porte de valeur par defaut : tous sont *requis mais
    nullables*. C'est deliberé. Avec des valeurs par defaut, le schema JSON
    transmis au modele marque les champs comme facultatifs, et le modele prend
    alors le chemin le plus court en ne renvoyant que le strict minimum. En les
    rendant requis, on l'oblige a se prononcer explicitement sur chacun, quitte
    a repondre null.
    """

    designation: str | None = Field(
        description="Libelle de la ligne, recopie tel quel, sans reformulation.")
    quantite: float | None = Field(
        description="Quantite. null si la ligne n'en porte pas.")
    prix_unitaire: float | None = Field(
        description="Prix unitaire hors taxes. null si non lisible.")
    montant_ligne: float | None = Field(
        description=("Montant total de la ligne TEL QU'IMPRIME sur le document, dans la colonne "
                     "total ou montant. Ne surtout pas le recalculer a partir de la quantite et "
                     "du prix unitaire : c'est la valeur imprimee qui est demandee, meme si elle "
                     "parait fausse. null si la ligne ne porte pas de colonne total."))


class FactureLue(BaseModel):
    """Sortie structuree imposee au modele de langage.

    Aucun champ calcule ici : le modele lit, il ne deduit pas. Le total HT
    demande est celui *imprime sur la facture*, pas la somme des lignes, afin
    de pouvoir precisement comparer les deux ensuite.

    Comme dans `LigneLue`, tous les champs sont requis et nullables.
    """

    nom_fournisseur: str | None = Field(
        description="Raison sociale de l'emetteur de la facture. null si illisible ou absent.")
    date: str | None = Field(
        description="Date de la facture au format AAAA-MM-JJ. null si illisible ou absente.")
    numero_facture: str | None = Field(
        description="Numero de la facture, recopie caractere pour caractere. null si illisible.")
    lignes_produits: list[LigneLue] = Field(
        description="Lignes du tableau de detail, dans l'ordre du document. Liste vide si aucune.")
    total_HT: float | None = Field(
        description="Total hors taxes tel qu'imprime sur la facture. Ne pas le recalculer. null si illisible.")
    total_TTC: float | None = Field(
        description="Total toutes taxes comprises tel qu'imprime. Ne pas le recalculer. null si illisible.")
    champs_illisibles: list[str] = Field(
        description=("Noms des champs qui figurent bien sur le document mais que tu n'as pas pu lire "
                     "de facon fiable. Un champ qui n'existe pas sur ce document ne va PAS ici."))
    remarques: list[str] = Field(
        description="Anomalies constatees a la lecture (texte corrompu, zone raturee, tampon illisible...).")


# --------------------------------------------------------------------------
# Ce que le code produit
# --------------------------------------------------------------------------

class Avertissement(BaseModel):
    code: str
    champ: str | None = None
    message: str
    gravite: Gravite
    # Renseignes uniquement quand une valeur a ete lue puis ecartee pour cause
    # d'incertitude. Exposes en clair plutot que noyes dans le message : une
    # interface doit pouvoir les afficher sans avoir a analyser une phrase.
    valeur_ecartee: str | None = None
    confiance: float | None = None
    seuil: float | None = None


class Controle(BaseModel):
    """Une verification deterministe. Aucune IA n'intervient ici."""

    nom: str
    resultat: ResultatControle
    detail: str
    attendu: float | str | None = None
    trouve: float | str | None = None
    ecart: float | None = None


class Correction(BaseModel):
    """Une valeur tranchee par un humain apres coup.

    Tracee explicitement plutot que d'ecraser la lecture en silence : dans une
    chaine comptable, savoir qu'un montant vient d'une saisie manuelle et non
    d'une lecture automatique n'est pas un detail, c'est ce qui permet de
    remonter a la decision quand le paiement est conteste.
    """

    champ: str
    valeur_lue: str | float | None = None
    valeur_retenue: str | float | None = None


class LigneProduit(BaseModel):
    """Une ligne du tableau de detail.

    Deux montants distincts et jamais fusionnes, pour la meme raison qui
    impose de lire le total HT plutot que de le recalculer : si le code
    substitue silencieusement sa propre valeur a celle du document, une erreur
    de calcul presente sur la facture devient indetectable par construction.

    - `total_ligne`    : quantite x prix_unitaire, calcule ici.
    - `total_ligne_lu` : la valeur imprimee dans la colonne total, lue telle quelle.

    Quand les deux existent et different, c'est le fournisseur qui s'est trompe,
    et c'est precisement ce qu'on veut signaler.
    """

    designation: str | None = None
    quantite: float | None = None
    prix_unitaire: float | None = None
    total_ligne: float | None = Field(
        default=None, description="quantite x prix_unitaire, calcule par le code, jamais lu.")
    total_ligne_lu: float | None = Field(
        default=None, description="Montant de la ligne tel qu'imprime sur le document, jamais calcule.")


class Meta(BaseModel):
    fichier: str
    statut_global: str = Field(
        description="fiable | a_verifier | non_exploitable")
    etats_champs: dict[str, EtatChamp]
    controles: list[Controle]
    confiance_ocr_moyenne: float | None = None
    confiance_ocr_minimum: float | None = None
    modele_ocr: str | None = None
    modele_extraction: str | None = None
    duree_ms: int | None = None
    corrections: list[Correction] = Field(
        default_factory=list,
        description="Valeurs reprises a la main apres la lecture automatique, dans l'ordre.")


class Facture(BaseModel):
    """Document final.

    Les six champs demandes par le sujet sont a plat, au premier niveau, pour
    rester directement comparables a leurs exemples. Tout ce qui releve de
    notre propre analyse est isole dans `meta`.
    """

    nom_fournisseur: str | None = None
    date: str | None = None
    numero_facture: str | None = None
    lignes_produits: list[LigneProduit] = Field(default_factory=list)
    total_HT: float | None = None
    total_TTC: float | None = None
    avertissements: list[Avertissement] = Field(default_factory=list)
    meta: Meta
