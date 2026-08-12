"""Compare la sortie du pipeline aux JSON de reference attendus.

Ce n'est pas un test unitaire : c'est une verification de bout en bout, qui
consomme des appels API. Elle repond a une question simple : est-ce que
l'extracteur retrouve les valeurs attendues, champ par champ ?

Les fichiers de reference ne sont pas versionnes ici : ce sont les exemples de
sortie fournis avec l'enonce, il ne nous appartient pas de les publier.
Indiquer leur dossier avec --ref.

    python -m facture_extract tests/fixtures/*.pdf --out resultats/
    python tests/comparer_reference.py --ref chemin/vers/factures_json

Le rapprochement se fait par nom de fichier : reference `facture_2.json` et
resultat `facture_2.json`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
CHAMPS = ["nom_fournisseur", "date", "numero_facture", "total_HT", "total_TTC"]
TOLERANCE = 0.011  # un centime, pour absorber les arrondis en virgule flottante


def comparer(attendu: dict, obtenu: dict) -> list[str]:
    ecarts: list[str] = []

    for champ in CHAMPS:
        a, o = attendu.get(champ), obtenu.get(champ)
        if isinstance(a, (int, float)) or isinstance(o, (int, float)):
            if a is None or o is None or abs(a - o) > TOLERANCE:
                ecarts.append(f"{champ} : attendu {a!r}, obtenu {o!r}")
        elif a != o:
            ecarts.append(f"{champ} : attendu {a!r}, obtenu {o!r}")

    lignes_a = attendu.get("lignes_produits", [])
    lignes_o = obtenu.get("lignes_produits", [])
    if len(lignes_a) != len(lignes_o):
        ecarts.append(f"nombre de lignes : attendu {len(lignes_a)}, obtenu {len(lignes_o)}")
    else:
        for i, (x, y) in enumerate(zip(lignes_a, lignes_o), start=1):
            for champ in ("quantite", "prix_unitaire"):
                a, o = x.get(champ), y.get(champ)
                if a is None or o is None or abs(a - o) > TOLERANCE:
                    ecarts.append(f"ligne {i}, {champ} : attendu {a!r}, obtenu {o!r}")
    return ecarts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Compare les resultats aux JSON de reference.")
    p.add_argument("--ref", type=Path, required=True,
                   help="Dossier contenant les JSON de reference fournis avec l'enonce.")
    p.add_argument("--resultats", type=Path, default=RACINE / "resultats",
                   help="Dossier des JSON produits (defaut : resultats/).")
    args = p.parse_args(argv)

    if not args.ref.is_dir():
        print(f"Dossier de reference introuvable : {args.ref}", file=sys.stderr)
        return 2
    if not args.resultats.is_dir():
        print(f"Dossier de resultats introuvable : {args.resultats}\n"
              f"Lancer d'abord : python -m facture_extract tests/fixtures/*.pdf --out resultats/",
              file=sys.stderr)
        return 2

    references = sorted(args.ref.glob("*.json"))
    if not references:
        print(f"Aucun JSON de reference dans {args.ref}", file=sys.stderr)
        return 2

    total = 0
    for reference in references:
        resultat = args.resultats / reference.name
        if not resultat.exists():
            print(f"{reference.stem:<34} SANS RESULTAT")
            continue
        ecarts = comparer(
            json.loads(reference.read_text(encoding="utf-8")),
            json.loads(resultat.read_text(encoding="utf-8")),
        )
        total += len(ecarts)
        print(f"{reference.stem:<34} {'CONFORME' if not ecarts else f'{len(ecarts)} ecart(s)'}")
        for e in ecarts:
            print(f"    - {e}")

    print(f"\nTotal : {total} ecart(s) sur les champs de reference.")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
