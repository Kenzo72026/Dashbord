"""Container Port Performance Index (Banque mondiale / S&P Global) : score et rang des ports.

Trois sources officielles sont lues :
  * « The Container Port Performance Index 2025 » (juin 2026) : annexe EXCEL « CPPI 2020-2025 » (score de chaque port 2020…2025,
    rang 2025 publié). C'est l'édition la plus récente ; ses scores 2020-2024 sont identiques à ceux extraits du PDF 2020-2024.
  * « The Container Port Performance Index 2020 to 2024 » : annexe avec le score CPPI de chaque port pour 2020…2024
    et le rang 2024 publié. Les colonnes sont retrouvées par leurs coordonnées dans la page (les cases vides, pour
    les ports absents certaines années, ne décalent donc pas les valeurs).
  * « The Container Port Performance Index 2023 » : tableau A.1, classement global publié (405 ports).

Le CPPI est un SCORE (points d'indice, positif = temps au port plus court que la moyenne, négatif = plus long) calculé
à partir du temps passé par les navires au port. Ce n'est pas un volume : on ne le compare pas aux EVP.
"""
import re

import pandas as pd

from ...constants import CPPI_2023_NAMES, CPPI_2023_PDF, CPPI_2024_PDF, CPPI_2025_XLSX
from ...models import CppiRecord
from ..registry import declare
from .common import PROCESSED, RAW, SourceUnavailable, http_get

PDF_2024 = RAW / "cppi_2020_2024.pdf"
PDF_2023 = RAW / "cppi_2023.pdf"
XLSX_2025 = RAW / "cppi_2020_2025.xlsx"
CSV_2025 = PROCESSED / "cppi_annexe_2020_2025.csv"
CSV_ANNEXE = PROCESSED / "cppi_annexe_2020_2024.csv"
CSV_2023 = PROCESSED / "cppi_2023_rang_publie.csv"
EDITION_2025 = "CPPI 2020-2025 (rapport publié en 2026)"
EDITION_2024 = "CPPI 2020-2024 (rapport publié en 2025)"
EDITION_2023 = "CPPI 2023 (rapport publié en 2024)"

# centre x (en points PDF) de chaque colonne numérique de l'annexe
COLONNES = {"cppi_2020": 484, "cppi_2021": 521, "cppi_2022": 557, "cppi_2023": 591, "cppi_2024": 626,
            "rang_2024": 658, "heures_poste_pct": 686, "indice_stat_2024": 716, "indice_admin_2024": 746}
NUM = re.compile(r"^-?\d+(\.\d+)?%?$")
LOCODE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}$")  # code UN/LOCODE : 2 lettres de pays + 3 caractères (peut contenir un chiffre)


def _telecharger(url, chemin):
    if not chemin.exists():
        chemin.write_bytes(http_get(url, timeout=120, binary=True))
    if chemin.read_bytes()[:4] != b"%PDF":
        chemin.unlink()
        raise SourceUnavailable(f"{url} n'a pas renvoyé un PDF")


def parse_annexe_2024(pdf) -> pd.DataFrame:
    import fitz  # PyMuPDF
    doc = fitz.open(pdf)
    lignes = []
    for pno, page in enumerate(doc, 1):
        mots = page.get_text("words")
        if not any(m[4] == "LOCODE" for m in mots):
            continue
        ancres = sorted([m for m in mots if 100 <= m[0] <= 118 and LOCODE.match(m[4])], key=lambda m: m[1])
        for k, a in enumerate(ancres):
            y0 = a[1] - 2
            y1 = ancres[k + 1][1] - 2 if k + 1 < len(ancres) else a[1] + 40
            bande = [m for m in mots if y0 <= m[1] < y1 and m[1] > 140]
            nom = " ".join(m[4] for m in sorted([m for m in bande if m[0] < 105], key=lambda m: (round(m[1]), m[0])))
            pays = " ".join(m[4] for m in sorted([m for m in bande if 150 <= m[0] < 220], key=lambda m: (round(m[1]), m[0])))
            rec = {"port": nom.strip(), "locode": a[4], "pays": pays.strip(), **{c: None for c in COLONNES}}
            for m in bande:
                if m[0] >= 440 and NUM.match(m[4]) and m[1] < a[1] + 8:
                    centre = (m[0] + m[2]) / 2
                    col = min(COLONNES, key=lambda c: abs(COLONNES[c] - centre))
                    if abs(COLONNES[col] - centre) < 17:
                        rec[col] = float(m[4].rstrip("%"))
            lignes.append(rec)
    if len(lignes) < 300:
        raise SourceUnavailable(f"annexe CPPI illisible ({len(lignes)} ports trouvés, au moins 300 attendus)")
    return pd.DataFrame(lignes)


