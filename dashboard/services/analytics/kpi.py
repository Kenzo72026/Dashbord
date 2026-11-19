"""Tuiles d'indicateurs. Règle du cours : chaque tuile porte quatre éléments, jamais un chiffre seul.

  1. valeur    : le chiffre et son unité
  2. référence : la cible ou le seuil de comparaison
  3. tendance  : le sens et l'ampleur de la variation
  4. fraîcheur : la période couverte, la date de récupération et la source

Un indicateur dont aucune décision ne dépend n'a pas sa place ici : chaque tuile indique la décision qu'elle éclaire.
"""
import numpy as np
import pandas as pd

from ...constants import (GUST_ALERT_KN, GUST_WARN_KN, WAVE_ALERT_M, WAVE_WARN_M, WIND_ALERT_KN, WIND_WARN_KN)
from ...models import CppiRecord, DataSource, UnctadValue, WeatherPoint
from ..fmt import mois_fr, nb, signe_pct
from .series import complexe, escales_hebdo, tonnes_mensuelles, volumes_par_port


def _source(cle):
    s = DataSource.objects.filter(key=cle).first()
    return {"source_cle": cle, "source": s.name if s else cle, "source_url": s.url if s else "",
            "source_statut": s.status if s else "missing",
            "recupere": s.retrieved_at.isoformat() if s and s.retrieved_at else None}


def _tuile(id, titre, decision, valeur, unite, reference, tendance, sens, statut, periode, source, spark=None, badge="", detail=""):
    return {"id": id, "titre": titre, "decision": decision, "valeur": valeur, "unite": unite, "reference": reference,
            "tendance": tendance, "sens": sens, "statut": statut, "periode": periode, "spark": spark or [], "badge": badge,
            "detail": detail, **_source(source)}


def _indispo(id, titre, decision, source, raison):
    return _tuile(id, titre, decision, "—", "", raison, "", "flat", "na", "indisponible", source, badge="SOURCE INDISPONIBLE")


def _statut_variation(pct, tol_ok=-3.0, tol_warn=-10.0):
    return "ok" if pct >= tol_ok else "warn" if pct >= tol_warn else "alert"


# ------------------------------------------------------------------------------------------ 1. volumes
def tuile_volumes():
    titre, decision = "Volume mensuel (EVP)", "Dimensionner équipes et postes à quai pour le mois"
    df, scope, ports = complexe(volumes_par_port())
    if df is None or df.empty:
        return _indispo("volumes", titre, decision, "pola", "Aucune donnée de volumes en base.")
    s = df["total_teu"].dropna()
    dernier = s.index[-1]
    v, an_prec = float(s.iloc[-1]), s.get(dernier - pd.DateOffset(years=1))
    moy12 = float(s.iloc[-12:].mean())
    yoy = (v / an_prec - 1) * 100 if an_prec else None
    ports_txt = "Los Angeles + Long Beach" if len(ports) == 2 else "Los Angeles seul"
    ton = tonnes_mensuelles()
    ref_complexe = ""
    if len(ports) == 1 and not ton.empty and len(ton) > 13:
        yoy_t = (ton.total_t.iloc[-1] / ton.total_t.iloc[-13] - 1) * 100
        ref_complexe = f" · Complexe LA-LB en tonnes (PortWatch, {mois_fr(ton.index[-1].strftime('%Y-%m'))}) : {signe_pct(yoy_t)} sur un an"
        from .insights import lire
        lb = lire("lb", {})
        if lb.get("ok") and lb.get("complexe_dernier"):
            cd = lb["complexe_dernier"]
            ref_complexe += f" · Complexe estimé {mois_fr(cd['mois'])} : {nb(cd['evp'])} EVP (±{nb(cd['marge_pct'], 1)} %, estimation)"
    return _tuile("volumes", f"Volume mensuel · {ports_txt}", decision, nb(v), "EVP",
                  (f"Même mois un an avant : {nb(an_prec)} EVP · moyenne 12 mois : {nb(moy12)} EVP" if an_prec else f"Moyenne 12 mois : {nb(moy12)} EVP") + ref_complexe,
                  f"{signe_pct(yoy)} sur un an" if yoy is not None else "", "up" if (yoy or 0) > 0.5 else "down" if (yoy or 0) < -0.5 else "flat",
                  _statut_variation(yoy) if yoy is not None else "info", mois_fr(dernier.strftime("%Y-%m")), "pola",
                  spark=[round(float(x)) for x in s.iloc[-24:]], badge="" if len(ports) == 2 else "LONG BEACH MANQUANT",
                  detail="Cible : au moins le niveau de l'an dernier (seuil d'alerte : −10 %).")


