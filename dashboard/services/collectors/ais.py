"""AIS : positions des navires autour de San Pedro Bay.

Deux origines, jamais mélangées :
  * live    : flux WebSocket d'aisstream.io (clé gratuite dans la variable d'environnement AISSTREAM_API_KEY).
              La clé reste côté serveur (le fournisseur interdit les connexions directes depuis un navigateur).
  * archive : extrait AIS du TP (MarineCadastre, 23/02-01/03/2026). Affiché uniquement si le direct est indisponible,
              avec la mention « archive » et sa date. Il fournit aussi la référence horaire de trafic (baseline).
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone as tz

import pandas as pd
from django.conf import settings
from django.utils import timezone

from ...constants import AIS_BBOX, AISSTREAM_WS, type_group
from ...models import AisPosition
from ..registry import declare, mark_stale_live
from .common import PROCESSED, SourceUnavailable

ARCHIVE_CSV = PROCESSED / "ais_archive_snapshot.csv"
BASELINE_CSV = PROCESSED / "ais_baseline_hourly.csv"
MESSAGE_SANS_CLE = (
    "Flux AIS en direct indisponible : aucune clé AISSTREAM_API_KEY. Inscription gratuite sur aisstream.io, puis variable "
    "d'environnement ou fichier .env (voir .env.example). En attendant, la carte affiche l'archive AIS du TP, clairement datée."
)


# ------------------------------------------------------------------ direct (aisstream.io)
def _parse_heure(texte):
    """« 2026-11-18 20:01:02.123456 +0000 UTC » → datetime UTC (repli : maintenant)."""
    try:
        return datetime.strptime(str(texte)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz.utc)
    except ValueError:
        return datetime.now(tz.utc)


def traiter_message(msg, positions, statiques):
    """Fonction pure (testable) : met à jour les dictionnaires `positions` et `statiques` à partir d'un message aisstream."""
    meta = msg.get("MetaData") or msg.get("Metadata") or {}
    mmsi = str(meta.get("MMSI") or meta.get("MMSI_String") or "").strip()
    if len(mmsi) != 9:
        return
    genre = msg.get("MessageType")
    corps = (msg.get("Message") or {}).get(genre) or {}
    if genre == "PositionReport":
        lat = meta.get("latitude", meta.get("Latitude", corps.get("Latitude")))
        lon = meta.get("longitude", meta.get("Longitude", corps.get("Longitude")))
        if lat is None or lon is None:
            return
        positions[mmsi] = {
            "name": (meta.get("ShipName") or "").strip(), "lat": float(lat), "lon": float(lon), "sog": corps.get("Sog"),
            "cog": corps.get("Cog"), "nav_status": corps.get("NavigationalStatus"),
            "seen_at": _parse_heure(meta.get("time_utc", "")),
        }
    elif genre == "ShipStaticData":
        dim = corps.get("Dimension") or {}
        longueur = (dim.get("A") or 0) + (dim.get("B") or 0)
        statiques[mmsi] = {"ship_type": corps.get("Type"), "length": longueur or None, "name": (corps.get("Name") or "").strip()}


async def _ecouter(cle, duree, positions, statiques):
    import websockets
    async with websockets.connect(AISSTREAM_WS, open_timeout=15, max_size=2 ** 22) as ws:
        # l'abonnement doit partir dans les 3 secondes suivant la connexion
        await ws.send(json.dumps({"APIKey": cle, "BoundingBoxes": [AIS_BBOX],
                                  "FilterMessageTypes": ["PositionReport", "ShipStaticData"]}))
        boucle = asyncio.get_running_loop()
        fin = boucle.time() + duree
        while boucle.time() < fin:
            try:
                brut = await asyncio.wait_for(ws.recv(), timeout=max(0.2, fin - boucle.time()))
            except asyncio.TimeoutError:
                break
            msg = json.loads(brut)
            if "error" in msg:
                raise SourceUnavailable(f"aisstream a refusé la connexion : {msg['error']}")
            traiter_message(msg, positions, statiques)


def collect_live(duree=45):
    """Écoute le flux `duree` secondes et enregistre la dernière position de chaque navire. Retourne le nombre de navires."""
    cle = settings.AISSTREAM_API_KEY
    if not cle:
        declare("ais_live", "missing", MESSAGE_SANS_CLE, retrieved=False)
        return 0
    positions, statiques = {}, {}
    try:
        asyncio.run(_ecouter(cle, duree, positions, statiques))
    except SourceUnavailable as exc:
        declare("ais_live", "error", str(exc), retrieved=False)
        return 0
    except Exception as exc:  # réseau, TLS, quota… : on garde l'état précédent et on le dit
        declare("ais_live", "error", f"Flux AIS injoignable ({type(exc).__name__}) : dernières positions conservées.", retrieved=False)
        return 0
    for mmsi, p in positions.items():
        s = statiques.get(mmsi, {})
        ancien = AisPosition.objects.filter(mmsi=mmsi, origin="live").first()
        type_ais = s.get("ship_type") if s.get("ship_type") is not None else (ancien.ship_type if ancien else None)
        AisPosition.objects.update_or_create(mmsi=mmsi, origin="live", defaults={
            "name": p["name"] or s.get("name", ""), "lat": p["lat"], "lon": p["lon"], "sog": p["sog"], "cog": p["cog"],
            "nav_status": p["nav_status"], "ship_type": type_ais, "type_group": type_group(type_ais),
            "length": s.get("length") or (ancien.length if ancien else None), "seen_at": p["seen_at"]})
    AisPosition.objects.filter(origin="live", seen_at__lt=timezone.now() - timedelta(hours=6)).delete()
    total = AisPosition.objects.filter(origin="live").count()
    declare("ais_live", "ok", f"{len(positions)} navires reçus en {duree} s ; {total} navires suivis (positions < 6 h).",
            rows=total, last_period=timezone.now().strftime("%Y-%m-%d %H:%M UTC"), retrieved=True,
            notes="Couverture gratuite par stations terrestres : peut être faible hors de la baie de Los Angeles.")
    return len(positions)


