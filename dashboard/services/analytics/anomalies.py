"""Détection d'anomalies : volumes mensuels (STL robuste) et escales hebdomadaires (médiane glissante).

Une anomalie est un écart anormal par rapport au comportement habituel, pas une cause : l'outil dit QUOI et DE COMBIEN,
l'humain cherche POURQUOI. Pour les volumes, un diagnostic simple indique quel flux (importations chargées,
exportations chargées, vides) explique l'écart.
"""
import numpy as np
import pandas as pd

Z_SEUIL = 3.0
ECART_MIN_PCT = 8.0  # matérialité : un écart de moins de 8 % de l'attendu n'appelle aucune action, même s'il est « statistiquement » rare
LIBELLES = {"loaded_imports": "importations chargées", "empty_imports": "importations de vides",
            "loaded_exports": "exportations chargées", "empty_exports": "exportations de vides"}


def _z_robuste(x: pd.Series) -> pd.Series:
    med = x.median()
    mad = (x - med).abs().median() * 1.4826
    return (x - med) / (mad if mad > 0 else x.std() or 1.0)


def anomalies_mensuelles(df: pd.DataFrame, z_seuil=Z_SEUIL):
    """df : composantes + total_teu par mois. Décomposition STL robuste (tendance + saison + reste) du total."""
    from statsmodels.tsa.seasonal import STL
    y = df["total_teu"].dropna()
    if len(y) < 36:
        return {"ok": False, "raison": "moins de 3 ans d'historique : détection saisonnière impossible"}
    stl = STL(y, period=12, robust=True).fit()
    z = _z_robuste(stl.resid)
    attendu = stl.trend + stl.seasonal
    liste = []
    ecart_pct = (y / attendu - 1) * 100
    candidats = z.index[(np.abs(z) >= z_seuil) & (np.abs(ecart_pct) >= ECART_MIN_PCT)]  # deux conditions : statistique ET matérielle
    for mois in candidats:
        diag = []
        an_avant = mois - pd.DateOffset(years=1)
        if an_avant in df.index:
            for col, nom in LIBELLES.items():
                avant, maintenant = df.loc[an_avant, col], df.loc[mois, col]
                if avant and avant > 1000:
                    diag.append({"flux": nom, "variation_pct": float((maintenant / avant - 1) * 100),
                                 "ecart_evp": float(maintenant - avant)})
            diag.sort(key=lambda d: -abs(d["ecart_evp"]))
        liste.append({"mois": mois.strftime("%Y-%m"), "valeur": float(y[mois]), "attendu": float(attendu[mois]),
                      "ecart_pct": float((y[mois] / attendu[mois] - 1) * 100), "z": float(z[mois]),
                      "sens": "hausse" if z[mois] > 0 else "baisse", "diagnostic": diag[:3]})
    return {"ok": True, "seuil_z": z_seuil, "methode": f"STL robuste (période 12) ; signalé si |z| ≥ {z_seuil:g} (z = reste / (1,4826 × MAD)) ET écart ≥ {ECART_MIN_PCT:g} % de l'attendu",
            "anomalies": liste, "serie": [{"mois": d.strftime("%Y-%m"), "valeur": float(y[d]), "attendu": float(attendu[d]),
                                           "z": float(z[d])} for d in y.index]}


def anomalies_hebdo(s: pd.Series, fenetre=26, z_seuil=Z_SEUIL):
    """s : escales par semaine. Écart à la médiane des `fenetre` semaines précédentes, en écarts robustes."""
    if len(s) < fenetre + 8:
        return {"ok": False, "raison": "historique hebdomadaire insuffisant"}
    med = s.rolling(fenetre).median().shift(1)
    mad = s.rolling(fenetre).apply(lambda v: np.median(np.abs(v - np.median(v))), raw=True).shift(1) * 1.4826
    z = ((s - med) / mad.replace(0, np.nan)).dropna()
    serie = [{"semaine": d.strftime("%Y-%m-%d"), "valeur": float(s[d]), "mediane": float(med[d]), "mad": float(mad[d]), "z": float(z.get(d, np.nan))}
             for d in s.index[-104:] if not np.isnan(med[d])]
    recents = [p for p in serie[-8:] if abs(p["z"]) >= z_seuil]
    derniere = serie[-1]
    return {"ok": True, "seuil_z": z_seuil, "serie": serie, "recentes": recents, "derniere": derniere}
