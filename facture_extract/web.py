"""Interface web : depot d'une facture, lecture du resultat.

Parti pris d'interface : le role de cet ecran n'est pas d'afficher des donnees,
c'est de **rendre le doute visible**. Un champ non lu, un ecart de total, un
taux de TVA improbable doivent sauter aux yeux avant les valeurs elles-memes.
Une extraction presentee sans son niveau de certitude invite a faire confiance
a des chiffres qui ne le meritent pas toujours.

Parti pris graphique : un instrument de mesure, pas un tableau de bord. Le
lecteur est un comptable ou un responsable d'atelier dans une PME industrielle ;
il lit des bons de commande et des releves, pas des applications. D'ou les
reglures d'un registre, les chiffres en chasse fixe alignes a la virgule, le
verdict tamponne en tete, et une palette de papier plutot que de logiciel.
La typographie est la famille IBM Plex, dessinee pour la documentation technique.

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


# Au-dela, le passage en base64 (+33 %) vers l'API n'a de toute facon aucune
# chance d'aboutir : autant refuser tout de suite avec un message clair.
TAILLE_MAX = 20 * 1024 * 1024


@app.post("/api/extraire")
def api_extraire(fichier: UploadFile = File(...)) -> JSONResponse:
    """Handler volontairement synchrone : FastAPI l'execute dans un thread,
    et la boucle d'evenements reste disponible pendant les quelques secondes
    d'OCR et d'extraction. En `async def`, tout le serveur serait fige, y
    compris la page elle-meme."""
    if not (fichier.filename or "").lower().endswith(".pdf"):
        return JSONResponse({"erreur": "Seuls les fichiers PDF sont acceptes."}, status_code=400)

    donnees = fichier.file.read(TAILLE_MAX + 1)
    if len(donnees) > TAILLE_MAX:
        return JSONResponse(
            {"erreur": f"Fichier trop volumineux (plus de {TAILLE_MAX // (1024 * 1024)} Mo)."},
            status_code=413)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            # Nom neutre : un nom de fichier uploade peut contenir des
            # caracteres interdits par le systeme de fichiers.
            chemin = Path(tmp) / "document.pdf"
            chemin.write_bytes(donnees)
            facture = traiter(chemin)
    except RuntimeError as e:
        # Nos propres erreurs (cle absente...) sont pedagogiques : on les montre.
        return JSONResponse({"erreur": str(e)}, status_code=500)
    except Exception as e:
        # Le detail (chemins locaux, corps de reponse API) reste cote serveur.
        print(f"[extraire] {type(e).__name__}: {e}")
        return JSONResponse(
            {"erreur": f"Le traitement a echoue ({type(e).__name__}). "
                       f"Verifier que le fichier est un PDF valide et reessayer."},
            status_code=500)
    return JSONResponse(facture.model_dump(mode="json"))


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return PAGE


PAGE = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lecture de facture</title>
<style>
/* =====================================================================
   Design system « klein-lin » du lab-design : fond lin chaud, outremer
   franc, ardoise bleutee, mono pour les montants. Preset genere depuis ses
   tokens et incruste tel quel, pour que la page reste autonome : aucune
   ressource distante, donc aucun risque de rendu degrade en demonstration.
   Les composants ci-dessous ne parlent QU'a la couche haute (les roles),
   jamais a la couche matiere. C'est la regle du systeme, et c'est ce qui
   permet de rethemer sans toucher au balisage.
   ===================================================================== */
  /* klein-lin — assurance santé d'équipe B2B — fond lin chaud, outremer franc, ardoise bleutée, Candara + Calibri + mono montants, mode bleu nuit apaisé */
  /* GÉNÉRÉ par tools/build-tokens.mjs depuis design-systems/klein-lin/tokens.json — ne pas éditer à la main. */
  :root {
    --bg: #f4efe6;
    --fg: #1a2a3a;
    --accent: #1a4fc8;
    --muted: #5c6478;
    --line: #dbd3c4;
    --font-display: Candara, Optima, 'Gill Sans MT', 'Gill Sans', system-ui, sans-serif;
    --font-body: Calibri, Candara, system-ui, sans-serif;
    --font-mono: ui-monospace, 'Cascadia Mono', Consolas, 'Courier New', monospace;
    --radius: 10px;
    --border: 1px solid #dbd3c4;
    --shadow: 0 4px 18px -4px rgba(26, 79, 200, 0.10);
    --fg-soft: #4a5560;
    --fg-faint: #989c9e;
    --fg-inverse: #f4efe6;
    --surface-card: #fcfaf8;
    --surface-sunken: #e9e4dc;
    --line: #dbd3c4;
    --line-strong: #c4bfb3;
    --accent-text: #1a4fc8;
    --accent-ink: #fdfdfb;
    --accent-veil: #dadce2;
    --success: #196b40;
    --success-veil: #dadfd2;
    --warning: #74591b;
    --warning-veil: #e5ddce;
    --error: #7c2a1d;
    --error-veil: #e6d7ce;
    --focus-ring: #1a2a3a;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #141e2e;
      --fg: #e8eef8;
      --accent: #6b90ee;
      --muted: #8899b4;
      --line: #263449;
      --border: 1px solid #263449;
      --shadow: 0 4px 18px -4px rgba(0, 10, 30, 0.50);
      --fg-soft: #b9c0cc;
      --fg-faint: #6d7583;
      --fg-inverse: #141e2e;
      --surface-card: #212a39;
      --surface-sunken: #0c121c;
      --line: #263449;
      --line-strong: #3d4a5e;
      --accent-text: #6b90ee;
      --accent-ink: #2a2b2d;
      --accent-veil: #1e2c45;
      --success: #6adc9f;
      --success-veil: #1e353c;
      --warning: #dcba6a;
      --warning-veil: #2c3135;
      --error: #dc796a;
      --error-veil: #2c2935;
      --focus-ring: #e8eef8;
    }
  }
/* ---------------------------------------------------------------------
   Composants. Parti pris : un formulaire d'atelier, pas une application.
   Le lecteur est comptable ou responsable de production dans une PME
   industrielle : il lit des bons et des releves, pas des logiciels. D'ou
   la grille stricte, les filets pleins, les chiffres en chasse fixe
   alignes a la virgule, et le verdict pose en tete comme un tampon.
   --------------------------------------------------------------------- */
*{box-sizing:border-box}
body{margin:0; background:var(--surface-sunken); color:var(--fg);
  font-family:var(--font-body); font-size:15px; line-height:1.5; -webkit-font-smoothing:antialiased}

header{background:var(--fg); color:var(--fg-inverse); padding:26px 24px}
.bande{max-width:940px; margin:0 auto; display:flex; align-items:baseline; gap:18px; flex-wrap:wrap}
header .num{font-size:11px; letter-spacing:.28em; text-transform:uppercase; color:var(--fg-faint)}
header h1{margin:0; font-family:var(--font-display); font-size:25px; font-weight:700; letter-spacing:-.02em}
header p{margin:0; font-size:13px; color:#b8b8b8; max-width:54ch}

main{max-width:940px; margin:0 auto; padding:26px 24px 24px}
.bloc{background:var(--surface-card); border:var(--border); border-radius:var(--radius)}

.depot{display:block; padding:34px 22px; text-align:center; cursor:pointer;
  border-bottom:var(--border); transition:background .12s}
.depot:hover,.depot.actif{background:var(--surface-sunken)}
.depot strong{display:block; font-family:var(--font-display); font-size:17px; font-weight:700}
.depot span{display:block; margin-top:3px; font-size:13px; color:var(--fg-soft)}
.depot input{display:none}
.regle{height:7px; border-bottom:var(--border);
  background:repeating-linear-gradient(90deg,var(--line) 0 1px,transparent 1px 14px)}

.exemples{display:flex; flex-wrap:wrap; align-items:stretch; border-bottom:var(--border)}
.exemples b{font-size:10px; letter-spacing:.2em; text-transform:uppercase; color:var(--fg-soft);
  padding:11px 14px; border-right:var(--border); display:flex; align-items:center}
.exemples button{font:inherit; font-size:12.5px; padding:11px 14px; cursor:pointer; background:transparent;
  border:0; border-right:var(--border); color:var(--fg); text-align:left}
.exemples button:hover{background:var(--fg); color:var(--fg-inverse)}
.etat{padding:12px 16px; font-size:13px; color:var(--fg-soft)}
.etat:empty{display:none}
.etat.charge::after{content:""; display:inline-block; width:6px; height:6px; margin-left:8px;
  background:var(--accent); animation:bat .9s steps(1) infinite}
@keyframes bat{0%,50%{opacity:1}51%,100%{opacity:0}}

#res:empty{display:none}
#res>*{animation:entre .3s ease both}
@keyframes entre{from{opacity:0; transform:translateY(6px)}to{opacity:1; transform:none}}

.verdict{display:flex; align-items:center; gap:16px; flex-wrap:wrap;
  padding:18px 22px; border-top:var(--border); border-bottom:var(--border)}
.tampon{font-family:var(--font-display); font-weight:700; font-size:17px; letter-spacing:.1em;
  text-transform:uppercase; padding:6px 14px; border:2px solid currentColor}
.v-fiable{background:var(--success-veil); color:var(--success)}
.v-a_verifier{background:var(--warning-veil); color:var(--warning)}
.v-non_exploitable{background:var(--error-veil); color:var(--error)}
.verdict .info{font-size:12px; color:var(--fg-soft);
  font-family:ui-monospace,Consolas,monospace; font-variant-numeric:tabular-nums}

section{padding:20px 22px; border-bottom:var(--border)}
section:last-of-type{border-bottom:0}
section h2{margin:0 0 14px; font-family:var(--font-display); font-size:11px; font-weight:700;
  letter-spacing:.22em; text-transform:uppercase; display:flex; align-items:center; gap:12px}
section h2::after{content:""; flex:1; height:1px; background:var(--line)}
section h2 .compte{font-family:ui-monospace,Consolas,monospace; letter-spacing:0; color:var(--fg-soft)}

.champs{display:grid; grid-template-columns:repeat(5,1fr);
  gap:1px; background:var(--line); border:var(--border)}
@media(max-width:860px){
  .champs{grid-template-columns:repeat(2,1fr)}
  .champ:last-child{grid-column:1/-1}
}
.champ{background:var(--surface-card); padding:11px 13px}
.champ .lib{font-size:10px; letter-spacing:.16em; text-transform:uppercase; color:var(--fg-soft)}
.champ .val{margin-top:4px; font-family:ui-monospace,Consolas,monospace; font-size:16px;
  font-variant-numeric:tabular-nums; word-break:break-word}
.champ .val.nul{color:var(--accent-text); font-size:14px}
.champ .note{margin-top:5px; font-size:10px; letter-spacing:.13em; text-transform:uppercase}
.n-illisible{color:var(--accent-text)} .n-absent{color:var(--fg-faint)}
.champ.tendu{box-shadow:inset 4px 0 0 var(--accent)}

table{width:100%; border-collapse:collapse; font-size:14px}
thead th{font-size:10px; letter-spacing:.16em; text-transform:uppercase; color:var(--fg-soft);
  text-align:left; font-weight:700; padding:0 10px 8px; border-bottom:2px solid var(--line-strong)}
tbody td{padding:9px 10px; border-bottom:1px solid var(--line); vertical-align:top}
tbody tr:last-child td{border-bottom:0}
td.n,th.n{text-align:right; white-space:nowrap;
  font-family:ui-monospace,Consolas,monospace; font-variant-numeric:tabular-nums}
td.calc{color:var(--fg-soft)}
.note-bas{margin:12px 0 0; font-size:12px; color:var(--fg-soft)}

.ctrl{display:grid; grid-template-columns:22px 208px 1fr; gap:12px; align-items:start;
  padding:9px 0; border-bottom:1px solid var(--line)}
.ctrl:last-of-type{border-bottom:0}
.marque{font-family:ui-monospace,Consolas,monospace; font-weight:700; text-align:center}
.m-ok{color:var(--success)} .m-echec{color:var(--accent)} .m-non_applicable{color:var(--fg-faint)}
.ctrl .nom{font-family:ui-monospace,Consolas,monospace; font-size:12px; color:var(--fg-soft)}
.ctrl .txt{font-size:13.5px}
.ctrl.echec .txt{color:var(--accent-text)}

.av{display:grid; grid-template-columns:74px 1fr; gap:14px;
  padding:13px 0; border-bottom:1px solid var(--line)}
.av:last-of-type{border-bottom:0}
.grav{font-size:9.5px; font-weight:700; letter-spacing:.14em; text-transform:uppercase;
  padding:4px 0; text-align:center; height:fit-content; border:1px solid currentColor}
.g-info{background:var(--surface-sunken); color:var(--fg-soft)}
.g-alerte{background:var(--warning-veil); color:var(--warning)}
.g-bloquant{background:var(--error-veil); color:var(--error)}
.av .code{font-family:ui-monospace,Consolas,monospace; font-size:11px; color:var(--fg-soft)}
.av .msg{margin-top:3px; font-size:13.5px}

.jauge{margin-top:12px; padding:12px 14px; background:var(--surface-sunken); border:1px solid var(--line)}
.jauge .ecarte{font-family:ui-monospace,Consolas,monospace; font-size:15px; color:var(--accent-text);
  text-decoration:line-through; text-decoration-thickness:2px}
.jauge .piste{position:relative; height:10px; margin:10px 0 6px;
  background:var(--surface-card); border:1px solid var(--line-strong)}
.jauge .rempli{position:absolute; top:0; bottom:0; left:0; background:var(--accent)}
.jauge .seuil{position:absolute; top:-5px; bottom:-5px; width:2px; background:var(--fg)}
.jauge .grad{display:flex; justify-content:space-between; font-size:11px;
  font-family:ui-monospace,Consolas,monospace; color:var(--fg-soft)}
.jauge .grad .bas{color:var(--accent-text); font-weight:700}

details{padding:16px 22px 22px; border-top:var(--border)}
summary{cursor:pointer; font-size:10px; letter-spacing:.2em; text-transform:uppercase; color:var(--fg-soft)}
summary:hover{color:var(--fg)}
pre{margin:12px 0 0; padding:15px; background:var(--fg); color:var(--fg-inverse); overflow:auto;
  font-family:ui-monospace,Consolas,monospace; font-size:11.5px; line-height:1.5}
.erreur{padding:20px 22px; border-top:var(--border); color:var(--accent-text)}
footer{max-width:940px; margin:0 auto; padding:0 24px 40px; font-size:11.5px; color:var(--fg-faint)}
@media(max-width:620px){
  .ctrl{grid-template-columns:20px 1fr; row-gap:2px}
  .ctrl .txt{grid-column:2}
}
</style></head><body>

<header><div class="bande">
  <span class="num">01</span>
  <h1>Lecture de facture</h1>
  <p>Ce qui n&#39;a pas ete lu de facon sure est signale et laisse vide. Aucune valeur n&#39;est devinee.</p>
</div></header>

<main>
  <div class="bloc">
    <label class="depot" id="depot">
      <strong>Deposer une facture PDF</strong>
      <span>ou cliquer pour choisir un fichier</span>
      <input type="file" id="fichier" accept="application/pdf">
    </label>
    <div class="regle"></div>
    <div class="exemples" id="exemples"></div>
    <div class="etat" id="etat"></div>
    <div id="res"></div>
  </div>
</main>

<footer>Extraction par l&#39;API Mistral. Verifications arithmetiques par le programme, sans modele.</footer>

<script>
const $ = s => document.querySelector(s);
const depot = $("#depot"), input = $("#fichier"), etat = $("#etat"), res = $("#res");
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const eur = v => v == null ? null
  : v.toLocaleString("fr-FR",{minimumFractionDigits:2,maximumFractionDigits:2}) + " EUR";
const pc  = v => v == null ? "n/a" : Math.round(v*100) + " %";

["dragenter","dragover"].forEach(e=>depot.addEventListener(e,ev=>{ev.preventDefault();depot.classList.add("actif")}));
["dragleave","drop"].forEach(e=>depot.addEventListener(e,ev=>{ev.preventDefault();depot.classList.remove("actif")}));
depot.addEventListener("drop",ev=>{ if(ev.dataTransfer.files[0]) envoyer(ev.dataTransfer.files[0]) });
input.addEventListener("change",()=>{ if(input.files[0]) envoyer(input.files[0]) });

fetch("/api/exemples").then(r=>r.json()).then(l=>{
  if(!l.length) return;
  const z = $("#exemples");
  z.innerHTML = "<b>Jeu de test</b>";
  l.forEach(n=>{
    const b = document.createElement("button");
    b.textContent = n.replace(/^facture_\d+_/,"").replace(/\.pdf$/,"").replace(/_/g," ");
    b.onclick = () => chargerExemple(n);
    z.appendChild(b);
  });
  // Lien direct : /#facture_2_studio_botanica.pdf charge l'exemple a l'ouverture.
  const cible = decodeURIComponent(location.hash.slice(1));
  if (cible && l.includes(cible)) chargerExemple(cible);
});

async function chargerExemple(n){
  etat.className = "etat charge"; etat.textContent = "Lecture de " + n;
  const blob = await (await fetch("/api/exemple/" + encodeURIComponent(n))).blob();
  envoyer(new File([blob], n, {type:"application/pdf"}));
}

async function envoyer(f){
  res.innerHTML = ""; etat.className = "etat charge"; etat.textContent = "Lecture de " + f.name;
  const fd = new FormData(); fd.append("fichier", f);
  try{
    const r = await fetch("/api/extraire",{method:"POST",body:fd,signal:AbortSignal.timeout(180000)});
    const d = await r.json();
    etat.className = "etat"; etat.textContent = "";
    if(!r.ok){ res.innerHTML = '<div class="erreur">' + esc(d.erreur) + '</div>'; return; }
    afficher(d, f.name);
  }catch(e){ etat.className="etat"; etat.textContent = "Erreur reseau : " + e.message; }
}

function champ(nom, libelle, d){
  const e = d.meta.etats_champs[nom], v = d[nom];
  const aff = typeof v === "number" ? eur(v) : v;
  const corps = v == null
    ? '<div class="val nul">' + (e === "illisible" ? "non lu" : "sans objet") + '</div>'
    : '<div class="val">' + esc(aff) + '</div>';
  const note = e === "lu" ? ""
    : '<div class="note n-' + e + '">' + (e === "illisible" ? "illisible sur le document" : "absent du document") + '</div>';
  return '<div class="champ' + (e === "illisible" ? " tendu" : "") + '">'
       + '<div class="lib">' + libelle + '</div>' + corps + note + '</div>';
}

function jauge(a){
  if(a.confiance == null || a.seuil == null) return "";
  const c = a.confiance*100, s = a.seuil*100;
  return '<div class="jauge">'
    + '<div>lecture ecartee : <span class="ecarte">' + esc(a.valeur_ecartee ?? "") + '</span></div>'
    + '<div class="piste"><div class="rempli" style="width:' + c.toFixed(1) + '%"></div>'
    + '<div class="seuil" style="left:' + s.toFixed(1) + '%" title="seuil d\'acceptation"></div></div>'
    + '<div class="grad"><span class="bas">confiance ' + c.toFixed(0) + ' %</span>'
    + '<span>seuil ' + s.toFixed(0) + ' %</span></div></div>';
}

function afficher(d, nom){
  const m = d.meta, st = m.statut_global;
  const mot = {fiable:"Exploitable", a_verifier:"A verifier", non_exploitable:"Non exploitable"}[st] || st;
  const echecs = m.controles.filter(c=>c.resultat === "echec").length;
  const marques = {ok:"\u2713", echec:"\u2715", non_applicable:"\u2013"};

  const lignes = d.lignes_produits.length
    ? '<table><thead><tr><th>Designation</th><th class="n">Qte</th><th class="n">P.U. HT</th><th class="n">Total</th></tr></thead><tbody>'
      + d.lignes_produits.map(l =>
          '<tr><td>' + (l.designation == null ? '<span class="val nul">non lu</span>' : esc(l.designation)) + '</td>'
          + '<td class="n">' + (l.quantite ?? "\u2013") + '</td>'
          + '<td class="n">' + (eur(l.prix_unitaire) ?? "\u2013") + '</td>'
          + '<td class="n calc">' + (eur(l.total_ligne) ?? "\u2013") + '</td></tr>').join("")
      + '</tbody></table><p class="note-bas">La colonne Total est calculee par le programme, elle n\'est pas lue sur le document.</p>'
    : '<p class="note-bas">Aucune ligne n\'a pu etre extraite.</p>';

  res.innerHTML =
    '<div class="verdict v-' + st + '"><span class="tampon">' + mot + '</span>'
  + '<span class="info">' + esc(nom) + ' &nbsp;/&nbsp; ' + m.duree_ms + ' ms &nbsp;/&nbsp; lecture '
  + pc(m.confiance_ocr_moyenne) + ' &nbsp;/&nbsp; ' + echecs + ' controle(s) en echec &nbsp;/&nbsp; '
  + d.avertissements.length + ' avertissement(s)</span></div>'

  + '<section><h2>Facture</h2><div class="champs">'
  + champ("nom_fournisseur","Fournisseur",d) + champ("date","Date",d)
  + champ("numero_facture","Numero",d) + champ("total_HT","Total HT",d)
  + champ("total_TTC","Total TTC",d) + '</div></section>'

  + '<section><h2>Lignes <span class="compte">' + d.lignes_produits.length + '</span></h2>' + lignes + '</section>'

  + '<section><h2>Verifications</h2>'
  + m.controles.map(c => '<div class="ctrl ' + c.resultat + '">'
      + '<span class="marque m-' + c.resultat + '">' + (marques[c.resultat] || "?") + '</span>'
      + '<span class="nom">' + esc(c.nom) + '</span>'
      + '<span class="txt">' + esc(c.detail) + '</span></div>').join("")
  + '<p class="note-bas">Ces verifications sont faites par le programme, sans intervention d\'un modele.</p></section>'

  + '<section><h2>Avertissements <span class="compte">' + d.avertissements.length + '</span></h2>'
  + (d.avertissements.length
      ? d.avertissements.map(a => '<div class="av"><span class="grav g-' + a.gravite + '">' + a.gravite + '</span>'
          + '<div><div class="code">' + esc(a.code) + (a.champ ? " &rarr; " + esc(a.champ) : "") + '</div>'
          + '<div class="msg">' + esc(a.message) + '</div>' + jauge(a) + '</div></div>').join("")
      : '<p class="note-bas">Aucun.</p>')
  + '</section>'

  + '<details><summary>Donnees completes (JSON)</summary><pre>' + esc(JSON.stringify(d,null,2)) + '</pre></details>';

  [...res.children].forEach((el,i)=>{ el.style.animationDelay = (i*55) + "ms" });
}
</script></body></html>
"""
