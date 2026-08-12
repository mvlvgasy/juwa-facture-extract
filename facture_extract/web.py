"""Interface web : depot d'une facture, lecture du resultat.

Parti pris d'interface : le role de cet ecran n'est pas d'afficher des donnees,
c'est de **rendre le doute visible**. Un champ non lu, un ecart de total, un
taux de TVA improbable doivent sauter aux yeux avant les valeurs elles-memes.
Une extraction presentee sans son niveau de certitude invite a faire confiance
a des chiffres qui ne le meritent pas toujours.

Disposition : bandeau de verdict en tete, puis deux colonnes. A gauche ce que
le document dit (champs, lignes), a droite ce que le programme en pense
(verifications, avertissements). Le doute reste donc epingle a l'ecran pendant
qu'on lit les valeurs, au lieu d'etre relegue en bas de page. La somme des
lignes est recalculee juste sous le tableau, a cote du total imprime : c'est
ce rapprochement qui rend un ecart visible sans avoir a le chercher.

Deuxieme parti pris : l'ecran ne s'arrete pas au constat. Signaler qu'un
montant est douteux sans permettre de le trancher laisserait l'utilisateur
devant un cul-de-sac. Le document d'origine s'ouvre donc a cote des valeurs,
et un mode correction permet de reprendre a la main ce que la lecture
automatique n'a pas su etablir. La reprise ne contourne pas les controles :
elle les relance.

Choix technique : une seule page, servie par le meme processus que l'API,
sans etape de build ni dependance front. Le projet s'installe avec un
`pip install` et se lance avec une commande, ce qui tient la contrainte de
mise en route en moins de cinq minutes et rend la demonstration previsible.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .pipeline import revalider, traiter
from .schema import Facture

app = FastAPI(title="Extraction de factures", docs_url="/api")

DOSSIER_EXEMPLES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

# Au-dela, le passage en base64 (+33 %) vers l'API n'a de toute facon aucune
# chance d'aboutir : autant refuser tout de suite avec un message clair.
TAILLE_MAX = 20 * 1024 * 1024


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


class DemandeRevalidation(BaseModel):
    """Corps de `/api/revalider` : le document lu, et ce que l'humain corrige."""

    facture: Facture
    corrections: dict = Field(
        default_factory=dict,
        description="Champs a plat et/ou `lignes_produits`. Un champ absent n'est pas touche.")


@app.post("/api/revalider")
def api_revalider(demande: DemandeRevalidation) -> JSONResponse:
    """Rejoue les controles sur des valeurs corrigees a la main.

    Aucun appel a l'API : on ne relit pas le document, on recalcule. La
    correction est donc instantanee et gratuite, ce qui compte quand un
    comptable reprend cinquante factures dans la journee.
    """
    try:
        corrigee = revalider(demande.facture, demande.corrections)
    except ValueError as e:
        return JSONResponse({"erreur": str(e)}, status_code=400)
    return JSONResponse(corrigee.model_dump(mode="json"))


@app.get("/", response_class=HTMLResponse)
def page() -> str:
    return PAGE


PAGE = r"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Controle factures</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400;12..96,500;12..96,600;12..96,700;12..96,800&family=Red+Hat+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
/* =====================================================================
   Jetons. Fond lin chaud et outremer, chiffres en chasse fixe. Tout est
   ici, en un seul bloc : changer d'ambiance ne demande pas de toucher au
   balisage.
   ===================================================================== */
:root{
  --papier:#eee7d7; --panneau:#f6f1e4; --surface:#fbf8f1;
  --filet:#e0d7c2; --filet-doux:#efe8d6; --pointille:#c9bd9f;
  --encre:#2a251c; --doux:#5c5443; --mut:#7a715f;
  --bleu:#2f45c8; --bleu-fonce:#1f2f8e; --bleu-voile:#e8ebf9;
  --ambre:#a3641a; --ambre-bande:#f3e3c3; --ambre-titre:#7c4a0f;
  --ambre-texte:#8a6528; --ambre-voile:#f9efe0; --ambre-filet:#e6c98f;
  --ambre-tirets:#c9963f; --jauge:#ece1c8;
  --rouge:#b0402c; --rouge-voile:#f7e4de; --rouge-filet:#d09a8b; --rouge-doux:#96543f;
  --vert:#3d7c47; --vert-voile:#e7eee4; --vert-filet:#b9cdb4;
}
*{box-sizing:border-box}
body{margin:0;background:var(--papier);color:var(--encre);
  font-family:"Bricolage Grotesque",system-ui,sans-serif;font-size:14px;line-height:1.5;
  -webkit-font-smoothing:antialiased}
