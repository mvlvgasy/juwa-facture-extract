"""Interface en ligne de commande.

    python -m facture_extract tests/fixtures/*.pdf
    python -m facture_extract facture.pdf --json
    python -m facture_extract dossier/*.pdf --out resultats/

Par defaut, affiche un resume lisible. `--json` imprime le document complet,
c'est le format de rendu attendu par le sujet.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import traiter
from .schema import EtatChamp, Facture, Gravite, ResultatControle

SYMBOLE_GRAVITE = {Gravite.INFO: "i", Gravite.ALERTE: "!", Gravite.BLOQUANT: "X"}
SYMBOLE_CONTROLE = {
    ResultatControle.OK: "ok  ",
    ResultatControle.ECHEC: "ECHEC",
    ResultatControle.NON_APPLICABLE: "n/a ",
}


def _montant(x: float | None) -> str:
    return "null" if x is None else f"{x:,.2f}".replace(",", " ").replace(".", ",")


def resume(f: Facture) -> str:
    """Rendu texte destine a l'humain qui regarde passer les factures."""
    lignes: list[str] = []
    m = f.meta
    lignes.append(f"\n=== {m.fichier}")
    lignes.append(f"    statut : {m.statut_global.upper()}"
                  f"   ({m.duree_ms} ms, confiance OCR "
                  f"{'n/a' if m.confiance_ocr_moyenne is None else f'{m.confiance_ocr_moyenne:.1%}'})")

    for champ in ("nom_fournisseur", "date", "numero_facture"):
        etat = m.etats_champs.get(champ)
        suffixe = "" if etat is EtatChamp.LU else f"   [{etat.value}]"
        lignes.append(f"    {champ:<16} : {getattr(f, champ) or 'null'}{suffixe}")

    lignes.append(f"    lignes           : {len(f.lignes_produits)}")
    for l in f.lignes_produits:
        libelle = (l.designation or "?")[:52]
        lignes.append(f"      - {libelle:<52} {str(l.quantite or '?'):>5} x "
                      f"{_montant(l.prix_unitaire):>10} = {_montant(l.total_ligne):>11}")
    lignes.append(f"    total HT         : {_montant(f.total_HT)}")
    lignes.append(f"    total TTC        : {_montant(f.total_TTC)}")

    lignes.append("    controles :")
    for c in m.controles:
        lignes.append(f"      [{SYMBOLE_CONTROLE[c.resultat]}] {c.nom:<26} {c.detail}")

    if f.avertissements:
        lignes.append("    avertissements :")
        for a in f.avertissements:
            cible = f" ({a.champ})" if a.champ else ""
            lignes.append(f"      [{SYMBOLE_GRAVITE[a.gravite]}] {a.code}{cible} : {a.message}")
    else:
        lignes.append("    avertissements : aucun")
    return "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="facture_extract",
        description="Extrait les donnees d'une facture PDF en JSON valide, via l'API Mistral.")
    p.add_argument("pdf", nargs="+", type=Path, help="Un ou plusieurs fichiers PDF.")
    p.add_argument("--json", action="store_true", help="Imprimer le JSON complet au lieu du resume.")
    p.add_argument("--out", type=Path, default=None,
                   help="Ecrire un fichier .json par facture dans ce dossier.")
    args = p.parse_args(argv)

    fichiers = [f for f in args.pdf if f.suffix.lower() == ".pdf" and f.exists()]
    manquants = [f for f in args.pdf if f not in fichiers]
    for f in manquants:
        print(f"ignore (introuvable ou non PDF) : {f}", file=sys.stderr)
    if not fichiers:
        print("Aucun PDF a traiter.", file=sys.stderr)
        return 2

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)

    code_sortie = 0
    for chemin in fichiers:
        try:
            facture = traiter(chemin)
        except Exception as e:  # une facture en echec n'interrompt pas le lot
            print(f"\n=== {chemin.name}\n    ECHEC : {type(e).__name__}: {e}", file=sys.stderr)
            code_sortie = 1
            continue

        contenu = facture.model_dump_json(indent=2, exclude_none=False)
        print(contenu if args.json else resume(facture))
        if args.out:
            (args.out / f"{chemin.stem}.json").write_text(contenu, encoding="utf-8")

    return code_sortie


if __name__ == "__main__":
    raise SystemExit(main())
