"""Vues : elles lisent la base (jamais les API externes). Seule l'action « Actualiser » peut rappeler la météo,
et seulement si les données ont dépassé leur durée de validité."""
from datetime import timedelta

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import DataSource
from .services import registry, viewdata
from .services.analytics.insights import compute_live, lire
from .services.collectors import ais as ais_collector
from .services.collectors import weather as weather_collector
from .services.fmt import mois_fr, nb, signe_pct

PAGES = [("accueil", "Vue d'ensemble", "M3 12l9-9 9 9M5 10v10h5v-6h4v6h5V10"),
         ("volumes", "Volumes LA · LB", "M3 20h18M6 20V10m6 10V4m6 16v-7"),
         ("monde", "Comparaison mondiale", "M12 3a9 9 0 100 18 9 9 0 000-18zM3 12h18M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"),
         ("direct", "En direct", "M12 12m-2 0a2 2 0 104 0 2 2 0 10-4 0M7.8 7.8a6 6 0 000 8.4M16.2 7.8a6 6 0 010 8.4M4.9 4.9a10 10 0 000 14.2M19.1 4.9a10 10 0 010 14.2"),
         ("decision", "Aide à la décision", "M9 11l3 3L22 4M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"),
         ("sources", "Sources & méthode", "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"),
         ("fiche", "Fiche de conception", "M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8zM14 3v5h5M9 13h6M9 17h6")]


ROSE = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]


