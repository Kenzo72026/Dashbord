"""Prépare les données de chaque page (JSON simple). Lecture de la base uniquement : aucun appel d'API externe."""
from datetime import timedelta

import numpy as np
import pandas as pd
from django.utils import timezone

from ..constants import (CPPI_PORTS, GUST_ALERT_KN, GUST_WARN_KN, NAV_STATUS, PORTWATCH_PORTS, UNCTAD_PLSCI_PORTS, VISIBILITY_WARN_M,
                         WAVE_ALERT_M, WAVE_WARN_M, WIND_ALERT_KN, WIND_WARN_KN, AIS_BBOX, MAP_CENTER, PORT_POINT, MARINE_POINT)
from ..models import AisPosition, CppiRecord, DataSource, UnctadValue, WeatherPoint
from .analytics.series import COMPOSANTES, complexe, escales_hebdo, tonnes_mensuelles, volumes_par_port

NOMS_PAYS = {"United States of America": "États-Unis", "United States": "États-Unis", "China": "Chine", "Singapore": "Singapour",
             "Netherlands (Kingdom of the)": "Pays-Bas", "Germany": "Allemagne", "Japan": "Japon", "Eastern Africa": "Afrique de l'Est (région)",
             "Djibouti": "Djibouti", "Egypt": "Égypte", "Saudi Arabia": "Arabie saoudite", "Kenya": "Kenya"}


def _liste(s):
    return [None if pd.isna(x) else float(x) for x in s]


# --------------------------------------------------------------------------------------------- volumes
def _pw_complexe(vol):
    """Tonnes de conteneurs du complexe Los Angeles-Long Beach (PortWatch) + comparaison avec les EVP de Los Angeles."""
    t = tonnes_mensuelles()
    if t is None or t.empty:
        return None
    out = {"mois": [x.strftime("%Y-%m") for x in t.index], "import_t": _liste(t.import_t), "export_t": _liste(t.export_t), "total_t": _liste(t.total_t),
           "yoy": _liste((t.total_t / t.total_t.shift(12) - 1) * 100)}
    base = t.total_t[t.index.year == 2019].mean()
    out["indice_tonnes"] = _liste(t.total_t / base * 100)
    if "LA" in vol:
        la = vol["LA"]["total_teu"].dropna()
        com = t.index.intersection(la.index)
        if len(com) >= 24:
            out["indice_la"] = _liste((la / la[la.index.year == 2019].mean() * 100).reindex(t.index))
            out["corr_total"] = float(t.total_t.loc[com].corr(la.loc[com]))
            li = vol["LA"]["loaded_imports"].loc[com]
            out["corr_import"] = float(t.import_t.loc[com].corr(li))
            out["tonnes_par_evp"] = float((t.import_t.loc[com] / li).median())
            out["n_mois_comparaison"] = int(len(com))
    return out


def volumes_payload():
    vol = volumes_par_port()
    ports = {}
    for p, df in vol.items():
        d = df.dropna(subset=["total_teu"])
        ports[p] = {"mois": [x.strftime("%Y-%m") for x in d.index], "total": _liste(d.total_teu),
                    **{c: _liste(d[c]) for c in COMPOSANTES}}
    df, scope, incl = complexe(vol)
    out = {"ports": ports, "perimetre": scope, "inclus": incl, "complexe": None, "heatmap": None, "annuel": [], "pw": None, "lb": None}
    out["pw"] = _pw_complexe(vol)
    from .analytics.insights import lire
    lb = lire("lb", {})
    out["lb"] = lb if lb.get("ok") else None
    if df is None:
        return out
    t = df.total_teu.dropna()
    yoy = (t / t.shift(12) - 1) * 100
    out["complexe"] = {"mois": [x.strftime("%Y-%m") for x in t.index], "total": _liste(t), "yoy": _liste(yoy),
                       **{c: _liste(df.loc[t.index, c]) for c in COMPOSANTES}}
    annees = sorted(set(t.index.year))
    z = [[None if (pd.Timestamp(a, m, 1) not in t.index) else float(t[pd.Timestamp(a, m, 1)]) for m in range(1, 13)] for a in annees]
    out["heatmap"] = {"annees": annees, "z": z}
    for a in annees:
        tt = t[t.index.year == a]
        out["annuel"].append({"annee": a, "total": float(tt.sum()), "mois": int(len(tt)),
                              "partiel": len(tt) < 12, "part_vides": float(df.loc[tt.index, "empty_exports"].sum() / df.loc[tt.index, "total_teu"].sum() * 100)})
    # comparaison honnête sur la même période pour l'année en cours (janvier → dernier mois)
    dernier = t.index[-1]
    cumul = {}
    for a in annees:
        sel = t[(t.index.year == a) & (t.index.month <= dernier.month)]
        cumul[a] = float(sel.sum()) if len(sel) == dernier.month else None
    out["cumul_meme_periode"] = {"jusqu_a": dernier.strftime("%m"), "valeurs": cumul}
    return out


