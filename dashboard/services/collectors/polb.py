"""Port of Long Beach : volumes mensuels en EVP.

Le site polb.com refuse l'accès (HTTP 403 le 18/11/2026 ; « Access Denied » aussi dans un navigateur ordinaire le 19/11/2026,
depuis le réseau de l'étudiant) : ce collecteur ne tente donc PAS de contourner ce blocage. Si le CSV mensuel de
https://polb.com/business/port-statistics/ (TEU mensuels depuis 1995) est obtenu par une voie légitime, il se place
dans data/raw/polb_teu_monthly.csv (ou .xlsx) puis lance : python manage.py import_polb

L'import reconnaît les colonnes par leur nom (sans dépendre de l'ordre exact), car la mise en forme du fichier du
port peut changer. En cas de doute, il refuse l'import et explique ce qui manque.
"""
import re
from datetime import date

import pandas as pd

from ...constants import SOURCES
from ...models import MonthlyVolume
from ..registry import declare
from .common import PROCESSED, RAW, SourceUnavailable

CSV_BRUT = RAW / "polb_teu_monthly.csv"
XLSX_BRUT = RAW / "polb_teu_monthly.xlsx"
CSV = PROCESSED / "polb_monthly_teu.csv"
MESSAGE_ABSENT = (
    "Données de Long Beach non importées : polb.com refuse l'accès (« Access Denied », erreur 403), aux téléchargements automatiques "
    "comme à certains navigateurs selon le réseau. Si le CSV mensuel (TEU) de la page « Port Statistics » est obtenu autrement "
    "(autre réseau, camarade, enseignante), le placer dans data/raw/polb_teu_monthly.csv puis lancer `python manage.py import_polb`. En attendant, la page Volumes affiche Long Beach observé jusqu'en août 2023 (BTS) puis estimé, et le complexe entier en tonnes (FMI PortWatch)."
)
MOIS_EN = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}


def _date_mois(valeur):
    """Accepte « JANUARY 2019 », « Jan 2019 », « 2019-01 », « 01/2019 » ou une vraie date."""
    if isinstance(valeur, (pd.Timestamp, date)):
        return date(valeur.year, valeur.month, 1)
    s = str(valeur).strip().lower()
    m = re.match(r"^([a-z]{3,9})\.?[\s\-/,]+(\d{4})$", s)
    if m:
        for nom, num in MOIS_EN.items():
            if nom.startswith(m.group(1)[:3]):
                return date(int(m.group(2)), num, 1)
    m = re.match(r"^(\d{4})[-/](\d{1,2})", s) or None
    if m:
        return date(int(m.group(1)), int(m.group(2)), 1)
    m = re.match(r"^(\d{1,2})[-/](\d{4})$", s)
    if m:
        return date(int(m.group(2)), int(m.group(1)), 1)
    return None


def _trouver(colonnes, *mots_requis, exclus=()):
    for c in colonnes:
        nom = str(c).lower()
        if all(m in nom for m in mots_requis) and not any(e in nom for e in exclus):
            return c
    return None


def parse_fichier(chemin) -> pd.DataFrame:
    """Lit le CSV/XLSX du port et renvoie year, month, loaded/empty imports/exports, total_teu (depuis 2019)."""
    brut = pd.read_excel(chemin) if str(chemin).lower().endswith("xlsx") else pd.read_csv(chemin)
    col = list(brut.columns)
    c_date = _trouver(col, "date") or _trouver(col, "month") or col[0]
    c_li = _trouver(col, "loaded", "inbound", exclus=("total",)) or _trouver(col, "loaded", "import", exclus=("total",))
    c_ei = _trouver(col, "empty", "inbound", exclus=("total",)) or _trouver(col, "empty", "import", exclus=("total",))
    c_le = _trouver(col, "loaded", "outbound", exclus=("total",)) or _trouver(col, "loaded", "export", exclus=("total",))
    c_ee = _trouver(col, "empty", "outbound", exclus=("total",)) or _trouver(col, "empty", "export", exclus=("total",))
    c_tot = _trouver(col, "total", exclus=("loaded", "empty", "in", "out")) or _trouver(col, "total teu") or _trouver(col, "total")
    manque = [n for n, c in [("chargés importés", c_li), ("vides importés", c_ei), ("chargés exportés", c_le),
                             ("vides exportés", c_ee)] if c is None]
    if manque:
        raise SourceUnavailable(f"colonnes introuvables dans le fichier de Long Beach : {', '.join(manque)} (colonnes lues : {col})")
    lignes = []
    for _, r in brut.iterrows():
        d = _date_mois(r[c_date])
        if d is None or d.year < 2019:
            continue
        v = {k: pd.to_numeric(str(r[c]).replace(",", ""), errors="coerce") for k, c in
             [("loaded_imports", c_li), ("empty_imports", c_ei), ("loaded_exports", c_le), ("empty_exports", c_ee)]}
        if any(pd.isna(x) for x in v.values()):
            continue
        total = pd.to_numeric(str(r[c_tot]).replace(",", ""), errors="coerce") if c_tot else float("nan")
        somme = float(sum(v.values()))
        if pd.notna(total) and abs(total - somme) > 0.01 * somme:
            raise SourceUnavailable(f"incohérence en {d:%Y-%m} : total publié {total:,.0f} ≠ somme des 4 colonnes {somme:,.0f}")
        lignes.append({"year": d.year, "month": d.month, **{k: float(x) for k, x in v.items()}, "total_teu": somme})
    if not lignes:
        raise SourceUnavailable("aucune ligne mensuelle depuis 2019 reconnue dans le fichier de Long Beach")
    return pd.DataFrame(lignes).sort_values(["year", "month"]).drop_duplicates(["year", "month"], keep="last")


def import_fichier():
    chemin = CSV_BRUT if CSV_BRUT.exists() else XLSX_BRUT if XLSX_BRUT.exists() else None
    if chemin is None:
        raise SourceUnavailable(MESSAGE_ABSENT)
    df = parse_fichier(chemin)
    df.to_csv(CSV, index=False)
    return df


def load():
    """CSV nettoyé → base. Sans fichier : source déclarée « indisponible » avec un message actionnable."""
    if not CSV.exists():
        declare("polb", "missing", MESSAGE_ABSENT, retrieved=False)
        MonthlyVolume.objects.filter(port="LB").delete()
        return 0
    df = pd.read_csv(CSV)
    MonthlyVolume.objects.filter(port="LB").delete()
    MonthlyVolume.objects.bulk_create([
        MonthlyVolume(port="LB", month=date(int(r.year), int(r.month), 1), loaded_imports=r.loaded_imports,
                      empty_imports=r.empty_imports, loaded_exports=r.loaded_exports, empty_exports=r.empty_exports,
                      total_teu=r.total_teu) for r in df.itertuples()
    ])
    d = df.iloc[-1]
    declare("polb", "ok", f"{len(df)} mois importés depuis le fichier téléchargé sur polb.com.", rows=len(df),
            last_period=f"{int(d.year)}-{int(d.month):02d}", url=SOURCES["polb"]["url"], retrieved=True)
    return len(df)