main{max-width:1240px;margin:0 auto;padding:26px 22px 60px}

.entete{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:18px}
.entete h1{margin:0;font-size:21px;font-weight:800;letter-spacing:-.01em}
.entete p{margin:0;font-size:13px;color:var(--mut)}

.depot{display:block;background:var(--panneau);border:1.5px dashed var(--filet);
  border-radius:10px;padding:34px 22px;text-align:center;cursor:pointer;transition:.14s}
.depot:hover,.depot.actif{border-color:var(--bleu);background:var(--bleu-voile)}
.depot strong{display:block;font-size:16px;font-weight:700}
.depot span{display:block;margin-top:3px;font-size:13px;color:var(--mut)}
.depot input{display:none}
.exemples{margin-top:12px;display:flex;gap:7px;flex-wrap:wrap;align-items:center}
.exemples b{font:600 10.5px "Red Hat Mono",monospace;letter-spacing:.14em;text-transform:uppercase;
  color:var(--mut);margin-right:3px}
.exemples button{font:500 12px "Red Hat Mono",monospace;padding:6px 11px;cursor:pointer;
  background:var(--surface);border:1px solid var(--filet);border-radius:16px;color:var(--encre);transition:.12s}
.exemples button:hover{border-color:var(--bleu);color:var(--bleu);background:var(--bleu-voile)}
.etat{margin-top:14px;font-size:13px;color:var(--mut)}
.etat:empty{display:none}
.etat.charge::after{content:"";display:inline-block;width:6px;height:6px;margin-left:8px;
  border-radius:50%;background:var(--ambre);animation:bat .9s steps(1) infinite}
@keyframes bat{0%,50%{opacity:1}51%,100%{opacity:0}}

