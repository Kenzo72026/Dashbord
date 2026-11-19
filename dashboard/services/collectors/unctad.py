"""CNUCED (UNCTADstat) : escales, temps médian au port, débit de conteneurs et connectivité maritime.

Fichiers téléchargés (API publique de téléchargement en bloc d'UNCTADstat, sans clé) :
  US.PortCallsArrivals   nombre d'escales par pays et par type de navire (annuel, 2018-2023)
  US.PortCalls           temps médian au port en jours (annuel, 2018-2023)
  US.ContPortThroughput  débit de conteneurs en EVP par pays (annuel, jusqu'en 2024)
  US.PLSCI               indice de connectivité maritime de chaque port (trimestriel, jusqu'en 2026)
  US.LSCI                indice de connectivité maritime de chaque pays (trimestriel)

LIMITE IMPORTANTE : UNCTADstat ne publie pas Djibouti dans les séries d'escales et de temps médian (seulement 22
économies individuelles + des regroupements). Le tableau de bord l'écrit clairement ; pour Djibouti il utilise donc
le débit en EVP, la connectivité (PLSCI/LSCI) et, hors CNUCED, les escales du FMI PortWatch.
"""
import io

import pandas as pd

from ...constants import (UNCTAD_BULK, UNCTAD_COUNTRIES_CALLS, UNCTAD_COUNTRIES_TEU, UNCTAD_DATASETS,
                          UNCTAD_LSCI_ECONOMIES, UNCTAD_PLSCI_PORTS)
from ...models import UnctadValue
from ..registry import declare
from .common import PROCESSED, RAW, SourceUnavailable, http_get

CSV = PROCESSED / "unctad_long.csv"
REGION_PROXY = "Eastern Africa"  # regroupement qui contient Djibouti : sert d'indication, jamais présenté comme Djibouti


def _telecharger(code):
    import py7zr
    nom = code.replace(".", "_")
    contenu = http_get(UNCTAD_BULK.format(code=code, name=nom), timeout=120, binary=True)
    if contenu[:2] != b"7z":
        raise SourceUnavailable(f"{code} : le fichier reçu n'est pas une archive .7z")
    (RAW / f"{nom}.csv.7z").write_bytes(contenu)
    with py7zr.SevenZipFile(io.BytesIO(contenu)) as z:
        z.extract(path=RAW / "unctad", targets=[f"{nom}.csv"])
    return pd.read_csv(RAW / "unctad" / f"{nom}.csv", dtype=str, encoding="utf-8-sig")


def _long(df, serie, entite_col, label_col, periode_col, valeur_col, garder, marche=None):
    d = df
    if marche:
        d = d[d["CommercialMarket Label"] == marche]
    d = d[d[label_col].isin(garder)]
    out = pd.DataFrame({"series": serie, "entity": d[entite_col], "entity_label": d[label_col],
                        "period": d[periode_col].str.replace(r"Q0", "Q", regex=True),
                        "value": pd.to_numeric(d[valeur_col], errors="coerce")})
    return out.dropna(subset=["value"])


def fetch():
    data = {code: _telecharger(code) for code in UNCTAD_DATASETS}
    calls, temps = data["US.PortCallsArrivals"], data["US.PortCalls"]
    morceaux = []
    zones = UNCTAD_COUNTRIES_CALLS + [REGION_PROXY]
    for marche, suffixe in (("All ships", "all"), ("Container ships", "container")):
        morceaux.append(_long(calls, f"port_calls_{suffixe}", "Economy", "Economy Label", "Year", "Number of port calls", zones, marche))
        morceaux.append(_long(temps, f"median_time_{suffixe}", "Economy", "Economy Label", "Year", "Median time in port (days)", zones, marche))
    morceaux.append(_long(data["US.ContPortThroughput"], "teu_throughput", "Economy", "Economy Label", "Year",
                          "TEU (Twenty foot Equivalent Unit)", UNCTAD_COUNTRIES_TEU))
    pl = data["US.PLSCI"].copy()
    pl["Port Label"] = pl["Port"].map(UNCTAD_PLSCI_PORTS)
    morceaux.append(_long(pl, "plsci", "Port", "Port Label", "Quarter", "Index (average Q1 2023 = 100)", list(UNCTAD_PLSCI_PORTS.values())))
    morceaux.append(_long(data["US.LSCI"], "lsci", "Economy", "Economy Label", "Quarter", "Index (average Q1 2023 = 100)", UNCTAD_LSCI_ECONOMIES))
    long = pd.concat(morceaux, ignore_index=True)
    if long.empty:
        raise SourceUnavailable("aucune valeur UNCTADstat exploitable")
    long.to_csv(CSV, index=False)
    return long


def load():
    if not CSV.exists():
        raise SourceUnavailable("fichier data/processed/unctad_long.csv absent : lancer `python manage.py fetch_all`")
    df = pd.read_csv(CSV)
    UnctadValue.objects.all().delete()
    UnctadValue.objects.bulk_create([
        UnctadValue(series=r.series, entity=str(r.entity), entity_label=r.entity_label, period=str(r.period), value=float(r.value))
        for r in df.itertuples()
    ])
    djibouti_escales = df[(df.series.str.startswith(("port_calls", "median_time"))) & (df.entity_label == "Djibouti")]
    note = ("Djibouti est ABSENT des séries d'escales et de temps médian d'UNCTADstat (non publié) ; "
            "repère régional « Afrique de l'Est » affiché à titre indicatif." if djibouti_escales.empty else "")
    dernier = df[df.series == "plsci"].period.max()
    declare("unctad", "ok", f"{len(df)} valeurs chargées (escales/temps 2018-2023, débit jusqu'en {int(df[df.series == 'teu_throughput'].period.astype(int).max())}, "
            f"connectivité jusqu'à {dernier}).", rows=len(df), last_period=str(dernier), notes=note, retrieved=False,
            url="https://unctadstat.unctad.org/datacentre/")
    return len(df)


def refresh():
    try:
        fetch()
        declare("unctad", "ok", "téléchargement réussi", retrieved=True)
    except (SourceUnavailable, ImportError) as exc:
        declare("unctad", "error", f"Source injoignable ({exc}) : dernières données conservées.", retrieved=False)
    return load()
