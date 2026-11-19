"""Accès aux séries stockées en base (jamais d'appel réseau ici)."""
import pandas as pd

from ...models import MonthlyVolume, PortCallDaily

COMPOSANTES = ["loaded_imports", "empty_imports", "loaded_exports", "empty_exports"]


def volumes_par_port() -> dict[str, pd.DataFrame]:
    """{'LA': DataFrame, 'LB': DataFrame} indexés par mois, avec les 4 composantes et le total (EVP)."""
    out = {}
    for port in ("LA", "LB"):
        lignes = list(MonthlyVolume.objects.filter(port=port).order_by("month").values("month", *COMPOSANTES, "total_teu"))
        if lignes:
            df = pd.DataFrame(lignes)
            df["month"] = pd.to_datetime(df["month"])
            out[port] = df.set_index("month").sort_index().asfreq("MS")
    return out


def complexe(vol: dict[str, pd.DataFrame]):
    """Série du complexe San Pedro Bay. Si Long Beach est absente, on travaille sur Los Angeles seul et on le dit.

    Retourne (DataFrame des composantes + total, étiquette de périmètre, ports inclus).
    """
    if "LA" not in vol:
        return None, "aucune donnée", []
    if "LB" in vol:
        idx = vol["LA"].dropna(subset=["total_teu"]).index.intersection(vol["LB"].dropna(subset=["total_teu"]).index)
        df = vol["LA"].loc[idx, COMPOSANTES + ["total_teu"]].add(vol["LB"].loc[idx, COMPOSANTES + ["total_teu"]])
        return df.asfreq("MS"), "San Pedro Bay (Los Angeles + Long Beach)", ["LA", "LB"]
    return vol["LA"][COMPOSANTES + ["total_teu"]].dropna().asfreq("MS"), "Los Angeles seul (Long Beach non importé)", ["LA"]


def escales_hebdo(port_id="port664", colonne="container") -> pd.Series:
    """Escales hebdomadaires (semaines complètes lundi-dimanche) d'un port PortWatch."""
    q = PortCallDaily.objects.filter(port_id=port_id).order_by("date").values("date", colonne)
    df = pd.DataFrame(list(q))
    if df.empty:
        return pd.Series(dtype=float)
    s = pd.Series(df[colonne].values, index=pd.to_datetime(df["date"])).asfreq("D")
    hebdo = s.resample("W-SUN", label="left", closed="right").agg(["sum", "count"])
    hebdo = hebdo[hebdo["count"] == 7]["sum"]
    hebdo.index = hebdo.index + pd.Timedelta(days=1)  # le lundi qui ouvre la semaine
    return hebdo.astype(float)


def tonnes_mensuelles(port_id="port664") -> pd.DataFrame:
    """Tonnes de conteneurs importées / exportées par mois (estimation PortWatch), mois COMPLETS seulement.

    Mesure du complexe Los Angeles-Long Beach en bloc : ce ne sont ni des EVP, ni des chiffres séparés par port.
    """
    q = PortCallDaily.objects.filter(port_id=port_id).order_by("date").values("date", "import_container_t", "export_container_t")
    df = pd.DataFrame(list(q))
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    d = df.set_index("date")
    jours = d["import_container_t"].resample("MS").count()
    m = d.resample("MS").sum()
    attendus = m.index.days_in_month
    m = m[(jours.reindex(m.index).values == attendus)]  # un mois partiel fausserait la comparaison
    m["total_t"] = m["import_container_t"] + m["export_container_t"]
    return m.rename(columns={"import_container_t": "import_t", "export_container_t": "export_t"})
