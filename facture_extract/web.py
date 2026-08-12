"""Interface web : depot d'une facture, lecture du resultat.

Parti pris d'interface : le role de cet ecran n'est pas d'afficher des donnees,
c'est de **rendre le doute visible**. Un champ non lu, un ecart de total, un
taux de TVA improbable doivent sauter aux yeux avant les valeurs elles-memes.
Une extraction presentee sans son niveau de certitude invite a faire confiance
a des chiffres qui ne le meritent pas toujours.

Choix technique : une seule page, servie par le meme processus que l'API,
sans etape de build ni dependance front. Le projet s'installe avec un
`pip install` et se lance avec une commande, ce qui tient la contrainte de
mise en route en moins de cinq minutes et rend la demonstration en direct
previsible.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .pipeline import traiter

app = FastAPI(title="Extraction de factures", docs_url="/api")


DOSSIER_EXEMPLES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"


@app.get("/api/exemples")
def api_exemples() -> JSONResponse:
    """Liste les factures du jeu de test, pour pouvoir demontrer sans chercher un fichier."""
    if not DOSSIER_EXEMPLES.is_dir():
        return JSONResponse([])
    return JSONResponse(sorted(p.name for p in DOSSIER_EXEMPLES.glob("*.pdf")))


@app.get("/api/exemple/{nom}", response_model=None)
def api_exemple(nom: str):
    chemin = (DOSSIER_EXEMPLES / Path(nom).name).resolve()
    if not chemin.is_file() or DOSSIER_EXEMPLES.resolve() not in chemin.parents:
        return JSONResponse({"erreur": "Exemple introuvable."}, status_code=404)
    return FileResponse(chemin, media_type="application/pdf", filename=chemin.name)


@app.post("/api/extraire")
async def api_extraire(fichier: UploadFile = File(...)) -> JSONResponse:
    if not (fichier.filename or "").lower().endswith(".pdf"):
        return JSONResponse({"erreur": "Seuls les fichiers PDF sont acceptes."}, status_code=400)

    with tempfile.TemporaryDirectory() as tmp:
        chemin = Path(tmp) / Path(fichier.filename).name
        chemin.write_bytes(await fichier.read())
        try:
            facture = traiter(chemin)
        except Exception as e:
            return JSONResponse({"erreur": f"{type(e).__name__} : {e}"}, status_code=500)
    return JSONResponse(facture.model_dump(mode="json"))


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return PAGE


PAGE = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Extraction de factures</title>
<style>
  :root {
    --bg:#f6f7f9; --card:#fff; --txt:#15202b; --mut:#657084; --bord:#dde2e9;
    --ok:#1a7f4b; --ok-bg:#e8f6ee; --warn:#a8660a; --warn-bg:#fdf3e3;
    --bad:#b3261e; --bad-bg:#fdeceb; --acc:#24405e;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--txt); font:15px/1.5 "Segoe UI",Roboto,Arial,sans-serif; }
  header { background:var(--acc); color:#fff; padding:18px 28px; }
  header h1 { margin:0; font-size:19px; font-weight:650; letter-spacing:-.01em; }
  header p { margin:3px 0 0; font-size:13px; opacity:.8; }
  main { max-width:1000px; margin:0 auto; padding:24px 20px 60px; }
  .depot { background:var(--card); border:2px dashed var(--bord); border-radius:12px;
           padding:34px; text-align:center; cursor:pointer; transition:.15s; }
  .depot:hover, .depot.actif { border-color:var(--acc); background:#f0f4f9; }
  .depot strong { display:block; font-size:16px; margin-bottom:4px; }
  .depot span { color:var(--mut); font-size:13px; }
  .depot input { display:none; }
  .etat { margin-top:16px; color:var(--mut); font-size:14px; }
  .carte { background:var(--card); border:1px solid var(--bord); border-radius:12px;
           padding:20px 22px; margin-top:18px; }
  .carte h2 { margin:0 0 14px; font-size:15px; letter-spacing:.02em; text-transform:uppercase;
              color:var(--mut); font-weight:650; }
  .bandeau { display:flex; align-items:center; gap:12px; flex-wrap:wrap;
             padding:14px 18px; border-radius:10px; margin-top:18px; font-weight:600; }
  .bandeau small { font-weight:400; opacity:.85; }
  .st-fiable { background:var(--ok-bg); color:var(--ok); border:1px solid #bfe3cd; }
  .st-a_verifier { background:var(--warn-bg); color:var(--warn); border:1px solid #f0d9ac; }
  .st-non_exploitable { background:var(--bad-bg); color:var(--bad); border:1px solid #f2c3bf; }
  .champs { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:14px; }
  .champ label { display:block; font-size:12px; color:var(--mut); margin-bottom:3px; }
  .champ .v { font-size:16px; font-weight:600; word-break:break-word; }
  .champ .v.vide { color:var(--bad); font-weight:500; font-style:italic; }
  .chip { display:inline-block; font-size:11px; padding:1px 7px; border-radius:20px;
          margin-left:6px; vertical-align:middle; font-weight:600; }
  .c-illisible { background:var(--bad-bg); color:var(--bad); }
  .c-absent { background:#eef0f3; color:var(--mut); }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th { text-align:left; font-size:12px; text-transform:uppercase; color:var(--mut);
       border-bottom:1px solid var(--bord); padding:6px 8px; }
  td { padding:7px 8px; border-bottom:1px solid #eef1f4; vertical-align:top; }
  td.n, th.n { text-align:right; white-space:nowrap; }
  .ligne { display:flex; gap:10px; padding:8px 0; border-bottom:1px solid #eef1f4; font-size:14px; }
  .ligne:last-child { border-bottom:0; }
  .pastille { flex:0 0 auto; font-size:11px; font-weight:700; padding:2px 8px; border-radius:5px; height:fit-content; }
  .p-ok { background:var(--ok-bg); color:var(--ok); }
  .p-echec { background:var(--bad-bg); color:var(--bad); }
  .p-na { background:#eef0f3; color:var(--mut); }
  .p-info { background:#e9eef6; color:var(--acc); }
  .p-alerte { background:var(--warn-bg); color:var(--warn); }
  .p-bloquant { background:var(--bad-bg); color:var(--bad); }
  .nom { font-family:Consolas,monospace; font-size:12.5px; color:var(--mut); flex:0 0 190px; }
  details { margin-top:18px; } summary { cursor:pointer; color:var(--mut); font-size:13px; }
  pre { background:#0f1720; color:#d7dee8; padding:16px; border-radius:10px; overflow:auto;
        font-size:12px; line-height:1.45; margin-top:10px; }
  .pied { margin-top:12px; font-size:12px; color:var(--mut); }
  .exemples { margin-top:12px; display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  .exemples b { font-size:12px; color:var(--mut); font-weight:600; margin-right:2px; }
  .exemples button { font:inherit; font-size:12.5px; padding:5px 11px; border-radius:20px;
    border:1px solid var(--bord); background:var(--card); color:var(--acc); cursor:pointer; }
  .exemples button:hover { border-color:var(--acc); background:#f0f4f9; }
</style></head><body>
<header>
  <h1>Extraction de factures fournisseurs</h1>
  <p>Les valeurs non lues et les incoherences sont signalees. Aucune valeur n'est devinee.</p>
</header>
<main>
  <label class="depot" id="depot">
    <strong>Deposer une facture PDF</strong>
    <span>ou cliquer pour choisir un fichier</span>
    <input type="file" id="fichier" accept="application/pdf">
  </label>
  <div class="exemples" id="exemples"></div>
  <div class="etat" id="etat"></div>
  <div id="res"></div>
</main>
<script>
const $ = s => document.querySelector(s);
const depot = $("#depot"), input = $("#fichier"), etat = $("#etat"), res = $("#res");
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const eur = v => v == null ? null : v.toLocaleString("fr-FR", {minimumFractionDigits:2, maximumFractionDigits:2}) + " EUR";

["dragenter","dragover"].forEach(e => depot.addEventListener(e, ev => { ev.preventDefault(); depot.classList.add("actif"); }));
["dragleave","drop"].forEach(e => depot.addEventListener(e, ev => { ev.preventDefault(); depot.classList.remove("actif"); }));
depot.addEventListener("drop", ev => { if (ev.dataTransfer.files[0]) envoyer(ev.dataTransfer.files[0]); });
input.addEventListener("change", () => { if (input.files[0]) envoyer(input.files[0]); });

fetch("/api/exemples").then(r => r.json()).then(l => {
  if (!l.length) return;
  const z = $("#exemples");
  z.innerHTML = "<b>Jeu de test :</b>";
  l.forEach(n => {
    const b = document.createElement("button");
    b.textContent = n.replace(/^facture_\d+_/, "").replace(/\.pdf$/, "").replace(/_/g, " ");
    b.onclick = async () => {
      etat.textContent = "Chargement de " + n + "...";
      const blob = await (await fetch("/api/exemple/" + encodeURIComponent(n))).blob();
      envoyer(new File([blob], n, { type: "application/pdf" }));
    };
    z.appendChild(b);
  });
});

async function envoyer(f) {
  res.innerHTML = ""; etat.textContent = `Lecture de ${f.name} en cours...`;
  const fd = new FormData(); fd.append("fichier", f);
  try {
    const r = await fetch("/api/extraire", { method:"POST", body:fd });
    const d = await r.json();
    etat.textContent = "";
    if (!r.ok) { res.innerHTML = `<div class="bandeau st-non_exploitable">${esc(d.erreur)}</div>`; return; }
    afficher(d, f.name);
  } catch (e) { etat.textContent = "Erreur reseau : " + e.message; }
}

function champ(nom, libelle, d) {
  const etatChamp = d.meta.etats_champs[nom], v = d[nom];
  const chip = etatChamp === "lu" ? "" : `<span class="chip c-${etatChamp}">${etatChamp}</span>`;
  const affiche = typeof v === "number" ? eur(v) : v;
  const val = v == null
    ? `<span class="v vide">non renseigne</span>`
    : `<span class="v">${esc(affiche)}</span>`;
  return `<div class="champ"><label>${libelle}</label>${val}${chip}</div>`;
}

function afficher(d, nom) {
  const m = d.meta, st = m.statut_global;
  const libelleStatut = { fiable:"Exploitable", a_verifier:"A verifier par un humain", non_exploitable:"Non exploitable" }[st] || st;
  const echecs = m.controles.filter(c => c.resultat === "echec").length;

  const lignes = d.lignes_produits.length ? `
    <table><thead><tr><th>Designation</th><th class="n">Qte</th><th class="n">P.U. HT</th><th class="n">Total</th></tr></thead><tbody>
    ${d.lignes_produits.map(l => `<tr>
      <td>${l.designation == null ? '<span class="v vide">non lu</span>' : esc(l.designation)}</td>
      <td class="n">${l.quantite ?? "-"}</td>
      <td class="n">${eur(l.prix_unitaire) ?? "-"}</td>
      <td class="n">${eur(l.total_ligne) ?? "-"}</td></tr>`).join("")}
    </tbody></table>
    <div class="pied">La colonne Total est calculee par le programme, elle n'est pas lue sur le document.</div>`
    : `<div class="v vide">Aucune ligne extraite.</div>`;

  res.innerHTML = `
  <div class="bandeau st-${st}">${libelleStatut}
    <small>${esc(nom)} · ${m.duree_ms} ms · confiance de lecture
    ${m.confiance_ocr_moyenne == null ? "n/a" : Math.round(m.confiance_ocr_moyenne * 100) + " %"}
    · ${echecs} controle(s) en echec · ${d.avertissements.length} avertissement(s)</small></div>

  <div class="carte"><h2>Facture</h2><div class="champs">
    ${champ("nom_fournisseur","Fournisseur",d)}
    ${champ("date","Date",d)}
    ${champ("numero_facture","Numero",d)}
    ${champ("total_HT","Total HT",d)}
    ${champ("total_TTC","Total TTC",d)}
  </div></div>

  <div class="carte"><h2>Lignes (${d.lignes_produits.length})</h2>${lignes}</div>

  <div class="carte"><h2>Controles deterministes</h2>
    ${m.controles.map(c => `<div class="ligne">
      <span class="pastille p-${c.resultat === "non_applicable" ? "na" : c.resultat}">${c.resultat === "non_applicable" ? "n/a" : c.resultat}</span>
      <span class="nom">${esc(c.nom)}</span><span>${esc(c.detail)}</span></div>`).join("")}
    <div class="pied">Ces verifications sont faites par du code, sans intervention d'un modele.</div>
  </div>

  <div class="carte"><h2>Avertissements (${d.avertissements.length})</h2>
    ${d.avertissements.length
      ? d.avertissements.map(a => `<div class="ligne">
          <span class="pastille p-${a.gravite}">${a.gravite}</span>
          <span class="nom">${esc(a.code)}</span><span>${esc(a.message)}</span></div>`).join("")
      : `<div style="color:var(--mut)">Aucun.</div>`}
  </div>

  <details><summary>Voir le JSON complet</summary><pre>${esc(JSON.stringify(d, null, 2))}</pre></details>`;
}
</script></body></html>
"""
