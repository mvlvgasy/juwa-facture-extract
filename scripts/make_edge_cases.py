"""Genere un corpus de factures difficiles, un piege par fichier.

Les quatre factures de `make_test_invoices.py` reproduisent les exemples de
l'enonce : elles verifient que le pipeline retrouve les bonnes valeurs. Celles-ci
verifient l'inverse, c'est-a-dire ce qu'il fait quand le document est mauvais.

Chaque fichier isole une seule difficulte, pour qu'un echec designe sa cause
sans ambiguite. Les documents sont generes par code plutot que par un modele
d'image : c'est reproductible, et surtout on sait exactement ce que chacun teste.

    python scripts/make_edge_cases.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CHROME = Path(os.environ.get("CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe"))
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

CSS = """
@page { size: A4; margin: 18mm; }
body { font-family: Arial, Helvetica, sans-serif; font-size: 10pt; color: #111; }
.hdr { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:14mm; }
.sup { font-size: 15pt; font-weight: bold; }
.meta { text-align:right; font-size: 9.5pt; line-height:1.6; }
h1 { font-size: 12pt; margin: 0 0 6mm; letter-spacing:.08em; }
table { width:100%; border-collapse:collapse; font-size:9.5pt; }
th { text-align:left; border-bottom:1.5px solid #333; padding:2mm 1.5mm; }
td { border-bottom:.5px solid #ccc; padding:2mm 1.5mm; vertical-align:top; }
td.n, th.n { text-align:right; white-space:nowrap; }
.tot { margin-top:8mm; width:74mm; margin-left:auto; font-size:10pt; }
.tot div { display:flex; justify-content:space-between; padding:1.5mm 0; }
.tot .g { border-top:1.5px solid #333; font-weight:bold; }
.foot { margin-top:16mm; font-size:8pt; color:#555; border-top:.5px solid #ccc; padding-top:3mm; }
.bavure { color:#8a8a8a; filter:blur(1.7px); letter-spacing:.06em; }
"""


def montant(x: float, devise: str = "EUR") -> str:
    return f"{x:,.2f}".replace(",", " ").replace(".", ",") + " " + devise


def document(*, fournisseur: str, numero: str, date: str, lignes: list[dict],
             total_ht: float | None, total_ttc: float | None, devise: str = "EUR",
             titre: str = "FACTURE", entete_detail: str = "DETAIL DES PRESTATIONS",
             mention_tva: str | None = None, numero_html: str | None = None,
             pied: str = "Reglement par virement sous 30 jours.") -> str:
    def total_imprime(l: dict) -> str:
        # `total_imprime` permet de forcer un montant de ligne different du
        # produit quantite x prix unitaire, pour reproduire une erreur de calcul
        # commise par le fournisseur sur son propre document.
        if l.get("total_imprime") is not None:
            return montant(l["total_imprime"], devise)
        if l.get("quantite") is None or l.get("prix_unitaire") is None:
            return ""
        return montant(l["quantite"] * l["prix_unitaire"], devise)

    rows = "".join(
        f"<tr><td>{l['designation']}</td>"
        f"<td class='n'>{'' if l.get('quantite') is None else l['quantite']}</td>"
        f"<td class='n'>{'' if l.get('prix_unitaire') is None else montant(l['prix_unitaire'], devise)}</td>"
        f"<td class='n'>{total_imprime(l)}</td></tr>"
        for l in lignes)

    bloc_totaux = ""
    if total_ht is not None:
        bloc_totaux += f"<div><span>Total HT</span><span>{montant(total_ht, devise)}</span></div>"
    if total_ht is not None and total_ttc is not None:
        bloc_totaux += f"<div><span>{mention_tva or 'TVA'}</span><span>{montant(total_ttc - total_ht, devise)}</span></div>"
    if total_ttc is not None:
        bloc_totaux += f"<div class='g'><span>Total TTC</span><span>{montant(total_ttc, devise)}</span></div>"

    num = numero_html if numero_html is not None else f"N° {numero}"
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<div class="hdr"><div><div class="sup">{fournisseur}</div>
<div style="font-size:9pt;color:#555;margin-top:2mm">7 avenue des Ateliers<br>69800 Saint-Priest<br>SIRET 000 000 000 00000</div></div>
<div class="meta"><b>{titre}</b><br>{num}<br>Date : {date}</div></div>
<h1>{entete_detail}</h1>
<table><thead><tr><th>Designation</th><th class="n">Qte</th><th class="n">P.U.</th><th class="n">Total</th></tr></thead>
<tbody>{rows}</tbody></table>
{f'<div class="tot">{bloc_totaux}</div>' if bloc_totaux else ''}
<div class="foot">{pied}</div></body></html>"""


# Chaque entree : (nom de fichier, ce que le cas teste, html)
CAS: list[tuple[str, str, str]] = [
    ("facture_11_ligne_mal_calculee",
     "Erreur de calcul commise par le fournisseur SUR SON PROPRE DOCUMENT : la ligne "
     "d'evacuation affiche 380,00 alors que 5 x 57,00 fait 285,00. Le total HT imprime, "
     "lui, est juste (1 119,20 = somme des produits reels), donc le controle global "
     "somme_lignes_vs_total_ht passe au VERT et ne voit rien. Seul le controle ligne a "
     "ligne detecte l'anomalie. C'est exactement le defaut releve par JUWA au debrief "
     "du 13/08/2026 : sans lui, le programme affichait sa propre valeur recalculee et "
     "corrigeait l'erreur du fournisseur en silence.",
     document(fournisseur="ATELIERS DELMAS", numero="FA-2026-0779", date="2026-06-04",
              lignes=[{"designation": "Electrovanne 4/3 centre ferme", "quantite": 3, "prix_unitaire": 187.4},
                      {"designation": "Kit evacuation renforce", "quantite": 5, "prix_unitaire": 57.0,
                       "total_imprime": 380.0},
                      {"designation": "Main d'oeuvre pose", "quantite": 4, "prix_unitaire": 68.0}],
              total_ht=1119.2, total_ttc=1343.04)),

    ("facture_5_prestation_sans_quantite",
     "Lignes forfaitaires sans quantite imprimee : les quantites doivent ressortir "
     "en `absent`, pas en `illisible`, et surtout pas en 1 invente.",
     document(fournisseur="CABINET RIVOIRE CONSEIL", numero="2026-0451", date="2026-04-18",
              lignes=[{"designation": "Audit de conformite documentaire, forfait", "quantite": None, "prix_unitaire": None},
                      {"designation": "Restitution et plan d'action, forfait", "quantite": None, "prix_unitaire": None},
                      {"designation": "Accompagnement, 3 demi-journees", "quantite": 3, "prix_unitaire": 640.0}],
              total_ht=5720.0, total_ttc=6864.0)),

    ("facture_6_tva_incoherente",
     "Rapport TTC/HT a 13,70 %, qui ne correspond a aucun taux francais : le controle "
     "doit lever une alerte au lieu de supposer que tout va bien.",
     document(fournisseur="HYDRO-SERVICES RHONE", numero="F-2026-118", date="2026-05-22",
              lignes=[{"designation": "Pompe a engrenages PGE-32", "quantite": 2, "prix_unitaire": 410.0},
                      {"designation": "Raccord tournant 3/8", "quantite": 8, "prix_unitaire": 27.5},
                      {"designation": "Main d'oeuvre atelier", "quantite": 6, "prix_unitaire": 68.0}],
              total_ht=1448.0, total_ttc=1646.4)),

    ("facture_7_numero_absent",
     "Aucun numero de facture imprime : le champ doit ressortir en `absent` sans "
     "declencher d'alerte, un document peut legitimement ne pas en porter.",
     document(fournisseur="ETS MARCHAND & FILS", numero="", date="2026-03-09",
              numero_html="<i>(sans reference)</i>",
              lignes=[{"designation": "Tole acier 3 mm, decoupe sur plan", "quantite": 12, "prix_unitaire": 84.5},
                      {"designation": "Pliage et ebavurage", "quantite": 12, "prix_unitaire": 19.0}],
              total_ht=1242.0, total_ttc=1490.4)),

    ("facture_8_numero_illisible",
     "Numero de facture imprime mais rendu illisible par une bavure d'encre : c'est "
     "le cas `illisible`, a distinguer du cas `absent` ci-dessus.",
     document(fournisseur="SOCIETE LYONNAISE DE JOINTS", numero="", date="2026-02-14",
              numero_html='N° <span class="bavure">FL&#8202;2&#8202;0&#8202;2&#8202;6&#8202;&#8212;&#8202;0&#8202;0&#8202;&#9608;&#9608;</span>',
              lignes=[{"designation": "Joint torique NBR 90 Shore, lot de 50", "quantite": 4, "prix_unitaire": 61.2},
                      {"designation": "Bague d'usure bronze BU-45", "quantite": 10, "prix_unitaire": 33.9}],
              total_ht=583.8, total_ttc=700.56)),

    ("facture_9_devise_dollars",
     "Facture libellee en dollars : limite connue du programme, qui suppose l'euro. "
     "Le but est de verifier qu'il ne plante pas et que le total reste coherent.",
     document(fournisseur="PACIFIC HYDRAULIC SUPPLY INC.", numero="INV-88420", date="2026-06-30",
              devise="USD", mention_tva="Sales tax 8.25 %",
              lignes=[{"designation": "Hydraulic cylinder HC-4400", "quantite": 3, "prix_unitaire": 512.0},
                      {"designation": "Seal kit SK-118", "quantite": 6, "prix_unitaire": 41.25}],
              total_ht=1783.5, total_ttc=1930.64,
              pied="Payment due within 30 days. Wire transfer only.")),

    ("facture_10_bon_de_livraison",
     "Ce n'est pas une facture mais un bon de livraison : aucun prix, aucun total. "
     "Le programme doit conclure `non_exploitable` au lieu d'inventer des montants.",
     document(fournisseur="TRANSPORTS BERTHOUD", numero="BL-2026-3391", date="2026-07-02",
              titre="BON DE LIVRAISON", entete_detail="ARTICLES LIVRES",
              lignes=[{"designation": "Verin VDE-80/45, palette 1/2", "quantite": 4, "prix_unitaire": None},
                      {"designation": "Kit joints KJ-2214, carton", "quantite": 12, "prix_unitaire": None},
                      {"designation": "Documentation technique, classeur", "quantite": 1, "prix_unitaire": None}],
              total_ht=None, total_ttc=None,
              pied="Marchandise recue en bon etat. Signature du destinataire : ______________")),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"{len(CAS)} cas limites :")
    for nom, description, html in CAS:
        chemin_html = OUT / f"{nom}.html"
        chemin_html.write_text(html, encoding="utf-8")
        pdf = OUT / f"{nom}.pdf"
        subprocess.run(
            [str(CHROME), "--headless=new", "--disable-gpu", "--no-sandbox",
             "--no-pdf-header-footer", "--virtual-time-budget=3000",
             f"--print-to-pdf={pdf}", chemin_html.as_uri()],
            check=True, capture_output=True, timeout=120)
        chemin_html.unlink()
        print(f"  {pdf.name:<38} {description.splitlines()[0]}")


if __name__ == "__main__":
    if not CHROME.exists():
        sys.exit(f"Chrome introuvable : {CHROME}")
    main()
