"""Regenere des factures PDF a partir des JSON de sortie fournis par JUWA.

Les PDF sources annonces dans le sujet n'etaient pas dans l'archive : seuls
quatre JSON d'exemple de sortie l'etaient. Ce script reconstruit un jeu de test
reproductible a partir de ces sorties attendues, pour pouvoir valider le
pipeline en attendant les originaux.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Surchargable par la variable d'environnement CHROME pour un poste ou Chrome
# est installe ailleurs (ou pour utiliser Edge, qui accepte les memes options).
CHROME = Path(os.environ.get("CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe"))
OUT = Path(__file__).resolve().parents[1] / "tests/fixtures"

CSS = """
@page { size: A4; margin: 18mm; }
body { font-family: Arial, Helvetica, sans-serif; font-size: 10pt; color: #111; }
.hdr { display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:14mm; }
.sup { font-size: 15pt; font-weight: bold; letter-spacing:.02em; }
.meta { text-align:right; font-size: 9.5pt; line-height:1.6; }
h1 { font-size: 12pt; margin: 0 0 6mm; letter-spacing:.08em; }
table { width:100%; border-collapse:collapse; font-size:9.5pt; }
th { text-align:left; border-bottom:1.5px solid #333; padding:2mm 1.5mm; }
td { border-bottom:.5px solid #ccc; padding:2mm 1.5mm; vertical-align:top; }
td.n, th.n { text-align:right; white-space:nowrap; }
.tot { margin-top:8mm; width:70mm; margin-left:auto; font-size:10pt; }
.tot div { display:flex; justify-content:space-between; padding:1.5mm 0; }
.tot .g { border-top:1.5px solid #333; font-weight:bold; }
.foot { margin-top:16mm; font-size:8pt; color:#555; border-top:.5px solid #ccc; padding-top:3mm; }
"""

def eur(x): return f"{x:,.2f}".replace(",", " ").replace(".", ",") + " EUR"

def html(d):
    rows = "".join(
        f"<tr><td>{l['designation']}</td><td class='n'>{l['quantite']}</td>"
        f"<td class='n'>{eur(l['prix_unitaire'])}</td>"
        f"<td class='n'>{eur(l['quantite'] * l['prix_unitaire'])}</td></tr>"
        for l in d["lignes_produits"])
    tva = d["total_TTC"] - d["total_HT"]
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<div class="hdr"><div><div class="sup">{d['nom_fournisseur']}</div>
<div style="font-size:9pt;color:#555;margin-top:2mm">12 rue de l'Industrie<br>38300 Bourgoin-Jallieu<br>SIRET 000 000 000 00000</div></div>
<div class="meta"><b>FACTURE</b><br>N° {d['numero_facture']}<br>Date : {d['date']}<br>Echeance : 30 jours</div></div>
<h1>DETAIL DES PRESTATIONS</h1>
<table><thead><tr><th>Designation</th><th class="n">Qte</th><th class="n">P.U. HT</th><th class="n">Total HT</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="tot"><div><span>Total HT</span><span>{eur(d['total_HT'])}</span></div>
<div><span>TVA</span><span>{eur(tva)}</span></div>
<div class="g"><span>Total TTC</span><span>{eur(d['total_TTC'])}</span></div></div>
<div class="foot">Reglement par virement. Penalites de retard : 3 fois le taux d'interet legal.
Indemnite forfaitaire pour frais de recouvrement : 40 EUR.</div></body></html>"""

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", type=Path, required=True,
                   help="Dossier contenant les JSON d'exemples de sortie fournis avec l'enonce.")
    args = p.parse_args()
    if not args.src.is_dir():
        sys.exit(f"Dossier introuvable : {args.src}")

    OUT.mkdir(parents=True, exist_ok=True)
    for jf in sorted(args.src.glob("*.json")):
        d = json.loads(jf.read_text(encoding="utf-8"))
        h = OUT / (jf.stem + ".html"); h.write_text(html(d), encoding="utf-8")
        pdf = OUT / (jf.stem + ".pdf")
        subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--no-sandbox",
                        "--no-pdf-header-footer", "--virtual-time-budget=3000",
                        f"--print-to-pdf={pdf}", h.as_uri()],
                       check=True, capture_output=True, timeout=120)
        h.unlink()
        print(f"  {pdf.name}  ({pdf.stat().st_size // 1024} Ko)")

if __name__ == "__main__":
    if not CHROME.exists(): sys.exit(f"Chrome introuvable : {CHROME}")
    main()