# --------------------------------------------------------------------------------------------- monde
def monde_payload():
    out = {"cppi": [], "cppi_distribution": [], "cppi_n": 0, "calls": {}, "median": {}, "teu": {}, "plsci": {}, "portwatch": {}, "djibouti_note": None}
    # --- CPPI : scores 2020-2025 et rangs publiés de trois éditions (2023, 2024, 2025)
    from .collectors.cppi import EDITION_2023, EDITION_2024, EDITION_2025
    ed25 = CppiRecord.objects.filter(edition=EDITION_2025)
    r24 = {r.port_name: r.rank for r in CppiRecord.objects.filter(edition=EDITION_2024, year=2024)}
    r23 = {r.port_name: r.rank for r in CppiRecord.objects.filter(edition=EDITION_2023)}
    out["cppi_n"] = ed25.filter(year=2025, rank__isnull=False).count()
    out["cppi_distribution"] = [r.score for r in ed25.filter(year=2025) if r.score is not None]
    for nom, etiquette in CPPI_PORTS.items():
        rows = {r.year: r for r in ed25.filter(port_name=nom)}
        if not rows:
            continue
        out["cppi"].append({"port": nom, "etiquette": etiquette, "scores": {a: r.score for a, r in rows.items()},
                            "rang_2025": rows[2025].rank if 2025 in rows else None, "rang_2024": r24.get(nom), "rang_2023": r23.get(nom)})
    # --- CNUCED
    def serie(nom, entite_label):
        return {r.period: r.value for r in UnctadValue.objects.filter(series=nom, entity_label=entite_label)}
    pays_calls = sorted({r.entity_label for r in UnctadValue.objects.filter(series="port_calls_container")})
    for p in pays_calls:
        c, m = serie("port_calls_container", p), serie("median_time_container", p)
        if c:
            out["calls"][NOMS_PAYS.get(p, p)] = c
        if m:
            out["median"][NOMS_PAYS.get(p, p)] = m
    for p in sorted({r.entity_label for r in UnctadValue.objects.filter(series="teu_throughput")}):
        out["teu"][NOMS_PAYS.get(p, p)] = serie("teu_throughput", p)
    for p in UNCTAD_PLSCI_PORTS.values():
        s = serie("plsci", p)
        if s:
            out["plsci"][p] = dict(sorted(s.items())[-28:])
    out["djibouti_note"] = ("UNCTADstat ne publie pas Djibouti dans les séries « nombre d'escales » et « temps médian au port » (seulement 22 économies "
                            "individuelles). Pour Djibouti, la comparaison utilise le débit en EVP, la connectivité maritime (PLSCI) et, hors CNUCED, "
                            "les escales du FMI PortWatch.")
    # --- PortWatch : escales de porte-conteneurs par semaine (lissées sur 8 semaines), indice 100 = moyenne hebdomadaire de 2019
    for pid, nom in PORTWATCH_PORTS.items():
        s = escales_hebdo(pid, "container")
        if len(s) < 60:
            continue
        base = s[s.index.year == 2019].mean()
        lisse = s.rolling(8).mean()  # 8 semaines : Djibouti n'a qu'une douzaine d'escales par semaine, la courbe brute est trop nerveuse
        s2 = lisse.iloc[-156:]
        out["portwatch"][nom] = {"semaines": [d.strftime("%Y-%m-%d") for d in s2.index], "indice": _liste(s2 / base * 100),
                                 "moyenne_12_sem": float(s.iloc[-12:].mean()), "moyenne_2019": float(base),
                                 "variation_vs_2019_pct": float((s.iloc[-26:].mean() / base - 1) * 100)}
    return out


# --------------------------------------------------------------------------------------------- direct
def direct_payload():
    maintenant = timezone.now()
    live = AisPosition.objects.filter(origin="live", seen_at__gte=maintenant - timedelta(minutes=30))
    if live.exists():
        origine, qs = "live", list(live)
        instant = maintenant
    else:
        arch = list(AisPosition.objects.filter(origin="archive"))
        if arch:
            fin = max(p.seen_at for p in arch)
            origine, qs, instant = "archive", [p for p in arch if p.seen_at >= fin - timedelta(minutes=60)], fin
        else:
            origine, qs, instant = None, [], None
    navires = [{"mmsi": p.mmsi, "nom": p.name or "(sans nom)", "lat": p.lat, "lon": p.lon, "sog": p.sog, "cog": p.cog,
                "statut": NAV_STATUS.get(p.nav_status, "Non renseigné"), "type": p.type_group or "Inconnu", "longueur": p.length,
                "vu": p.seen_at.isoformat()} for p in qs]
    meteo = [{"t": w.time.isoformat(), "vent": w.wind_kn, "rafales": w.gust_kn, "vagues": w.wave_m, "visibilite": w.visibility_m}
             for w in WeatherPoint.objects.filter(is_current=False).order_by("time")]
    return {"ais": {"origine": origine, "instant": instant.isoformat() if instant else None, "navires": navires},
            "meteo": meteo, "seuils": {"vent": [WIND_WARN_KN, WIND_ALERT_KN], "rafales": [GUST_WARN_KN, GUST_ALERT_KN],
                                       "vagues": [WAVE_WARN_M, WAVE_ALERT_M], "visibilite": VISIBILITY_WARN_M},
            "carte": {"centre": MAP_CENTER, "bbox": AIS_BBOX, "port": PORT_POINT, "mer": MARINE_POINT,
                      "ports": [{"nom": "Port of Los Angeles", "lat": 33.738, "lon": -118.262}, {"nom": "Port of Long Beach", "lat": 33.754, "lon": -118.216}]}}


def sources_resume():
    srcs = list(DataSource.objects.order_by("kind", "key"))
    return srcs