def _rose(deg):
    """Direction en degrés → rose des vents à 16 points, en français."""
    return ROSE[int(((float(deg) % 360) + 11.25) // 22.5) % 16]


def _vent():
    """Vent actuel pour la boussole de la barre latérale (None si la météo est indisponible)."""
    m = lire("meteo", {})
    c = m.get("courant") if m.get("disponible") else None
    if not c or c.get("vent") is None or c.get("direction") is None:
        return None
    return {"kn": c["vent"], "rafales": c.get("rafales"), "dir": c["direction"], "rose": _rose(c["direction"])}


def _ticker():
    """Bulletin défilant : un repère par indicateur (titre court, valeur, état)."""
    return [{"titre": k["titre"].split(" · ")[0], "valeur": k["valeur"], "unite": k["unite"], "statut": k["statut"]}
            for k in lire("kpis", []) if k.get("statut") != "na"]


def _ctx(page, **extra):
    synth = lire("synthese", {"niveau": "na"})
    meta = lire("meta", {})
    sources = list(DataSource.objects.all())
    ko = [s for s in sources if s.status in ("error", "missing")]
    # chaque bannière « source indisponible » n'apparaît que là où elle compte (évite la fatigue d'alerte)
    visibles = {"polb": ("accueil", "volumes", "sources"), "ais_live": ("accueil", "direct", "sources"), "ais_archive": ("direct", "sources")}
    bannieres = [s for s in ko if page in visibles.get(s.key, (page,))]
    registry.mark_stale_live("ais_live", settings.AIS_STALE_SECONDS)
    registry.mark_stale_live("weather", settings.WEATHER_TTL_SECONDS * 4)
    return {"page": page, "pages": PAGES, "synthese": synth, "meta": meta, "sources": sources, "sources_ko": ko, "bannieres": bannieres,
            "maintenant": timezone.now(), "perimetre": meta.get("perimetre", ""), "vent": _vent(), "ticker": _ticker(), **extra}


def accueil(request):
    kpis = lire("kpis", [])
    recs = lire("recs", [])
    meteo = lire("meteo", {})
    prev = lire("forecast", {})
    meta = lire("meta", {})
    # phrase d'accroche calculée à partir des chiffres (aucun texte écrit à la main sur des valeurs)
    t = {k["id"]: k for k in kpis}
    phrases = []
    if "volumes" in t and t["volumes"]["statut"] != "na":
        phrases.append(f"{mois_fr(meta.get('dernier_mois', '2000-01'))} : {t['volumes']['valeur']} EVP ({t['volumes']['tendance']}).")
    if prev.get("ok"):
        p = prev["prevision"][0]
        phrases.append(f"Prévision {mois_fr(p['mois'])} : {nb(p['valeur'])} EVP, entre {nb(p['bas'])} et {nb(p['haut'])}.")
    if meteo.get("disponible") and meteo["alertes"]:
        phrases.append(meteo["alertes"][0]["message"])
    elif meteo.get("disponible"):
        phrases.append("Aucun épisode de vent ou de vagues au-dessus des seuils dans les 48 prochaines heures.")
    a_surveiller = [k["titre"] for k in kpis if k["id"] in ("volumes", "escales", "ais", "vent", "vagues") and k["statut"] in ("warn", "alert")]
    return render(request, "dashboard/accueil.html", _ctx("accueil", kpis=kpis, recs=recs[:3], nb_recs=len(recs), meteo=meteo, a_surveiller=a_surveiller,
                                                          phrases=phrases, forecast=prev, anom_m=lire("anom_m", {}), meta=meta))


def volumes(request):
    return render(request, "dashboard/volumes.html", _ctx("volumes", donnees=viewdata.volumes_payload(), forecast=lire("forecast", {}),
                                                          anom=lire("anom_m", {}), anom_h=lire("anom_h", {})))


def monde(request):
    return render(request, "dashboard/monde.html", _ctx("monde", donnees=viewdata.monde_payload()))


def direct(request):
    return render(request, "dashboard/direct.html", _ctx("direct", donnees=viewdata.direct_payload(), meteo=lire("meteo", {}), ais=lire("ais", {}),
                                                         file_attente=lire("file_attente", {}),
                                                         cle_ais=bool(settings.AISSTREAM_API_KEY)))


def decision(request):
    return render(request, "dashboard/decision.html", _ctx("decision", recs=lire("recs", []), forecast=lire("forecast", {}), anom_m=lire("anom_m", {}),
                                                           anom_h=lire("anom_h", {}), meteo=lire("meteo", {}), kpis=lire("kpis", [])))


def sources(request):
    return render(request, "dashboard/sources.html", _ctx("sources", liste=viewdata.sources_resume()))


def fiche(request):
    return render(request, "dashboard/fiche.html", _ctx("fiche", kpis=lire("kpis", [])))


# --------------------------------------------------------------------------------------- API JSON (lecture de la base)
def api_live(request):
    d = viewdata.direct_payload()
    s = {x.key: {"statut": x.status, "message": x.message, "recupere": x.retrieved_at.isoformat() if x.retrieved_at else None}
         for x in DataSource.objects.filter(key__in=["weather", "ais_live", "ais_archive"])}
    return JsonResponse({"direct": d, "meteo": lire("meteo", {}), "ais": lire("ais", {}), "kpis": lire("kpis", []), "recs": lire("recs", []),
                         "sources": s, "synthese": lire("synthese", {})})


@require_POST
def api_refresh(request):
    """Actualise la météo seulement si elle a dépassé sa durée de validité (ou depuis plus d'une minute si forcé).

    Évite de rappeler l'API à chaque clic. Le flux AIS, lui, est alimenté par la commande `collect_ais` (processus séparé).
    """
    age = registry.age_seconds("weather")
    force = request.POST.get("force") == "1" and (age is None or age > 60)
    weather_collector.refresh(force=force)
    compute_live()
    nouvel_age = registry.age_seconds("weather")
    return JsonResponse({"ok": True, "force": force, "age_meteo_s": nouvel_age, "ttl_s": settings.WEATHER_TTL_SECONDS,
                         "message": "Météo rafraîchie." if force or (age is None or age > settings.WEATHER_TTL_SECONDS)
                         else f"Données encore valables (récupérées il y a {int(age)} s) : aucun appel externe."})
