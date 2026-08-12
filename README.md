# Extraction de factures fournisseurs

Extrait d'une facture PDF un JSON validé : fournisseur, date, numéro, lignes de
produits, total HT, total TTC. Ce qui n'a pas pu être lu de façon fiable revient
à `null` avec un avertissement explicite. **Aucune valeur n'est devinée.**

Traitements IA via l'**API Mistral** uniquement.

---

## Mise en route

```bash
git clone <url-du-repo> && cd juwa-facture-extract
python -m venv .venv && .venv\Scripts\activate      # Windows
# python3 -m venv .venv && source .venv/bin/activate  # macOS / Linux
pip install -r requirements.txt
cp .env.example .env        # puis renseigner MISTRAL_API_KEY
```

La clé se récupère sur [console.mistral.ai](https://console.mistral.ai) (le tier
gratuit suffit pour ce volume). Elle est lue depuis la variable d'environnement
`MISTRAL_API_KEY`, ou à défaut depuis le fichier `.env`, **qui est gitignoré et
n'est jamais commité**.

### En ligne de commande

```bash
python -m facture_extract tests/fixtures/facture_2_studio_botanica.pdf
```

```bash
python -m facture_extract tests/fixtures/*.pdf --json --out resultats/
```

`--json` imprime le document complet, `--out` écrit un fichier par facture.

### Interface web

```bash
python -m uvicorn facture_extract.web:app --port 8100
```

Puis `http://localhost:8100`. Dépôt par glisser-déposer, et des boutons chargent
directement les factures du jeu de test.

---

## Ce que fait le programme

```
PDF ──► OCR Mistral ──► extraction structurée ──► contrôles ──► JSON
        (perception)     (structuration)          (code pur)
```

**1. OCR** (`mistral-ocr-latest`). Le document devient du texte et des tableaux.
L'API renvoie au passage un score de confiance de lecture, qui est conservé.

**2. Extraction structurée** (`mistral-small-latest`). Le texte devient une
structure typée, contrainte par un schéma Pydantic transmis au modèle. Le modèle
n'a le droit de faire qu'une chose : reporter ce qu'il lit. Il ne calcule rien,
il ne corrige rien, il ne reformule rien.

**3. Contrôles déterministes** (`checks.py`). Aucun modèle n'intervient ici.
C'est le point où l'IA s'arrête.

**4. Document final.** Les six champs demandés sont à plat au premier niveau ;
tout ce qui relève de notre analyse est isolé dans `meta`.

### Les contrôles

| Contrôle | Ce qu'il vérifie |
|---|---|
| `somme_lignes_vs_total_ht` | La somme des lignes correspond-elle au total HT imprimé. En cas d'écart, **aucune des deux valeurs n'est corrigée**, les deux restent visibles |
| `taux_tva` | Le taux est **déduit** du rapport TTC/HT, jamais supposé, puis confronté aux taux français connus, historiques compris |
| `ttc_superieur_ht` | Cohérence élémentaire des deux totaux |
| `date_plausible` | Format, date non future, année vraisemblable |
| `lignes_positives` | Quantités strictement positives, prix non négatifs |
| `encodage_texte` | Détection des séquences de double encodage UTF-8 dans le texte source |

Le contrôle de TVA mérite un mot : le taux normal français est passé de 19,6 % à
20 % le 1er janvier 2014. Une facture de 2009 porte donc légitimement 19,6 %.
Coder 20 % en dur produirait un faux positif sur toutes les archives anciennes.

---

## Le schéma de données

Deux modèles distincts, parce que la frontière entre ce qui est lu et ce qui est
calculé doit rester visible dans le résultat.

`FactureLue` est ce que le modèle a le droit de renseigner. Tous ses champs sont
**requis mais nullables** : avec des valeurs par défaut, le schéma JSON les
marque comme facultatifs et le modèle prend le chemin le plus court en ne
renvoyant que le minimum. En les rendant requis, il doit se prononcer sur chacun,
quitte à répondre `null`.

`Facture` est le document final. Il ajoute un bloc `meta` qui porte les états de
champs, les contrôles exécutés, la confiance OCR et un statut global
(`fiable`, `a_verifier`, `non_exploitable`).