def parse_rang_2023(pdf) -> pd.DataFrame:
    import fitz
    doc = fitz.open(pdf)
    rangs = {}
    for pno in range(65, 71):  # tableau A.1 : classement global
        lignes = [x.strip() for x in doc[pno - 1].get_text().replace("−", "-").splitlines() if x.strip()]
        i = 0
        while i < len(lignes) - 1:
            nom, suivant = lignes[i], lignes[i + 1]
            if (re.fullmatch(r"\d{1,3}", suivant) and nom.upper() == nom and len(nom) > 2 and not nom.isdigit()
                    and not nom.startswith(("PORT NAME", "OVERALL", "RANKING", "TABLE", "SOURCE", "APPENDIX"))):
                rangs.setdefault(nom, int(suivant))
                i += 2
            else:
                i += 1
    df = pd.DataFrame(sorted(rangs.items(), key=lambda t: t[1]), columns=["port_majuscules", "rang_2023"])
    sel = df[df.port_majuscules.isin(CPPI_2023_NAMES)]
    if len(sel) < len(CPPI_2023_NAMES) - 1:
        raise SourceUnavailable("classement CPPI 2023 illisible : ports de comparaison introuvables")
    return df[(df.rang_2023 >= 1) & (df.rang_2023 <= 405)]


def parse_annexe_2025(xlsx) -> pd.DataFrame:
    """Annexe Excel de l'édition 2025 : colonnes retrouvées par leur intitulé (et non par leur position)."""
    d = pd.read_excel(xlsx)
    d.columns = [str(c).strip() for c in d.columns]
    def col(prefixe):
        trouve = [c for c in d.columns if c.lower().startswith(prefixe.lower())]
        if not trouve:
            raise SourceUnavailable(f"annexe CPPI 2025 : colonne « {prefixe} » introuvable (colonnes : {list(d.columns)[:20]})")
        return trouve[0]
    d = d[d[col("Port")].notna() & d[col("UN/LOCODE")].notna()]
    out = pd.DataFrame({"port": d[col("Port")].astype(str).str.strip().str.rstrip("*"), "locode": d[col("UN/LOCODE")], "pays": d[col("Territory")]})
    for a in range(2020, 2026):
        out[f"cppi_{a}"] = pd.to_numeric(d[col(f"CPPI {a}")], errors="coerce").round(1)
    out["rang_2025"] = pd.to_numeric(d[col("Rank 2025")], errors="coerce")
    out["indice_stat_2025"] = pd.to_numeric(d[col("Statistical Index")], errors="coerce").round(1)
    out["indice_admin_2025"] = pd.to_numeric(d[col("Administrative Index")], errors="coerce").round(1)
    if len(out) < 350 or out["rang_2025"].notna().sum() < 350:
        raise SourceUnavailable(f"annexe CPPI 2025 illisible ({len(out)} ports, {int(out['rang_2025'].notna().sum())} rangs)")
    return out