# ------------------------------------------------------------------------------------------ 2. prévision
def tuile_prevision(prev):
    titre, decision = "Prévision du mois prochain (EVP)", "Anticiper la charge et la main-d'œuvre du mois suivant"
    if not prev or not prev.get("ok"):
        return _indispo("prevision", titre, decision, "pola", (prev or {}).get("raison", "Prévision non calculée."))
    p = prev["prevision"][0]
    pct = p["ecart_annee_prec_pct"]
    return _tuile("prevision", titre, decision, nb(p["valeur"]), "EVP",
                  f"Fourchette : {nb(p['bas'])} à {nb(p['haut'])} (erreur moyenne du modèle : ±{nb(p['mae'])} EVP, soit "
                  f"{nb(p['mae'] / p['valeur'] * 100, 1)} %)",
                  f"{signe_pct(pct)} vs même mois un an avant" if pct is not None else "",
                  "up" if (pct or 0) > 0.5 else "down" if (pct or 0) < -0.5 else "flat", "info", mois_fr(p["mois"]), "pola",
                  spark=[round(h["valeur"]) for h in prev["historique"][-12:]] + [round(x["valeur"]) for x in prev["prevision"]],
                  detail=f"Modèle : {prev['modele']} · {prev['gain_vs_naif_pct']:.0f} % d'erreur en moins que « même mois l'an dernier ».")


# ------------------------------------------------------------------------------------------ 3. escales hebdomadaires
def tuile_escales(anom):
    titre, decision = "Escales de porte-conteneurs · semaine", "Ajuster postes à quai et pilotes de la semaine"
    s = escales_hebdo()
    if len(s) < 30 or not anom or not anom.get("ok"):
        return _indispo("escales", titre, decision, "portwatch", "Historique hebdomadaire d'escales indisponible.")
    v, prec = float(s.iloc[-1]), float(s.iloc[-2])
    med = float(s.iloc[-27:-1].median())
    z = anom["derniere"].get("z") or 0.0
    ecart = (v / med - 1) * 100
    statut = "alert" if abs(z) >= 3 else "warn" if abs(z) >= 2 else "ok"
    fin = (s.index[-1] + pd.Timedelta(days=6)).strftime("%d/%m")
    return _tuile("escales", f"{titre} · Los Angeles-Long Beach", decision, nb(v), "escales",
                  f"Médiane des 26 semaines précédentes : {nb(med)} · écart : {signe_pct(ecart)}",
                  f"{signe_pct((v / prec - 1) * 100)} vs semaine précédente", "up" if v > prec else "down" if v < prec else "flat",
                  statut, f"semaine du {s.index[-1].strftime('%d/%m')} au {fin}", "portwatch",
                  spark=[int(x) for x in s.iloc[-26:]], detail="Seuil : alerte si l'écart dépasse 3 écarts robustes (z ≥ 3).")


