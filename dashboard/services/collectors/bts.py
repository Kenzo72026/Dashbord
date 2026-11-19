"""BTS (ministère américain des Transports) : EVP totaux mensuels de Long Beach, janvier 2019 → août 2023.

Seule source ouverte, gratuite et officielle trouvée pour Long Beach sans passer par polb.com (qui refuse l'accès). Deux jeux de
données publics (domaine public, API Socrata sans clé) se complètent :
  * rd72-aq8r « Monthly TEU Data »                          : 2019-01 → 2022-10, 9 ports américains
  * iahn-a7j4 « TEU Handled by Select U.S. Container Ports » : 2020-01 → 2023-08, 9 ports américains
Ils ne donnent que le TOTAL mensuel (pas d'import/export, pas de chargés/vides) et s'arrêtent en août 2023.

Contrôles : (1) les EVP de Los Angeles du BTS doivent coïncider avec ceux publiés par le port de Los Angeles (écart ≤ 5 EVP) ;
(2) sur les mois communs aux deux jeux, les écarts de ±1 EVP (arrondis) sont ignorés ; un écart plus grand est signalé et le
jeu rd72 est retenu (cas constaté : novembre 2020, 783 523 contre 753 524, coquille probable puisque le rapport tonnes/EVP du
mois n'est cohérent qu'avec 783 523).
"""
import io
import json

import pandas as pd

from ...constants import BTS_IAHN, BTS_RD72, SOURCES
from ..registry import declare
from .common import PROCESSED, SourceUnavailable, http_get

CSV = PROCESSED / "bts_long_beach_total_teu.csv"
POLA_CSV = PROCESSED / "pola_monthly_teu.csv"
TOLERANCE_ARRONDI = 5  # EVP


def assembler(rd72: pd.DataFrame, iahn: pd.DataFrame, pola: pd.DataFrame | None = None) -> pd.DataFrame:
    """Fonction pure (testable) : fusionne les deux jeux BTS en une série Long Beach et la contrôle."""
    a = rd72.copy()
    a["mois"] = pd.to_datetime(a["Port"], format="%m/%d/%Y")
    a = a.set_index("mois")
    b = iahn.copy()
    b["mois"] = pd.to_datetime(b["unnamed_column"])
    b = b.set_index("mois")
    lb1 = pd.to_numeric(a["Long Beach, CA"], errors="coerce")
    lb2 = pd.to_numeric(b["long_beach"], errors="coerce")
    if lb1.dropna().empty or lb2.dropna().empty:
        raise SourceUnavailable("jeux BTS illisibles : colonne Long Beach vide")
    lignes, notes = {}, {}
    for m in sorted(set(lb1.dropna().index) | set(lb2.dropna().index)):
        v1, v2 = lb1.get(m), lb2.get(m)
        if pd.notna(v1) and pd.notna(v2) and abs(v1 - v2) > TOLERANCE_ARRONDI:
            lignes[m] = (float(v1), "rd72-aq8r")
            notes[m] = f"jeux BTS divergents ({v1:,.0f} contre {v2:,.0f}) : jeu rd72-aq8r retenu"
        elif pd.notna(v1):
            lignes[m] = (float(v1), "rd72-aq8r")
        else:
            lignes[m] = (float(v2), "iahn-a7j4")
    df = pd.DataFrame([{"mois": m.strftime("%Y-%m"), "total_teu": v, "source": s, "note": notes.get(m, "")} for m, (v, s) in lignes.items()])
    # contrôle croisé avec Los Angeles publié par le port
    if pola is not None:
        la = pd.to_numeric(a["Los Angeles, CA"], errors="coerce").dropna()
        pola_idx = pola.assign(mois=pd.to_datetime(dict(year=pola.year, month=pola.month, day=1))).set_index("mois").total_teu
        com = la.index.intersection(pola_idx.index)
        ecart = (la.loc[com] - pola_idx.loc[com]).abs().max() if len(com) else None
        if ecart is not None and ecart > TOLERANCE_ARRONDI:
            raise SourceUnavailable(f"contrôle échoué : EVP de Los Angeles du BTS ≠ port de Los Angeles (écart maximal {ecart:,.0f} EVP)")
    return df


def fetch():
    rd72 = pd.read_csv(io.StringIO(http_get(BTS_RD72)))
    iahn = pd.DataFrame(json.loads(http_get(BTS_IAHN, params={"$limit": 500})))
    pola = pd.read_csv(POLA_CSV) if POLA_CSV.exists() else None
    df = assembler(rd72, iahn, pola)
    df.to_csv(CSV, index=False)
    return df


def load():
    if not CSV.exists():
        declare("bts", "missing", "Série BTS de Long Beach absente : lancer `python manage.py fetch_all --only bts`.", retrieved=False)
        raise SourceUnavailable("fichier data/processed/bts_long_beach_total_teu.csv absent")
    df = pd.read_csv(CSV)
    divergents = df[df.note.fillna("") != ""]
    declare("bts", "ok", f"{len(df)} mois de Long Beach ({df.mois.iloc[0]} → {df.mois.iloc[-1]}), total EVP uniquement."
            + (f" Divergence entre les deux jeux : {', '.join(divergents.mois)}." if len(divergents) else ""),
            rows=len(df), last_period=df.mois.iloc[-1], url=SOURCES["bts"]["url"], retrieved=False,
            notes="Domaine public (U.S. DOT / BTS). Total mensuel seulement ; s'arrête en août 2023. EVP de Los Angeles du BTS = ceux du port (écart ≤ 2 EVP).")
    return len(df)


def refresh():
    try:
        fetch()
        declare("bts", "ok", "téléchargement réussi", retrieved=True)
    except SourceUnavailable as exc:
        declare("bts", "error", f"Source injoignable ou incohérente ({exc}) : dernières données conservées.", retrieved=False)
    return load()
