"""Transforme un PDF texte en scan degrade, sans couche texte.

Le sujet annonce « 3 factures fournisseurs au format PDF (dont un scan de
qualite degradee) ». Les PDF sources n'etant pas fournis, ce script fabrique
ce cas de test a partir d'une facture texte : rasterisation, passage en niveaux
de gris, legere rotation, bruit, flou, contraste reduit et compression JPEG
agressive. Le PDF resultant ne contient qu'une image : aucune extraction de
texte n'est possible sans OCR, ce qui est precisement le cas a eprouver.

Usage : python scripts/degrade_scan.py <entree.pdf> <sortie.pdf>
"""
import random
import sys
from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image, ImageEnhance, ImageFilter

SEED = 20260812  # rend le jeu de test reproductible


def degrade(img: Image.Image, rng: random.Random) -> Image.Image:
    img = img.convert("L")                                    # scan monochrome
    img = img.rotate(rng.uniform(-0.7, 0.7), resample=Image.BICUBIC,
                     fillcolor=245, expand=False)             # feuille de travers
    img = ImageEnhance.Contrast(img).enhance(0.78)            # encre passee
    img = ImageEnhance.Brightness(img).enhance(1.06)          # papier jauni/lave
    img = img.filter(ImageFilter.GaussianBlur(radius=0.6))    # optique mediocre

    px = img.load()
    w, h = img.size
    for _ in range(int(w * h * 0.012)):                       # poussieres et grain
        x, y = rng.randrange(w), rng.randrange(h)
        px[x, y] = max(0, min(255, px[x, y] + rng.randint(-55, 55)))

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=38)                  # compression agressive
    return Image.open(BytesIO(buf.getvalue()))


def main(src: Path, dst: Path) -> None:
    rng = random.Random(SEED)
    doc = pymupdf.open(src)
    out = pymupdf.open()
    for page in doc:
        pix = page.get_pixmap(dpi=150)                        # scan de bureau typique
        img = degrade(Image.frombytes("RGB", (pix.width, pix.height), pix.samples), rng)
        buf = BytesIO()
        img.convert("L").save(buf, format="JPEG", quality=38)
        new = out.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, stream=buf.getvalue())     # image seule, zero texte
    out.save(dst, deflate=True)
    out.close()
    doc.close()

    check = pymupdf.open(dst)
    residual = "".join(p.get_text() for p in check).strip()
    check.close()
    print(f"  {dst.name}  ({dst.stat().st_size // 1024} Ko)  "
          f"texte extractible sans OCR : {len(residual)} caracteres")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