# ------------------------------------------------------------------------------------------ 4. CPPI
def tuile_cppi():
    from ..collectors.cppi import EDITION_2024, EDITION_2025
    titre, decision = "Rang CPPI 2025 · temps au port", "Choisir où chercher des gains de temps d'escale (investissement, procédures)"
    g = lambda nom, an=2025, ed=EDITION_2025: CppiRecord.objects.filter(port_name=nom, year=an, edition=ed).first()
    la, lb, dj, top = g("Los Angeles"), g("Long Beach"), g("Djibouti"), g("Fuzhou")
    if not (la and lb and la.rank and lb.rank):
        return _indispo("cppi", titre, decision, "cppi", "Classement CPPI 2025 absent de la base.")
    n = CppiRecord.objects.filter(year=2025, edition=EDITION_2025, rank__isnull=False).count()
    la24, lb24 = g("Los Angeles", 2024, EDITION_2024), g("Long Beach", 2024, EDITION_2024)
    gain_la = (la24.rank - la.rank) if la24 else None
    gain_lb = (lb24.rank - lb.rank) if lb24 else None
    tend = " · ".join(t for t in [f"LA {gain_la:+d} places vs 2024" if gain_la is not None else "", f"LB {gain_lb:+d}" if gain_lb is not None else ""] if t).replace("-", "−")
    ref = f"{('Djibouti ' + str(dj.rank) + 'ᵉ · ') if dj and dj.rank else ''}{('Fuzhou 1ᵉʳ · ') if top and top.rank == 1 else ''}score LA {la.score:+.0f}, LB {lb.score:+.0f} (0 = moyenne)".replace("-", "−")
    pire = max(la.rank, lb.rank)
    return _tuile("cppi", "Rang CPPI 2025 · Long Beach / Los Angeles", decision, f"{lb.rank}ᵉ / {la.rank}ᵉ", f"/ {n}", ref, tend,
                  "up" if (gain_la or 0) > 0 else "down", "alert" if pire > 0.8 * n else "warn" if pire > 0.5 * n else "ok", "édition 2025", "cppi",
                  detail="Le CPPI est un score de temps au port, pas un volume : un grand port actif peut être mal classé. Un classement bouge beaucoup d'une année à l'autre.")


# ------------------------------------------------------------------------------------------ 5. CNUCED temps médian
def tuile_cnuced():
    titre, decision = "Temps médian au port · conteneurs", "Fixer l'objectif de temps d'escale face aux autres pays"
    q = UnctadValue.objects.filter(series="median_time_container")
    us = {r.period: r.value for r in q.filter(entity_label="United States of America")}
    if not us:
        return _indispo("cnuced", titre, decision, "unctad", "Série CNUCED absente de la base.")
    an = max(us)
    autres = {r.entity_label: r.value for r in q.filter(period=an).exclude(entity_label__in=["United States of America", "Eastern Africa"])}
    prec = us.get(str(int(an) - 1))
    tend = (us[an] / prec - 1) * 100 if prec else None
    med = float(np.median(list(autres.values()))) if autres else None
    ref = " · ".join(f"{n.split(' (')[0].replace('Netherlands', 'Pays-Bas').replace('Germany', 'Allemagne').replace('China', 'Chine').replace('Singapore', 'Singapour').replace('Japan', 'Japon')} {nb(v, 2)} j"
                     for n, v in sorted(autres.items(), key=lambda t: t[1])[:4])
    return _tuile("cnuced", "Temps médian au port · conteneurs, États-Unis", decision, nb(us[an], 2), "jours",
                  f"Comparaison {an} : {ref}", f"{signe_pct(tend)} vs {int(an) - 1}" if tend is not None else "",
                  "down" if (tend or 0) < 0 else "up", "warn" if med and us[an] > 1.2 * med else "ok", f"année {an}", "unctad",
                  spark=[us[k] for k in sorted(us)], badge="DJIBOUTI NON PUBLIÉ",
                  detail="UNCTADstat ne publie pas Djibouti dans cette série : voir la vue « Comparaison mondiale » pour les autres mesures.")


