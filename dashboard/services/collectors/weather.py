"""Météo du port (Open-Meteo, sans clé) : vent, rafales, visibilité, vagues ; état actuel + prévision 72 h.

Les vues ne rappellent jamais l'API : elles lisent les points stockés. Un nouvel appel n'a lieu que si les données ont
plus de WEATHER_TTL_SECONDS (15 minutes par défaut) ou si l'utilisateur force l'actualisation.
"""
import json
from datetime import datetime, timezone as tz

from django.conf import settings
from django.utils import timezone

from ...constants import MARINE_POINT, OPEN_METEO_FORECAST, OPEN_METEO_MARINE, PORT_POINT
from ...models import WeatherPoint
from ..registry import declare, is_fresh
from .common import SourceUnavailable, http_get


def _horaire(rep, champs):
    h = rep.get("hourly") or {}
    return {t: {c: (h.get(c) or [None] * len(h["time"]))[i] for c in champs} for i, t in enumerate(h.get("time", []))}


def _instant(texte):
    return datetime.fromisoformat(texte).replace(tzinfo=tz.utc)


def fetch():
    vent = json.loads(http_get(OPEN_METEO_FORECAST, params={
        "latitude": PORT_POINT[0], "longitude": PORT_POINT[1], "wind_speed_unit": "kn", "timezone": "UTC",
        "past_days": 1, "forecast_days": 3,
        "current": "wind_speed_10m,wind_gusts_10m,wind_direction_10m",
        "hourly": "wind_speed_10m,wind_gusts_10m,wind_direction_10m,visibility"}, timeout=30))
    mer = json.loads(http_get(OPEN_METEO_MARINE, params={
        "latitude": MARINE_POINT[0], "longitude": MARINE_POINT[1], "timezone": "UTC", "past_days": 1, "forecast_days": 3,
        "current": "wave_height,wave_period,wave_direction,swell_wave_height",
        "hourly": "wave_height,wave_period,wave_direction,swell_wave_height"}, timeout=30))
    if "hourly" not in vent:
        raise SourceUnavailable("réponse Open-Meteo sans prévision horaire")
    return vent, mer


def refresh(force=False):
    """Retourne le nombre de points stockés. Respecte le TTL sauf si force=True."""
    if not force and is_fresh("weather", settings.WEATHER_TTL_SECONDS):
        return WeatherPoint.objects.count()
    try:
        vent, mer = fetch()
    except (SourceUnavailable, ValueError) as exc:
        declare("weather", "error", f"Open-Meteo injoignable ({exc}) : dernières prévisions conservées.", retrieved=False)
        return WeatherPoint.objects.count()
    maintenant = timezone.now()
    hv = _horaire(vent, ["wind_speed_10m", "wind_gusts_10m", "wind_direction_10m", "visibility"])
    hm = _horaire(mer, ["wave_height", "wave_period", "wave_direction", "swell_wave_height"]) if "hourly" in mer else {}
    points = []
    for t, v in hv.items():
        m = hm.get(t, {})
        points.append(WeatherPoint(time=_instant(t), is_current=False, wind_kn=v["wind_speed_10m"], gust_kn=v["wind_gusts_10m"],
                                   wind_dir=v["wind_direction_10m"], visibility_m=v["visibility"], wave_m=m.get("wave_height"),
                                   wave_period_s=m.get("wave_period"), wave_dir=m.get("wave_direction"),
                                   swell_m=m.get("swell_wave_height"), fetched_at=maintenant))
    cv, cm = vent.get("current", {}), mer.get("current", {})
    courant = WeatherPoint(time=_instant(cv["time"]), is_current=True, wind_kn=cv.get("wind_speed_10m"), gust_kn=cv.get("wind_gusts_10m"),
                           wind_dir=cv.get("wind_direction_10m"), wave_m=cm.get("wave_height"), wave_period_s=cm.get("wave_period"),
                           wave_dir=cm.get("wave_direction"), swell_m=cm.get("swell_wave_height"), fetched_at=maintenant)
    WeatherPoint.objects.all().delete()
    WeatherPoint.objects.bulk_create(points + [courant])
    declare("weather", "ok", f"{len(points)} heures (24 h passées + 72 h de prévision), vent {PORT_POINT}, vagues {MARINE_POINT}.",
            rows=len(points) + 1, last_period=cv["time"], retrieved=True,
            notes="Modèles de prévision globaux (grille ~ 11 km pour le vent, ~ 5 km pour les vagues) : indicatif, pas une mesure "
                  "au quai. Vagues calculées au large de la jetée, pas dans le bassin abrité.")
    return len(points) + 1