def live_status():
    """Met à jour l'état « périmé » du direct et le renvoie (pour l'affichage)."""
    mark_stale_live("ais_live", settings.AIS_STALE_SECONDS)


# ------------------------------------------------------------------ archive du TP
def build_archive(source_csv):
    """Prépare l'archive à partir du gros fichier AIS du TP (ais_clean.csv) : dernier jour + référence horaire."""
    colonnes = ["mmsi", "base_date_time", "longitude", "latitude", "sog", "cog", "vessel_name", "vessel_type", "status", "length", "type_group"]
    df = pd.read_csv(source_csv, usecols=colonnes, parse_dates=["base_date_time"])
    (lat0, lon0), (lat1, lon1) = AIS_BBOX
    df = df[df.latitude.between(lat0, lat1) & df.longitude.between(lon0, lon1)]
    df["groupe"] = df.vessel_type.map(type_group)
    dernier_jour = df.base_date_time.dt.date.max()
    snap = (df[df.base_date_time.dt.date == dernier_jour].sort_values("base_date_time").groupby("mmsi").tail(1))
    snap.drop(columns=["type_group"]).rename(columns={"vessel_name": "name"}).to_csv(ARCHIVE_CSV, index=False)
    # référence : nombre de navires cargo/pétroliers distincts présents dans la zone, par heure UTC, médiane sur les jours
    gros = df[df.groupe.isin(["Cargo (conteneurs, vrac)", "Pétrolier / chimiquier"])].copy()
    gros["jour"], gros["heure"] = gros.base_date_time.dt.date, gros.base_date_time.dt.hour
    gros["immobile"] = gros.sog < 0.5
    par = gros.groupby(["jour", "heure"]).agg(navires=("mmsi", "nunique"))
    immo = gros[gros.immobile].groupby(["jour", "heure"]).agg(immobiles=("mmsi", "nunique"))
    ancre = gros[gros.status == 1].groupby(["jour", "heure"]).agg(ancre=("mmsi", "nunique"))  # statut AIS 1 = à l'ancre
    tab = par.join(immo, how="left").join(ancre, how="left").fillna(0).reset_index()
    ref = tab.groupby("heure").agg(navires_med=("navires", "median"), navires_p25=("navires", lambda s: s.quantile(.25)),
                                   navires_p75=("navires", lambda s: s.quantile(.75)), immobiles_med=("immobiles", "median"),
                                   ancre_med=("ancre", "median"), ancre_p75=("ancre", lambda s: s.quantile(.75)),
                                   jours=("jour", "nunique")).reset_index()
    ref.to_csv(BASELINE_CSV, index=False)
    return len(snap), int(ref.jours.max())


def load_archive():
    if not ARCHIVE_CSV.exists():
        declare("ais_archive", "missing", "archive AIS absente : lancer `python manage.py build_ais_archive <ais_clean.csv>`", retrieved=False)
        return 0
    df = pd.read_csv(ARCHIVE_CSV, parse_dates=["base_date_time"])
    AisPosition.objects.filter(origin="archive").delete()
    AisPosition.objects.bulk_create([
        AisPosition(mmsi=str(int(r.mmsi)), name=str(r.name) if pd.notna(r.name) else "", lat=r.latitude, lon=r.longitude,
                    sog=r.sog, cog=r.cog, nav_status=int(r.status) if pd.notna(r.status) else None,
                    ship_type=int(r.vessel_type) if pd.notna(r.vessel_type) else None, type_group=r.groupe,
                    length=r.length if pd.notna(r.length) else None, seen_at=r.base_date_time.tz_localize("UTC"), origin="archive")
        for r in df.itertuples()
    ], ignore_conflicts=True)
    fin = df.base_date_time.max()
    declare("ais_archive", "ok", f"{len(df)} navires (dernière position du {fin:%d/%m/%Y}). Données historiques, pas du direct.",
            rows=len(df), last_period=f"{fin:%Y-%m-%d}", retrieved=False,
            notes="Extrait fourni avec le TP (MarineCadastre AIS, NOAA/BOEM), zone Los Angeles-Long Beach.")
    from datetime import datetime, timezone as _tz
    from ...models import DataSource
    DataSource.objects.filter(key="ais_archive").update(retrieved_at=datetime.fromtimestamp(ARCHIVE_CSV.stat().st_mtime, _tz.utc))
    return len(df)
