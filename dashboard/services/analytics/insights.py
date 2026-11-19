"""Orchestration : calcule les analyses et les range en base (modèle Insight).

  compute_all()  : recalcul complet (prévision, anomalies) puis partie « direct » ; à lancer après un téléchargement.
  compute_live() : alertes météo, résumé AIS, indicateurs et recommandations ; rapide, appelé à chaque actualisation du direct.
"""
import math

import pandas as pd
from django.utils import timezone

from ...models import CppiRecord, DataSource, Insight
from ..collectors.ais import BASELINE_CSV
from . import alerts, anomalies, forecast, kpi, lb_estimate, recommend
from .series import complexe, escales_hebdo, tonnes_mensuelles, volumes_par_port


def _propre(o):
    """Rend l'objet sérialisable en JSON : NaN/inf → None, types numpy → types Python."""
    if isinstance(o, dict):
        return {k: _propre(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_propre(v) for v in o]
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if hasattr(o, "item"):
        return _propre(o.item())
    return o


def _sauver(cle, valeur):
    Insight.objects.update_or_create(key=cle, defaults={"payload": _propre(valeur), "computed_at": timezone.now()})


def lire(cle, defaut=None):
    i = Insight.objects.filter(key=cle).first()
    return i.payload if i else defaut


def _structure(df):
    d = df.dropna().iloc[-1]
    tot_imp, tot_exp = d.loaded_imports + d.empty_imports, d.loaded_exports + d.empty_exports
    return {"mois": df.dropna().index[-1].strftime("%Y-%m"), "part_vides_exports": float(d.empty_exports / tot_exp * 100),
            "part_exports_charges": float(d.loaded_exports / d.total_teu * 100), "part_imports_charges": float(d.loaded_imports / d.total_teu * 100),
            "exports_total": float(tot_exp), "imports_total": float(tot_imp)}


def contexte_cppi():
    from ..collectors.cppi import EDITION_2024, EDITION_2025
    g = lambda nom, an, ed=EDITION_2025: CppiRecord.objects.filter(port_name=nom, year=an, edition=ed).first()
    la, lb, dj = g("Los Angeles", 2025), g("Long Beach", 2025), g("Djibouti", 2025)
    if not (la and lb and la.rank and lb.rank):
        return []
    n = CppiRecord.objects.filter(year=2025, edition=EDITION_2025, rank__isnull=False).count()
    la24, lb24 = g("Los Angeles", 2024, EDITION_2024), g("Long Beach", 2024, EDITION_2024)
    out = [f"Rang CPPI 2025 : Long Beach {lb.rank}ᵉ et Los Angeles {la.rank}ᵉ sur {n} ports" + (f", Djibouti {dj.rank}ᵉ." if dj and dj.rank else ".")]
    if la24 and lb24:
        out.append(f"En un an : Los Angeles {la24.rank}ᵉ → {la.rank}ᵉ (score {la24.score:+.0f} → {la.score:+.0f}), Long Beach {lb24.rank}ᵉ → {lb.rank}ᵉ "
                   f"({lb24.score:+.0f} → {lb.score:+.0f}) ; 0 = temps moyen au port.".replace("-", "−"))
    if dj and dj.rank:
        s = lambda an: (g("Djibouti", an).score if g("Djibouti", an) else None)
        out.append(f"Djibouti : {s(2022):+.0f} en 2022, {s(2023):+.0f} en 2023, {s(2024):+.0f} en 2024, {s(2025):+.0f} en 2025.".replace("-", "−"))
    if la24 and lb24 and abs(la.rank - lb.rank) > 100:
        out.append(f"Les deux ports du complexe sont très éloignés (écart de {abs(la.rank - lb.rank)} places en 2025 contre {abs(la24.rank - lb24.rank)} en 2024) : "
                   "chercher la cause (terminaux, mouillage, mix de navires) avant d'agir.")
    return [x for x in out if x]


def calculer_lb():
    """Long Beach observé (BTS) puis estimé (tonnes PortWatch) ; {'ok': False, 'raison': …} si une entrée manque."""
    import pandas as pd
    from ..collectors.bts import CSV as CSV_BTS
    if not CSV_BTS.exists():
        return {"ok": False, "raison": "série BTS de Long Beach absente"}
    df = pd.read_csv(CSV_BTS)
    lb = pd.Series(df.total_teu.values, index=pd.to_datetime(df.mois + "-01"))
    vol = volumes_par_port()
    t = tonnes_mensuelles()
    if "LA" not in vol or t is None or t.empty:
        return {"ok": False, "raison": "volumes de Los Angeles ou tonnes PortWatch absents"}
    return lb_estimate.estimer(lb, vol["LA"].total_teu.dropna(), t.total_t)


def compute_all():
    vol = volumes_par_port()
    df, scope, ports = complexe(vol)
    prev = forecast.prevoir(df["total_teu"]) if df is not None else {"ok": False, "raison": "aucune donnée de volumes"}
    anom_m = anomalies.anomalies_mensuelles(df) if df is not None else {"ok": False, "raison": "aucune donnée de volumes"}
    if anom_m.get("ok"):
        anom_m["structure"] = _structure(df)
    anom_h = anomalies.anomalies_hebdo(escales_hebdo())
    _sauver("meta", {"perimetre": scope, "ports": ports, "dernier_mois": df.dropna().index[-1].strftime("%Y-%m") if df is not None else None})
    _sauver("forecast", prev)
    _sauver("anom_m", anom_m)
    _sauver("anom_h", anom_h)
    _sauver("lb", calculer_lb())
    compute_live()


def compute_live():
    meta = lire("meta", {})
    prev, anom_m, anom_h = lire("forecast"), lire("anom_m"), lire("anom_h")
    meteo = alerts.alertes_meteo()
    ais = alerts.resume_ais(BASELINE_CSV)
    file_attente = alerts.alerte_file_attente(ais)
    tuiles = kpi.toutes_les_tuiles(prev, anom_h, meteo, ais)
    polb_ok = "LB" in (meta.get("ports") or [])
    recs = recommender = recommend.recommander(prev, anom_m, anom_h, meteo, ais, file_attente, contexte_cppi(), polb_ok,
                                               meta.get("perimetre", "inconnu"))
    # synthèse = situation OPÉRATIONNELLE (météo, activité, file d'attente) ; le classement CPPI est structurel et reste hors du bandeau
    operationnelles = [t for t in tuiles if t["id"] in ("volumes", "escales", "ais", "vent", "vagues")]
    niveau = "alerte" if any(t["statut"] == "alert" for t in operationnelles) or meteo.get("niveau") == "alerte" else \
        "vigilance" if any(t["statut"] == "warn" for t in operationnelles) or meteo.get("niveau") in ("vigilance",) or file_attente else "ok"
    _sauver("meteo", meteo)
    _sauver("ais", ais)
    _sauver("file_attente", file_attente or {})
    _sauver("kpis", tuiles)
    _sauver("recs", recs)
    _sauver("synthese", {"niveau": niveau, "calcule": timezone.now().isoformat()})