def _telecharger_xlsx(url, chemin):
    if not chemin.exists():
        chemin.write_bytes(http_get(url, timeout=120, binary=True))
    if chemin.read_bytes()[:2] != b"PK":
        chemin.unlink()
        raise SourceUnavailable(f"{url} n'a pas renvoyé un fichier Excel")


def fetch():
    _telecharger_xlsx(CPPI_2025_XLSX, XLSX_2025)
    parse_annexe_2025(XLSX_2025).to_csv(CSV_2025, index=False)
    _telecharger(CPPI_2024_PDF, PDF_2024)
    _telecharger(CPPI_2023_PDF, PDF_2023)
    parse_annexe_2024(PDF_2024).to_csv(CSV_ANNEXE, index=False)
    parse_rang_2023(PDF_2023).to_csv(CSV_2023, index=False)


def load():
    if not (CSV_ANNEXE.exists() and CSV_2023.exists() and CSV_2025.exists()):
        raise SourceUnavailable("CSV du CPPI absents : lancer `python manage.py fetch_all`")
    a25 = pd.read_csv(CSV_2025)
    a24 = pd.read_csv(CSV_ANNEXE)
    r23 = pd.read_csv(CSV_2023).set_index("port_majuscules").rang_2023.to_dict()
    CppiRecord.objects.all().delete()
    objets = []
    # édition 2025 : scores 2020-2025 (méthode homogène) et rang 2025 publié
    for row in a25.itertuples():
        for annee in range(2020, 2026):
            score = getattr(row, f"cppi_{annee}")
            if pd.isna(score):
                continue
            rang = int(row.rang_2025) if annee == 2025 and not pd.isna(row.rang_2025) else None
            objets.append(CppiRecord(port_name=row.port, locode=row.locode, country=row.pays if isinstance(row.pays, str) else "",
                                     year=annee, score=float(score), rank=rang, rank_kind="publie" if rang else "aucun", edition=EDITION_2025))
    # édition 2024 : rang 2024 publié
    for row in a24.itertuples():
        if not pd.isna(row.rang_2024) and not pd.isna(row.cppi_2024):
            objets.append(CppiRecord(port_name=row.port, locode=row.locode, country=row.pays if isinstance(row.pays, str) else "",
                                     year=2024, score=float(row.cppi_2024), rank=int(row.rang_2024), rank_kind="publie", edition=EDITION_2024))
    # édition 2023 : rang global publié, ports de comparaison seulement
    loc = a25.set_index("port").locode.to_dict()
    pays = a25.set_index("port").pays.to_dict()
    for maj, nom in CPPI_2023_NAMES.items():
        if maj in r23 and nom in loc:
            objets.append(CppiRecord(port_name=nom, locode=loc[nom], country=pays.get(nom, ""), year=2023, score=None,
                                     rank=int(r23[maj]), rank_kind="publie", edition=EDITION_2023))
    CppiRecord.objects.bulk_create(objets)
    n25 = int(a25.rang_2025.notna().sum())
    declare("cppi", "ok", f"{len(a25)} ports lus ; classements publiés : 2025 ({n25} ports), 2024 ({int(a24.rang_2024.notna().sum())}) et 2023.", rows=len(objets),
            last_period="2025", retrieved=False,
            notes="Score = points d'indice (temps au port, comparé à la moyenne de la classe de navires). Édition 2025 : annexe Excel officielle ; "
                  "ses scores 2020-2024 coïncident avec ceux extraits du PDF 2020-2024 (0 écart > 2 points sur plus de 300 ports). "
                  "Shanghai et Yangshan sont regroupés en 2025 (Yangshan n'a plus de score).")
    return len(objets)


def refresh():
    try:
        fetch()
        declare("cppi", "ok", "téléchargement réussi", retrieved=True)
    except (SourceUnavailable, ImportError) as exc:
        declare("cppi", "error", f"Source injoignable ou illisible ({exc}) : dernières données conservées.", retrieved=False)
    return load()
