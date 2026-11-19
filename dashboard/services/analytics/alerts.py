"""Alertes : météo (vent, rafales, vagues, visibilité) et file d'attente AIS.

Règle de conception contre la « fatigue d'alerte » (cours, bloc C) : peu de niveaux (vigilance / alerte), des seuils
affichés avec leur valeur, des fenêtres horaires regroupées (une alerte par épisode, pas une par heure) et un horizon
limité à 48 h. Les seuils sont dans constants.py et se règlent sans toucher au code des vues.
"""
from datetime import timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from django.utils import timezone

from ...constants import (GUST_ALERT_KN, GUST_WARN_KN, VISIBILITY_WARN_M, WAVE_ALERT_M, WAVE_WARN_M, WIND_ALERT_KN, WIND_WARN_KN)
from ...models import AisPosition, WeatherPoint
from ..fmt import nb

try:
    LOCAL = ZoneInfo("America/Los_Angeles")
except Exception:  # base de fuseaux absente : on reste en UTC plutôt que de planter
    LOCAL = timezone.utc

REGLES = [
    # (clé, champ, seuil vigilance, seuil alerte, unité, libellé)
    ("vent", "wind_kn", WIND_WARN_KN, WIND_ALERT_KN, "nœuds", "Vent moyen"),
    ("rafales", "gust_kn", GUST_WARN_KN, GUST_ALERT_KN, "nœuds", "Rafales"),
    ("vagues", "wave_m", WAVE_WARN_M, WAVE_ALERT_M, "m", "Vagues au large"),
]


def _heure(dt):
    return dt.astimezone(LOCAL).strftime("%d/%m %Hh")


def _fenetres(points, champ, seuil_vig, seuil_alerte, bas_est_mauvais=False):
    """Regroupe les heures consécutives au-dessus du seuil en épisodes."""
    episodes, cour = [], None
    for p in points:
        v = getattr(p, champ)
        niveau = 0
        if v is not None:
            if bas_est_mauvais:
                niveau = 1 if v <= seuil_vig else 0
            else:
                niveau = 2 if v >= seuil_alerte else 1 if v >= seuil_vig else 0
        if niveau:
            if cour is None:
                cour = {"debut": p.time, "fin": p.time, "pic": v, "pic_heure": p.time, "niveau": niveau}
            else:
                cour["fin"] = p.time
                cour["niveau"] = max(cour["niveau"], niveau)
                if (v < cour["pic"]) if bas_est_mauvais else (v > cour["pic"]):
                    cour["pic"], cour["pic_heure"] = v, p.time
        elif cour:
            episodes.append(cour)
            cour = None
    if cour:
        episodes.append(cour)
    return episodes