### Absent n'est pas illisible

Les deux valent `null`, mais ce ne sont pas la même chose : une facture de
prestation n'a légitimement pas de quantité, alors qu'un champ raturé est un
problème. L'énumération `EtatChamp` porte cette distinction que `null` seul ne
permet pas d'exprimer.

| État | Signification |
|---|---|
| `lu` | Valeur trouvée et jugée fiable |
| `illisible` | Le champ figure sur le document mais n'a pas pu être lu de façon sûre |
| `absent` | Le champ ne figure pas sur ce document |

---

## Jeu de test

⚠️ **Les PDF sources annoncés dans le sujet n'étaient pas dans l'archive fournie**,
qui ne contenait que quatre fichiers JSON, exemples de sortie attendue. Le jeu de
test a donc été **reconstruit à partir de ces sorties**, pour pouvoir valider le
pipeline en attendant les originaux.

```bash
python scripts/make_test_invoices.py                      # regénère les PDF
python scripts/degrade_scan.py <entrée.pdf> <sortie.pdf>  # fabrique un scan dégradé
```

### Vérification par rapport aux sorties attendues

```bash
python -m facture_extract tests/fixtures/*.pdf --out resultats/
python tests/comparer_reference.py --ref <dossier des JSON de référence>
```

Compare champ par champ, lignes comprises, avec une tolérance d'un centime.
Sur les quatre fichiers de référence fournis avec l'énoncé : **0 écart**.

Les JSON de référence ne sont pas versionnés ici : ils font partie de l'énoncé,
il ne m'appartient pas de les publier.

| Fixture | Difficulté couverte |
|---|---|
| `facture_1_meca_precision` | Cas nominal, TVA 20 %, tout cohérent |
| `facture_2_studio_botanica` | Somme des lignes 1 020 € contre total HT 1 040 €, **écart de 20 €** |
| `facture_3_scan_2009` | Facture de 2009, **TVA à 19,6 %** |
| `facture_3_scan_2009_degrade` | Version rasterisée sans couche texte : zéro caractère extractible sans OCR |
| `facture_4_hydrofluid_encodage` | Anomalie d'encodage du texte source |

---

## Limites connues

Elles sont annoncées ici plutôt que découvertes en production.

- **La dégradation du scan n'a pas mis l'OCR en difficulté.** Confiance moyenne
  de 98,2 % sur la version dégradée contre 98,0 % sur la version propre, tous
  les champs retrouvés. Le cas dégradé n'est donc **pas réellement éprouvé** :
  ma dégradation n'était pas assez sévère, et il faudrait de vrais scans anciens
  pour conclure.
- **Le seuil de confiance OCR (85 %) est posé, pas mesuré.** Il n'a jamais été
  franchi sur ce jeu de test, faute de document assez mauvais.
- **La confiance minimale par page n'est pas exploitable comme déclencheur** :
  elle descend à 0,19 sur des documents parfaitement propres. Seule la moyenne
  est utilisée.
- **Une seule facture par PDF.** Un PDF multi-factures serait traité comme un
  document unique et donnerait un résultat incohérent.
- **Devises non gérées.** Les montants sont supposés en euros ; aucun contrôle ne
  vérifie la devise imprimée.
- **L'écart de 20 € de `facture_2` provient du jeu d'exemples fourni**, dont le
  champ `avertissements` est pourtant vide. Signalé à JUWA le 12/08.

---

## Structure

```
facture_extract/
  schema.py       modèles Pydantic, la frontière lu / calculé
  mistral_io.py   tout ce qui parle à Mistral, et rien d'autre
  checks.py       contrôles déterministes, zéro IA
  pipeline.py     l'enchaînement complet, lisible de haut en bas
  cli.py          ligne de commande
  web.py          API et interface, une seule page sans étape de build
scripts/          génération du jeu de test
tests/fixtures/   factures PDF de test
```

Le fournisseur de modèles est isolé dans `mistral_io.py` : en changer revient à
réécrire ce seul fichier, sans toucher au schéma, aux contrôles, à la CLI ni à
l'interface.
