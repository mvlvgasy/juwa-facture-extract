"""Compare la sortie du pipeline aux JSON de reference fournis par JUWA.

Ce n'est pas un test unitaire : c'est une verification de bout en bout qui
consomme des appels API. Elle repond a une question simple : est-ce que
l'extracteur retrouve les valeurs attendues, champ par champ ?

    python tests/comparer_reference.py
"""
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
REF = RACINE.parents[2] / "lab-job-hunt/projets-meta/cv-linkedin-portfolio/outreach/juwa/test-technique/factures_json"
OBTENU = RACINE / "resultats"

CHAMPS = ["nom_fournisseur", "date", "numero_facture", "total_HT", "total_TTC"]


def comparer(attendu: dict, obtenu: dict) -> list[str]:
    ecarts = []
    for c in CHAMPS:
        a, o = attendu.get(c), obtenu.get(c)
        if isinstance(a, float) or isinstance(o, float):
            if a is None or o is None or abs(a - o) > 0.011:
                ecarts.append(f"{c}: attendu {a!r}, obtenu {o!r}")
        elif a != o:
            ecarts.append(f"{c}: attendu {a!r}, obtenu {o!r}")

    la, lo = attendu["lignes_produits"], obtenu["lignes_produits"]
    if len(la) != len(lo):
        ecarts.append(f"nombre de lignes: attendu {len(la)}, obtenu {len(lo)}")
    else:
        for i, (x, y) in enumerate(zip(la, lo), 1):
            for c in ("quantite", "prix_unitaire"):
                if x[c] is None or y[c] is None or abs(x[c] - y[c]) > 0.011:
                    ecarts.append(f"ligne {i} {c}: attendu {x[c]!r}, obtenu {y[c]!r}")
    return ecarts


def main() -> int:
    total_ecarts = 0
    for ref in sorted(REF.glob("*.json")):
        obt = OBTENU / ref.name
        if not obt.exists():
            print(f"{ref.stem:<34} SANS RESULTAT (lancer la CLI avec --out resultats/)")
            continue
        ecarts = comparer(json.loads(ref.read_text(encoding="utf-8")),
                          json.loads(obt.read_text(encoding="utf-8")))
        total_ecarts += len(ecarts)
        print(f"{ref.stem:<34} {'CONFORME' if not ecarts else f'{len(ecarts)} ecart(s)'}")
        for e in ecarts:
            print(f"    - {e}")
    print(f"\nTotal : {total_ecarts} ecart(s) sur les champs de reference.")
    return 0 if total_ecarts == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