def alertes_meteo(horizon_h=48):
    maintenant = timezone.now()
    pts = list(WeatherPoint.objects.filter(is_current=False, time__gte=maintenant - timedelta(hours=1),
                                           time__lte=maintenant + timedelta(hours=horizon_h)).order_by("time"))
    courant = WeatherPoint.objects.filter(is_current=True).first()
    if not pts or not courant:
        return {"disponible": False, "niveau": "na", "alertes": [],
                "message": "Prévisions météo indisponibles : dernière source non récupérée. Les alertes météo sont suspendues."}
    alertes = []
    for cle, champ, vig, alerte, unite, nom in REGLES:
        for ep in _fenetres(pts, champ, vig, alerte):
            niveau = "alerte" if ep["niveau"] == 2 else "vigilance"
            seuil = alerte if niveau == "alerte" else vig
            alertes.append({
                "variable": cle, "niveau": niveau, "debut": ep["debut"].isoformat(), "fin": (ep["fin"] + timedelta(hours=1)).isoformat(),
                "pic": round(float(ep["pic"]), 1), "unite": unite, "seuil": seuil,
                "message": f"{nom} jusqu'à {nb(float(ep['pic']), 1)} {unite} entre {_heure(ep['debut'])} et {_heure(ep['fin'] + timedelta(hours=1))} "
                           f"(heure de Los Angeles) — seuil de {niveau} : {nb(seuil, 1 if seuil % 1 else 0)} {unite}."})
    for ep in _fenetres(pts, "visibility_m", VISIBILITY_WARN_M, VISIBILITY_WARN_M, bas_est_mauvais=True):
        alertes.append({"variable": "visibilite", "niveau": "vigilance", "debut": ep["debut"].isoformat(),
                        "fin": (ep["fin"] + timedelta(hours=1)).isoformat(), "pic": round(float(ep["pic"])), "unite": "m", "seuil": VISIBILITY_WARN_M,
                        "message": f"Visibilité réduite à {nb(float(ep['pic']))} m entre {_heure(ep['debut'])} et {_heure(ep['fin'] + timedelta(hours=1))} "
                                   f"(seuil : {nb(VISIBILITY_WARN_M)} m)."})
    alertes.sort(key=lambda a: (a["niveau"] != "alerte", a["debut"]))
    niveau = "alerte" if any(a["niveau"] == "alerte" for a in alertes) else "vigilance" if alertes else "ok"
    max_h = lambda champ: max((getattr(p, champ) for p in pts if getattr(p, champ) is not None), default=None)
    return {"disponible": True, "niveau": niveau, "alertes": alertes, "horizon_h": horizon_h,
            "max": {"vent": max_h("wind_kn"), "rafales": max_h("gust_kn"), "vagues": max_h("wave_m")},
            "courant": {"vent": courant.wind_kn, "rafales": courant.gust_kn, "vagues": courant.wave_m, "periode": courant.wave_period_s,
                        "direction": courant.wind_dir, "heure": courant.time.isoformat()},
            "maj": courant.fetched_at.isoformat()}


# ---------------------------------------------------------------------------------- AIS
def resume_ais(baseline_csv):
    """Compte les navires autour du port, en direct si possible, sinon dans l'archive (clairement signalée)."""
    maintenant = timezone.now()
    live = AisPosition.objects.filter(origin="live", seen_at__gte=maintenant - timedelta(minutes=30))
    if live.exists():
        origine, qs, instant = "live", live, maintenant
    else:
        archive = AisPosition.objects.filter(origin="archive")
        if not archive.exists():
            return {"disponible": False, "origine": None}
        fin = max(p.seen_at for p in archive)
        origine, qs, instant = "archive", archive.filter(seen_at__gte=fin - timedelta(minutes=60)), fin
    gros = [p for p in qs if p.type_group in ("Cargo (conteneurs, vrac)", "Pétrolier / chimiquier")]
    ancre = [p for p in gros if p.nav_status == 1]
    en_route = [p for p in qs if (p.sog or 0) >= 0.5]
    ref = {"navires_med": None}
    try:
        base = pd.read_csv(baseline_csv).set_index("heure")
        ligne = base.loc[instant.hour]
        ref = {k: float(ligne[k]) for k in ligne.index if k != "jours"}
        ref["jours"] = int(base["jours"].max())
    except (OSError, KeyError, ValueError):
        pass
    groupes = {}
    for p in qs:
        groupes[p.type_group or "Inconnu"] = groupes.get(p.type_group or "Inconnu", 0) + 1
    return {"disponible": True, "origine": origine, "instant": instant.isoformat(), "total": len(qs), "gros_navires": len(gros),
            "a_l_ancre": len(ancre), "en_mouvement": len(en_route), "par_type": dict(sorted(groupes.items(), key=lambda t: -t[1])),
            "reference": ref}


def alerte_file_attente(ais):
    """Vigilance si le nombre de gros navires à l'ancre dépasse nettement la référence horaire (direct uniquement)."""
    if not ais.get("disponible") or ais["origine"] != "live":
        return None
    ref = ais["reference"].get("ancre_p75")
    if ref is None:
        return None
    seuil = max(ref + 3, 5)
    if ais["a_l_ancre"] > seuil:
        return {"variable": "file_attente", "niveau": "vigilance", "pic": ais["a_l_ancre"], "unite": "navires", "seuil": seuil,
                "message": f"{ais['a_l_ancre']} gros navires à l'ancre (référence habituelle à cette heure : ≤ {ref:g}). File d'attente à surveiller."}
    return None