#res:empty{display:none}
#res{margin-top:20px;animation:monte .3s ease both}
@keyframes monte{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
.doc{background:var(--panneau);border:1px solid var(--filet);border-radius:9px;
  box-shadow:0 1px 3px rgba(0,0,0,.06);overflow:hidden}

.barre{display:flex;align-items:center;gap:14px;flex-wrap:wrap;
  padding:14px 26px;border-bottom:1px solid var(--filet)}
.barre .titre{font-weight:800;font-size:15px}
.puce-fichier{font:500 12px "Red Hat Mono",monospace;color:var(--mut);background:var(--papier);
  border:1px solid var(--filet);border-radius:6px;padding:5px 10px}
.actions{margin-left:auto;display:flex;gap:10px}
.btn{font:600 13px "Bricolage Grotesque",sans-serif;border-radius:7px;padding:8px 14px;
  cursor:pointer;border:1.5px solid var(--bleu);background:transparent;color:var(--bleu);transition:.12s}
.btn:hover{background:var(--bleu-voile)}
.btn.plein{background:var(--bleu);color:#fff}
.btn.plein:hover{background:var(--bleu-fonce);border-color:var(--bleu-fonce)}

.verdict{display:flex;align-items:center;gap:22px;flex-wrap:wrap;padding:20px 26px;border-bottom:2px solid}
.verdict .rond{width:44px;height:44px;border-radius:50%;display:flex;align-items:center;
  justify-content:center;font-size:24px;font-weight:800;color:var(--panneau);flex:none}
.verdict .mot{font-size:29px;font-weight:800;letter-spacing:-.01em;line-height:1}
.verdict .sous{margin-top:5px;font-size:13.5px}
.verdict .puces{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap;
  font:600 11px "Red Hat Mono",monospace}
.verdict .puces span{padding:6px 11px;border-radius:20px;background:var(--surface);border:1px solid}
.v-a_verifier{background:var(--ambre-bande);border-bottom-color:var(--ambre)}
.v-a_verifier .rond{background:var(--ambre)}
.v-a_verifier .mot{color:var(--ambre-titre)} .v-a_verifier .sous{color:var(--ambre-texte)}
.v-fiable{background:var(--vert-voile);border-bottom-color:var(--vert)}
.v-fiable .rond{background:var(--vert)}
.v-fiable .mot{color:#2c5c36} .v-fiable .sous{color:#4a6b50}
.v-non_exploitable{background:var(--rouge-voile);border-bottom-color:var(--rouge)}
.v-non_exploitable .rond{background:var(--rouge)}
.v-non_exploitable .mot{color:#8c2f20} .v-non_exploitable .sous{color:var(--rouge-doux)}
.p-alerte{border-color:var(--ambre-filet)!important;color:var(--ambre-texte)}
.p-echec{border-color:var(--rouge-filet)!important;color:var(--rouge)}
.p-ok{border-color:var(--vert-filet)!important;color:var(--vert)}

.grille{display:grid;grid-template-columns:1fr 360px;gap:24px;padding:24px 26px 30px;align-items:start}
@media(max-width:1000px){.grille{grid-template-columns:1fr}}
.colonne{display:flex;flex-direction:column;gap:24px}
.rail{display:flex;flex-direction:column;gap:18px;position:sticky;top:16px}
@media(max-width:1000px){.rail{position:static}}
.legende{font:700 12px "Bricolage Grotesque",sans-serif;letter-spacing:.09em;
  text-transform:uppercase;color:var(--mut);margin-bottom:10px}

.champs{display:grid;grid-template-columns:1.6fr 1fr 1.2fr 1fr 1fr;gap:10px}
@media(max-width:900px){.champs{grid-template-columns:repeat(2,1fr)}}
.champ{background:var(--surface);border:1px solid var(--filet);border-radius:8px;padding:12px 14px}
.champ .lib{font-size:11px;color:var(--mut);margin-bottom:6px}
.champ .val{font:600 15px "Red Hat Mono",monospace;font-variant-numeric:tabular-nums;word-break:break-word}
.champ .pourquoi{font-size:10.5px;margin-top:4px;line-height:1.35}
.champ.illisible{background:var(--ambre-voile);border:1.5px dashed var(--ambre-tirets)}
.champ.illisible .lib,.champ.illisible .pourquoi{color:var(--ambre-texte)}
.champ.illisible .val{font-weight:700;color:var(--ambre)}
.champ.absent .val{color:var(--mut);font-weight:500}
.champ.absent .pourquoi{color:var(--mut)}
.champ.corrige{background:var(--bleu-voile);border:1.5px solid var(--bleu)}
.champ.corrige .lib,.champ.corrige .pourquoi{color:var(--bleu-fonce)}
.champ.corrige .val{color:var(--bleu-fonce)}

/* Mode correction. La saisie reprend la chasse fixe des valeurs : on remplace
   un chiffre par un chiffre, la ligne ne doit pas sauter en passant en edition. */
.saisie{width:100%;background:var(--surface);color:var(--encre);border:1.5px solid var(--bleu);
  border-radius:5px;padding:4px 7px;font:600 15px "Red Hat Mono",monospace;
  font-variant-numeric:tabular-nums}
.saisie:focus{outline:2px solid var(--bleu);outline-offset:1px}
.saisie::placeholder{font-weight:400;color:var(--mut)}
.tl .saisie{font-size:13px;font-weight:500}
.tl .saisie.n{text-align:right}
.bandeau-edition{padding:11px 26px;background:var(--bleu-voile);border-bottom:1px solid var(--bleu);
  font-size:13px;color:var(--bleu-fonce)}
.p-corr{border-color:var(--bleu)!important;color:var(--bleu)}
.corr{font-size:12.5px;padding:5px 0;border-bottom:1px solid var(--filet-doux)}
.corr:last-of-type{border-bottom:0}
.corr b{font:600 12px "Red Hat Mono",monospace;color:var(--bleu-fonce)}
.corr .fleche{font-family:"Red Hat Mono",monospace;color:var(--mut)}
.corr .apres{font:600 12.5px "Red Hat Mono",monospace}
.corr .avant{font:400 12.5px "Red Hat Mono",monospace;color:var(--mut);text-decoration:line-through}
/* Rien n'avait ete lu : barrer « vide » n'aurait aucun sens. */
.corr .avant.neant{text-decoration:none;font-style:italic}

/* Volet du document source. Il pousse le contenu au lieu de le recouvrir :
   comparer une valeur lue au papier suppose de voir les deux a la fois.
   Largeur calee a 560 px et pas davantage : au-dela, la visionneuse PDF de
   Chrome deplie d'elle-meme son volet de vignettes, qui mange la moitie de la
   place sans rien apporter sur un document d'une page. */
.volet{position:fixed;top:0;right:0;bottom:0;width:min(560px,46vw);z-index:20;
  display:flex;flex-direction:column;background:var(--panneau);
  border-left:1px solid var(--filet);box-shadow:-8px 0 24px rgba(0,0,0,.10)}
.volet[hidden]{display:none}
.volet .tete{display:flex;align-items:center;gap:12px;padding:12px 16px;
  border-bottom:1px solid var(--filet);font-weight:700;font-size:14px}
.volet .tete button{margin-left:auto}
.volet iframe{flex:1;width:100%;border:0;background:#3a352c}
body.avec-pdf main,body.avec-pdf footer{max-width:none;margin-right:min(560px,46vw)}
/* Volet ouvert : la place manque pour cinq colonnes, et un champ date tronque
   dans sa case est precisement ce qu'on demande a l'utilisateur de relire. */
body.avec-pdf .champs{grid-template-columns:repeat(3,1fr)}
body.avec-pdf .grille{grid-template-columns:1fr 300px;gap:16px;padding:20px}
@media(max-width:820px){
  .volet{width:100vw}
  body.avec-pdf main,body.avec-pdf footer{margin-right:0}
}

.tableau{background:var(--surface);border:1px solid var(--filet);border-radius:8px;overflow:hidden}
.tl{display:grid;grid-template-columns:1fr 62px 112px 122px;padding:9px 16px}
.tl.tete{font-size:11px;font-weight:700;color:var(--mut);background:var(--panneau);
  border-bottom:1px solid var(--filet)}
.tl.corps{font-size:13px;border-bottom:1px solid var(--filet-doux)}
.tl.corps:last-of-type{border-bottom:0}
.tl.edite{grid-template-columns:1fr 84px 124px 96px;gap:8px;align-items:center}
.tl .n{text-align:right;font:500 13px "Red Hat Mono",monospace;font-variant-numeric:tabular-nums}
.tl .n.fort{font-weight:600}
.tl .n.calc{color:var(--mut)}
.somme{display:flex;justify-content:flex-end;gap:18px;padding:10px 16px;
  border-top:1.5px solid var(--encre);background:var(--panneau);
  font:600 13px "Red Hat Mono",monospace;font-variant-numeric:tabular-nums}
.somme .etiq{color:var(--mut);font-weight:500}
.somme.discordante{background:var(--rouge-voile)}
.somme.discordante .valeur{color:var(--rouge)}
.note{margin-top:10px;font-size:12px;color:var(--mut);font-style:italic}
.vide{font-size:13px;color:var(--mut);font-style:italic}

.carte{background:var(--surface);border:1px solid var(--filet);border-radius:8px;padding:16px 18px}
.ctrl{display:flex;gap:10px;align-items:baseline;font-size:13px;padding:4px 0}
.ctrl .marque{font:700 13px "Red Hat Mono",monospace;flex:none}
.ctrl small{display:block;font-size:11.5px;line-height:1.35;color:var(--mut)}
.c-ok .marque{color:var(--vert)}
.c-echec{background:var(--rouge-voile);border-radius:6px;padding:8px 10px;margin:2px -10px}
.c-echec .marque{color:var(--rouge)} .c-echec b{color:var(--rouge)}
.c-echec small{color:var(--rouge-doux)}
.c-non_applicable{color:var(--mut)} .c-non_applicable .marque{color:var(--pointille)}

.av{border-radius:7px;padding:12px 14px;font-size:13px;line-height:1.45}
.av + .av{margin-top:10px}
.av .code{font:600 10.5px "Red Hat Mono",monospace;letter-spacing:.06em;
  text-transform:uppercase;display:block;margin-bottom:4px;opacity:.75}
.a-alerte{background:var(--ambre-voile);border:1px solid var(--ambre-filet)}
.a-bloquant{background:var(--rouge-voile);border:1px solid var(--rouge-filet)}
.a-info{background:var(--panneau);border:1px solid var(--filet);color:var(--doux)}

.jauge{margin-top:11px}
.jauge .lu{font:600 13px "Red Hat Mono",monospace}
.jauge .piste{position:relative;height:8px;background:var(--jauge);border-radius:4px;margin:11px 0 5px}
.jauge .rempli{position:absolute;left:0;top:0;bottom:0;background:var(--ambre-tirets);border-radius:4px 0 0 4px}
.jauge .seuil{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--encre)}
.jauge .grad{display:flex;justify-content:space-between;
  font:500 11px "Red Hat Mono",monospace;color:var(--ambre-texte)}
.jauge .grad .s{color:var(--encre)}

details{border-top:1px solid var(--filet);padding:14px 26px 20px}
summary{cursor:pointer;font:600 11px "Red Hat Mono",monospace;letter-spacing:.12em;
  text-transform:uppercase;color:var(--mut)}
summary:hover{color:var(--encre)}
pre{margin:12px 0 0;padding:16px;background:#241f18;color:#e8dfcb;border-radius:7px;overflow:auto;
  font-family:"Red Hat Mono",Consolas,monospace;font-size:11.5px;line-height:1.5}
.erreur{background:var(--rouge-voile);border:1px solid var(--rouge-filet);color:var(--rouge);
  border-radius:8px;padding:16px 18px;font-size:13.5px}
footer{max-width:1240px;margin:0 auto;padding:0 22px 36px;font-size:11.5px;color:var(--mut)}
</style></head><body>

<main>
  <div class="entete">
    <h1>Controle factures</h1>
    <p>Ce qui n&#39;a pas ete lu de facon sure est signale et laisse vide. Aucune valeur n&#39;est devinee.</p>
  </div>

  <label class="depot" id="depot">
    <strong>Deposer une facture PDF</strong>
    <span>ou cliquer pour choisir un fichier</span>
    <input type="file" id="fichier" accept="application/pdf">
  </label>
  <div class="exemples" id="exemples"></div>
  <div class="etat" id="etat"></div>
  <div id="res"></div>
</main>

<aside class="volet" id="volet" hidden>
  <div class="tete">Document source
    <button class="btn" id="fermer-pdf">Fermer</button></div>
  <iframe id="cadre-pdf" title="Facture d&#39;origine"></iframe>
</aside>

<footer>Extraction par l&#39;API Mistral. Verifications arithmetiques par le programme, sans modele.</footer>

<script>
const $ = s => document.querySelector(s);
const depot = $("#depot"), input = $("#fichier"), etat = $("#etat"), res = $("#res");
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const nb = v => v.toLocaleString("fr-FR",{minimumFractionDigits:2,maximumFractionDigits:2});
const eur = v => v == null ? null : nb(v) + " €";
const pc = v => v == null ? "n/a" : Math.round(v*100) + " %";
// Etat courant : le document analyse, son nom, l'URL locale du PDF depose
// (jamais renvoye au serveur, il y est deja passe une fois) et le mode.
let dernier = null, nomCourant = "", urlPdf = null, edition = false;

const volet = $("#volet"), cadrePdf = $("#cadre-pdf");
$("#fermer-pdf").onclick = () => montrerPdf(false);
function montrerPdf(ouvrir){
  volet.hidden = !ouvrir;
  document.body.classList.toggle("avec-pdf", ouvrir);
  if (ouvrir && cadrePdf.src !== urlPdf) cadrePdf.src = urlPdf || "";
}

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
  const ouvrirDepuisUrl = () => {
    const cible = decodeURIComponent(location.hash.slice(1));
    if (cible && l.includes(cible)) chargerExemple(cible);
  };
  ouvrirDepuisUrl();
  // Changer le fragment ne recharge pas la page : sans cet ecouteur, passer
  // d'une facture a l'autre par l'URL ne ferait rien du tout.
  addEventListener("hashchange", ouvrirDepuisUrl);
});

async function chargerExemple(n){
  etat.className = "etat charge"; etat.textContent = "Lecture de " + n;
  const blob = await (await fetch("/api/exemple/" + encodeURIComponent(n))).blob();
  envoyer(new File([blob], n, {type:"application/pdf"}));
}

async function envoyer(f){
  res.innerHTML = ""; etat.className = "etat charge"; etat.textContent = "Lecture de " + f.name;
  montrerPdf(false); cadrePdf.removeAttribute("src");
  if (urlPdf) URL.revokeObjectURL(urlPdf);
  urlPdf = URL.createObjectURL(f); nomCourant = f.name; edition = false;
  const fd = new FormData(); fd.append("fichier", f);
  try{
    const r = await fetch("/api/extraire",{method:"POST",body:fd,signal:AbortSignal.timeout(180000)});
    const d = await r.json();
    etat.className = "etat"; etat.textContent = "";
    if(!r.ok){ res.innerHTML = '<div class="erreur">' + esc(d.erreur) + '</div>'; return; }
    dernier = d; afficher(d);
  }catch(e){ etat.className="etat"; etat.textContent = "Erreur reseau : " + e.message; }
}

// Ce qui est envoye a /api/revalider : uniquement les champs presents a
// l'ecran. Un champ jamais affiche n'est pas transmis, donc pas ecrase.
function collecter(){
  const c = {};
  res.querySelectorAll("[data-champ]").forEach(i => { c[i.dataset.champ] = i.value; });
  const lignes = [];
  res.querySelectorAll("[data-ligne]").forEach(i => {
    const k = Number(i.dataset.ligne);
    lignes[k] = lignes[k] || {};
    lignes[k][i.dataset.col] = i.value;
  });
  if (lignes.length) c.lignes_produits = lignes;
  return c;
}

async function valider(){
  etat.className = "etat charge"; etat.textContent = "Application des corrections";
  try{
    const r = await fetch("/api/revalider",{method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({facture: dernier, corrections: collecter()})});
    const d = await r.json();
    etat.className = "etat"; etat.textContent = "";
    if(!r.ok){ etat.textContent = d.erreur || "Correction refusee."; return; }
    dernier = d; edition = false; afficher(d);
  }catch(e){ etat.className="etat"; etat.textContent = "Erreur reseau : " + e.message; }
}

function champ(nom, libelle, d){
  const e = d.meta.etats_champs[nom], v = d[nom];
  const aff = typeof v === "number" ? eur(v) : v;
  const alerte = (d.avertissements||[]).find(x => x.champ === nom && x.confiance != null);

  let corps, pourquoi = "";
  if (edition) {
    // La valeur part telle qu'affichee, separateurs francais compris : le
    // serveur sait relire « 1 040,00 ». Ce qui a ete lu puis ecarte devient
    // un indice de saisie, pas une valeur pre-remplie qu'on validerait par
    // inadvertance.
    const saisie = v == null ? "" : (typeof v === "number" ? nb(v) : String(v));
    const indice = alerte ? "lu « " + alerte.valeur_ecartee + " », ecarte"
                          : (e === "illisible" ? "non lu" : "absent du document");
    corps = '<input class="saisie" data-champ="' + nom + '" value="' + esc(saisie)
          + '" placeholder="' + esc(indice) + '" autocomplete="off">';
  } else {
    corps = '<div class="val">' + (v == null ? (e === "illisible" ? "non lu" : "—") : esc(aff)) + '</div>';
    if (e === "illisible") {
      pourquoi = '<div class="pourquoi">' + (alerte
        ? "confiance OCR " + Math.round(alerte.confiance*100) + " % &lt; seuil " + Math.round(alerte.seuil*100) + " %"
        : "illisible sur le document") + '</div>';
    } else if (e === "absent") {
      pourquoi = '<div class="pourquoi">absent du document</div>';
    } else if (e === "corrige") {
      pourquoi = '<div class="pourquoi">saisi a la main</div>';
    }
  }
  return '<div class="champ ' + e + '"><div class="lib">' + libelle + '</div>' + corps + pourquoi + '</div>';
}

function jauge(a){
  if(a.confiance == null || a.seuil == null) return "";
  const c = a.confiance*100, s = a.seuil*100;
  return '<div class="jauge">'
    + '<div>Lecture ecartee : <span class="lu">' + esc(a.valeur_ecartee ?? "") + '</span></div>'
    + '<div class="piste"><div class="rempli" style="width:' + c.toFixed(1) + '%"></div>'
    + '<div class="seuil" style="left:' + s.toFixed(1) + '%"></div></div>'
    + '<div class="grad"><span>confiance ' + c.toFixed(0) + ' %</span>'
    + '<span class="s">seuil ' + s.toFixed(0) + ' %</span></div></div>';
}

function afficher(d){
  const nom = nomCourant;
  const m = d.meta, st = m.statut_global;
  const corr = m.corrections || [];
  const fmt = v => v == null ? "vide" : (typeof v === "number" ? nb(v) : String(v));
  const mot = {fiable:"Exploitable", a_verifier:"À vérifier", non_exploitable:"Non exploitable"}[st] || st;
  const glyphe = {fiable:"✓", a_verifier:"!", non_exploitable:"✕"}[st] || "?";
  const echecs = m.controles.filter(c=>c.resultat === "echec").length;
  const ok = m.controles.filter(c=>c.resultat === "ok").length;
  const nonLus = Object.entries(m.etats_champs).filter(([,e])=>e === "illisible").map(([c])=>c);

  // Le resume doit couvrir TOUTES les causes du verdict, y compris un
  // avertissement bloquant qui ne vient d'aucun controle en echec : sans ca,
  // un document « non exploitable » pouvait s'annoncer comme coherent.
  const bloquants = d.avertissements.filter(a => a.gravite === "bloquant");
  const bouts = [];
  if (bloquants.length) bouts.push(bloquants.length + " point" + (bloquants.length>1?"s":"") + " bloquant" + (bloquants.length>1?"s":""));
  if (nonLus.length) bouts.push(nonLus.length + " champ" + (nonLus.length>1?"s":"") + " non lu" + (nonLus.length>1?"s":""));
  if (echecs) bouts.push(echecs + " controle" + (echecs>1?"s":"") + " en echec");
  const sous = (bouts.length
      ? bouts.join(" · ") + (st === "non_exploitable" ? "" : " — le reste est coherent")
      : "Tous les controles applicables sont coherents.")
    + (corr.length ? " " + corr.length + " valeur" + (corr.length>1?"s":"")
                     + " corrigee" + (corr.length>1?"s":"") + " a la main." : "");

  const puces = [];
  bloquants.forEach(a => puces.push('<span class="p-echec">' + esc(a.code.replace(/_/g," ")) + "</span>"));
  nonLus.forEach(c => puces.push('<span class="p-alerte">' + c.replace(/_/g," ").toUpperCase() + " NON LU</span>"));
  if (echecs) puces.push('<span class="p-echec">CONTROLE ' + echecs + "/" + m.controles.length + " EN ECHEC</span>");
  if (!puces.length) puces.push('<span class="p-ok">' + ok + "/" + m.controles.length + " CONTROLES OK</span>");
  if (corr.length) puces.push('<span class="p-corr">' + corr.length + " CORRIGEE" + (corr.length>1?"S":"") + "</span>");

  const chiffrees = d.lignes_produits.filter(l => l.total_ligne != null);
  const somme = chiffrees.length ? chiffrees.reduce((s,l)=>s+l.total_ligne, 0) : null;
  const discordante = somme != null && d.total_HT != null
                      && chiffrees.length === d.lignes_produits.length
                      && Math.abs(somme - d.total_HT) > 0.011;

  const cls = edition ? " edite" : "";
  const cellule = (i, col, valeur, droite) =>
    '<div' + (droite ? ' class="n"' : "") + '><input class="saisie' + (droite ? " n" : "")
    + '" data-ligne="' + i + '" data-col="' + col + '" value="' + esc(valeur) + '" autocomplete="off"></div>';

  const lignes = d.lignes_produits.length ? (
    '<div class="tableau">'
    + '<div class="tl tete' + cls + '"><div>Designation</div><div class="n">Qte</div><div class="n">PU HT</div><div class="n">Total</div></div>'
    + d.lignes_produits.map((l, i) => edition
        ? '<div class="tl corps' + cls + '">'
          + cellule(i, "designation", l.designation ?? "", false)
          + cellule(i, "quantite", l.quantite ?? "", true)
          + cellule(i, "prix_unitaire", l.prix_unitaire == null ? "" : nb(l.prix_unitaire), true)
          + '<div class="n calc">recalcule</div></div>'
        : '<div class="tl corps"><div>' + (l.designation == null ? '<span class="vide">non lu</span>' : esc(l.designation)) + '</div>'
          + '<div class="n">' + (l.quantite ?? "–") + '</div>'
          + '<div class="n">' + (l.prix_unitaire == null ? "–" : nb(l.prix_unitaire)) + '</div>'
          + '<div class="n fort calc">' + (l.total_ligne == null ? "–" : nb(l.total_ligne)) + '</div></div>').join("")
    // La somme affichee pendant l'edition serait celle d'avant correction :
    // une valeur perimee a cote de champs qu'on est en train de modifier
    // induirait en erreur, on l'enleve jusqu'a la validation.
    + (somme != null && !edition
        ? '<div class="somme' + (discordante ? " discordante" : "") + '"><div class="etiq">Somme des lignes'
          + (chiffrees.length < d.lignes_produits.length
             ? " (" + chiffrees.length + "/" + d.lignes_produits.length + " chiffrees)" : "")
          + '</div><div class="valeur">' + eur(somme) + '</div></div>'
        : "")
    + '</div><p class="note">' + (edition
        ? "Les totaux de ligne et la somme seront recalcules par le programme a la validation."
        : "La colonne Total et la somme sont calculees par le programme, elles ne sont pas lues sur le document.")
    + '</p>'
  ) : '<p class="vide">Aucune ligne n\'a pu etre extraite.</p>';

  res.innerHTML =
    '<div class="doc">'
  + '<div class="barre"><span class="titre">Controle factures</span>'
  + '<span class="puce-fichier">' + esc(nom) + " · lecture " + pc(m.confiance_ocr_moyenne)
  + " · analysee en " + (m.duree_ms/1000).toFixed(1).replace(".", ",") + ' s</span>'
  + '<span class="actions">' + (edition
      ? '<button class="btn" id="btn-annuler">Annuler</button>'
        + '<button class="btn plein" id="btn-valider">Valider les corrections</button>'
      : '<button class="btn" id="btn-pdf">Voir le PDF</button>'
        + '<button class="btn" id="btn-json">Telecharger le JSON</button>'
        + '<button class="btn plein" id="btn-corriger">Corriger et valider</button>')
  + '</span></div>'

  + (edition
      ? '<div class="bandeau-edition">Mode correction. Les valeurs sont modifiables, le document '
        + 'd\'origine est ouvert a droite pour comparaison. A la validation, les memes controles '
        + 'arithmetiques sont rejoues sur les valeurs corrigees, et chaque reprise est tracee dans le JSON.</div>'
      : "")

  + '<div class="verdict v-' + st + '"><div class="rond">' + glyphe + '</div>'
  + '<div><div class="mot">' + mot + '</div><div class="sous">' + sous + '</div></div>'
  + '<div class="puces">' + puces.join("") + '</div></div>'

  + '<div class="grille"><div class="colonne">'
  + '<div><div class="legende">Champs extraits</div><div class="champs">'
  + champ("nom_fournisseur","Fournisseur",d) + champ("date","Date",d)
  + champ("numero_facture","N° de facture",d) + champ("total_HT","Total HT",d)
  + champ("total_TTC","Total TTC",d) + '</div></div>'
  + '<div><div class="legende">Lignes de la facture</div>' + lignes + '</div>'
  + '</div>'

  + '<div class="rail">'
  + '<div class="carte"><div class="legende">Verifications arithmetiques · ' + ok + "/" + m.controles.length + '</div>'
  + m.controles.map(c => {
      const marque = {ok:"✓", echec:"✗", non_applicable:"–"}[c.resultat];
      return '<div class="ctrl c-' + c.resultat + '"><span class="marque">' + marque + '</span>'
        + '<div><b>' + esc(c.nom.replace(/_/g," ")) + '</b><small>' + esc(c.detail) + '</small></div></div>';
    }).join("")
  + '<p class="note">Faites par le programme, sans intervention d\'un modele.</p></div>'

  + '<div class="carte"><div class="legende">Avertissements · ' + d.avertissements.length + '</div>'
  + (d.avertissements.length
      ? d.avertissements.map(a => '<div class="av a-' + a.gravite + '">'
          + '<span class="code">' + esc(a.code) + (a.champ ? " → " + esc(a.champ) : "") + '</span>'
          + esc(a.message) + jauge(a) + '</div>').join("")
      : '<p class="vide">Aucun.</p>')
  + '</div>'

  + (corr.length
      ? '<div class="carte"><div class="legende">Corrections manuelles · ' + corr.length + '</div>'
        + corr.map(c => '<div class="corr"><b>' + esc(c.champ.replace(/_/g," ")) + '</b><br>'
            + '<span class="avant' + (c.valeur_lue == null ? " neant" : "") + '">'
            + esc(fmt(c.valeur_lue)) + '</span> '
            + '<span class="fleche">-&gt;</span> '
            + '<span class="apres">' + esc(fmt(c.valeur_retenue)) + '</span></div>').join("")
        + '<p class="note">Ces valeurs viennent d\'une saisie humaine, pas de la lecture '
        + 'automatique. Le JSON conserve les deux.</p></div>'
      : "")
  + '</div></div>'

  + '<details><summary>Donnees completes (JSON)</summary><pre>' + esc(JSON.stringify(d,null,2)) + '</pre></details>'
  + '</div>';

  if (edition) {
    $("#btn-annuler").onclick = () => { edition = false; afficher(dernier); };
    $("#btn-valider").onclick = valider;
    const premier = res.querySelector(".saisie");
    if (premier) premier.focus();
  } else {
    // Corriger sans le document sous les yeux n'aurait pas de sens : passer en
    // mode correction ouvre le PDF d'origine dans le meme geste.
    $("#btn-corriger").onclick = () => { edition = true; afficher(dernier); montrerPdf(true); };
    $("#btn-pdf").onclick = () => montrerPdf(volet.hidden);
    $("#btn-json").onclick = () => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(dernier,null,2)], {type:"application/json"}));
      a.download = nom.replace(/\.pdf$/i,"") + ".json"; a.click(); URL.revokeObjectURL(a.href);
    };
  }
}
</script></body></html>
"""