# ------------------------------------------------------------------------------------------ 6. AIS
def tuile_ais(ais, baseline):
    titre, decision = "Gros navires dans la baie", "Réguler les entrées/sorties et surveiller la file au mouillage"
    if not ais.get("disponible"):
        return _indispo("ais", titre, decision, "ais_live", "Ni flux en direct ni archive AIS disponibles.")
    live = ais["origine"] == "live"
    ref = ais["reference"]
    med = ref.get("navires_med")
    ecart = ais["gros_navires"] - med if med is not None else None
    src = "ais_live" if live else "ais_archive"
    instant = pd.Timestamp(ais["instant"])
    return _tuile("ais", "Gros navires dans la baie (cargos, pétroliers)", decision, nb(ais["gros_navires"]), "navires",
                  (f"Habituel à cette heure : {nb(med)} (plage courante {nb(ref['navires_p25'])}–{nb(ref['navires_p75'])}, sur {ref.get('jours', '?')} jours)"
                   if med is not None else "Pas de référence horaire"),
                  f"{ecart:+.0f} vs habituel · dont {ais['a_l_ancre']} à l'ancre".replace("-", "−") if ecart is not None else f"dont {ais['a_l_ancre']} à l'ancre",
                  "up" if (ecart or 0) > 0 else "down" if (ecart or 0) < 0 else "flat", "info",
                  ("direct · " if live else "ARCHIVE · ") + instant.strftime("%d/%m/%Y %H:%M UTC"), src,
                  badge="" if live else "ARCHIVE — PAS DU DIRECT",
                  detail="Direct : aisstream.io (couverture gratuite variable). Archive : extrait AIS du TP, 23/02-01/03/2026." )


# ------------------------------------------------------------------------------------------ 7 et 8. météo
def _spark(champ):
    return [round(float(getattr(p, champ)), 1) for p in WeatherPoint.objects.filter(is_current=False).order_by("time") if getattr(p, champ) is not None]


def tuiles_meteo(meteo):
    t1, t2 = ("Vent et rafales", "Autoriser ou différer pilotage, remorquage et grues"), ("Vagues au large", "Autoriser l'entrée des grands navires / pilotage")
    if not meteo.get("disponible"):
        return [_indispo("vent", *t1, "weather", meteo.get("message", "Météo indisponible.")), _indispo("vagues", *t2, "weather", meteo.get("message", ""))]
    c, m = meteo["courant"], meteo["max"]
    niv = {a["variable"]: a["niveau"] for a in meteo["alertes"] if a["niveau"] == "alerte"}
    niv_v = {a["variable"]: a["niveau"] for a in meteo["alertes"]}

    def statut(*vars_):
        return "alert" if any(niv.get(v) for v in vars_) else "warn" if any(niv_v.get(v) for v in vars_) else "ok"

    heure = pd.Timestamp(c["heure"]).strftime("%d/%m %H:%M UTC")
    vent = _tuile("vent", "Vent et rafales · port", t1[1], f"{nb(c['vent'], 0)} / {nb(c['rafales'], 0)}", "nœuds (vent / rafales)",
                  f"Vigilance : vent ≥ {nb(WIND_WARN_KN)} ou rafales ≥ {nb(GUST_WARN_KN)} · alerte ≥ {nb(WIND_ALERT_KN)}",
                  f"Maximum prévu 48 h : vent {nb(m['vent'], 0)}, rafales {nb(m['rafales'], 0)} nœuds", "up" if (m["rafales"] or 0) > (c["rafales"] or 0) else "down",
                  statut("vent", "rafales"), heure, "weather", spark=_spark("gust_kn"),
                  detail="Modèle global Open-Meteo, grille ≈ 11 km : indicatif, pas une mesure au quai.")
    mer = _tuile("vagues", "Vagues au large de la jetée", t2[1], nb(c["vagues"], 1), "m" + (f" · période {nb(c['periode'], 0)} s" if c.get("periode") else ""),
                 f"Vigilance ≥ {nb(WAVE_WARN_M, 1)} m · alerte ≥ {nb(WAVE_ALERT_M, 1)} m", f"Maximum prévu 48 h : {nb(m['vagues'], 1)} m",
                 "up" if (m["vagues"] or 0) > (c["vagues"] or 0) else "down", statut("vagues"), heure, "weather", spark=_spark("wave_m"),
                 detail="Hauteur significative des vagues au large ; la houle est atténuée dans le bassin abrité.")
    return [vent, mer]


def toutes_les_tuiles(prev, anom_hebdo, meteo, ais):
    return [tuile_volumes(), tuile_prevision(prev), tuile_escales(anom_hebdo), tuile_cppi(), tuile_cnuced(), tuile_ais(ais, None), *tuiles_meteo(meteo)]
