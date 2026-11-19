"""FMI PortWatch : escales quotidiennes par port (signaux AIS des Nations unies).

Donne aussi les TONNES de conteneurs importées/exportées par port (estimation à partir de la taille des navires, pas des EVP) :
c'est la seule mesure de volume gratuite et complète du COMPLEXE Los Angeles-Long Beach (le port de Long Beach seul n'est pas séparé).
Sert à (1) suivre l'activité des navires du complexe Los Angeles-Long Beach, (2) comparer avec Djibouti, Singapour
et Rotterdam, là où la CNUCED ne publie pas Djibouti. API publique ArcGIS, sans clé. Délai de publication : quelques jours.
"""
import json
from datetime import date

import pandas as pd

from ...constants import PORTWATCH_DAILY, PORTWATCH_PORTS, PORTWATCH_SINCE
from ...models import PortCallDaily
from ..registry import declare
from .common import PROCESSED, SourceUnavailable, http_get

CSV = PROCESSED / "portwatch_daily_portcalls.csv"
CHAMPS = "date,portid,portname,portcalls_container,portcalls_dry_bulk,portcalls_general_cargo,portcalls_roro,portcalls_tanker,portcalls,import_container,export_container"


def fetch():
    ids = ",".join(f"'{p}'" for p in PORTWATCH_PORTS)
    lignes, offset = [], 0
    while True:
        rep = json.loads(http_get(PORTWATCH_DAILY, params={
            "where": f"portid IN ({ids}) AND date >= DATE '{PORTWATCH_SINCE}'", "outFields": CHAMPS, "orderByFields": "portid,date",
            "resultOffset": offset, "resultRecordCount": 1000, "returnGeometry": "false", "f": "json"}))
        if "error" in rep:
            raise SourceUnavailable(f"PortWatch : {rep['error'].get('message', 'erreur')}")
        page = [f["attributes"] for f in rep.get("features", [])]
        lignes += page
        if len(page) < 1000 and not rep.get("exceededTransferLimit"):
            break
        offset += len(page)
    if not lignes:
        raise SourceUnavailable("PortWatch n'a renvoyé aucune ligne")
    df = pd.DataFrame(lignes)
    df["date"] = pd.to_datetime(df["date"]).dt.date if df["date"].dtype == object else pd.to_datetime(df["date"], unit="ms").dt.date
    df = df.sort_values(["portid", "date"]).drop_duplicates(["portid", "date"])
    df.to_csv(CSV, index=False)
    return df


def load():
    if not CSV.exists():
        raise SourceUnavailable("fichier data/processed/portwatch_daily_portcalls.csv absent : lancer `python manage.py fetch_all`")
    df = pd.read_csv(CSV, parse_dates=["date"]).fillna(0)
    PortCallDaily.objects.all().delete()
    PortCallDaily.objects.bulk_create([
        PortCallDaily(port_id=r.portid, port_name=PORTWATCH_PORTS.get(r.portid, r.portname), date=r.date.date(),
                      container=int(r.portcalls_container), dry_bulk=int(r.portcalls_dry_bulk),
                      general_cargo=int(r.portcalls_general_cargo), roro=int(r.portcalls_roro), tanker=int(r.portcalls_tanker),
                      total=int(r.portcalls), import_container_t=float(r.import_container), export_container_t=float(r.export_container))
        for r in df.itertuples()
    ], batch_size=2000)
    dernier = df.date.max().date()
    declare("portwatch", "ok", f"{len(df)} jours-ports chargés, dernier jour publié : {dernier}.", rows=len(df),
            last_period=str(dernier), retrieved=False, url="https://portwatch.imf.org/")
    return len(df)


def refresh():
    try:
        fetch()
        declare("portwatch", "ok", "téléchargement réussi", retrieved=True)
    except SourceUnavailable as exc:
        declare("portwatch", "error", f"Source injoignable ({exc}) : dernières données conservées.", retrieved=False)
    return load()
