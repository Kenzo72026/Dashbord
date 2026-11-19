"""Prévision mensuelle des volumes (EVP) avec marge d'incertitude.

Méthode (celle du cours, séquence 6 partie 2) :
  1. mesurer l'erreur moyenne du modèle sur le passé (MAE) par un « backtest » : on se replace à 24 dates passées,
     on prévoit les 6 mois suivants avec les seules données connues à cette date, puis on compare au réel ;
  2. afficher « prévision − erreur » et « prévision + erreur » ;
  3. préciser l'horizon (mois +1, +2…) : l'erreur est calculée séparément pour chaque horizon ;
  4. l'erreur est recalculée à chaque actualisation des données.

Trois modèles sont comparés et le plus précis est retenu :
  * naïf saisonnier : même mois l'an dernier (la référence à battre) ;
  * ratio annuel   : même mois l'an dernier × évolution récente (moyenne des 3 derniers mois / mêmes mois un an plus tôt) ;
  * Holt-Winters   : lissage exponentiel avec tendance amortie et saisonnalité de 12 mois.
"""
import warnings

import numpy as np
import pandas as pd

HORIZON = 6
N_ORIGINES = 24


def _naif_saisonnier(train: pd.Series, h: int) -> np.ndarray:
    return np.array([train.iloc[-12 + k] for k in range(h)])


def _ratio_annuel(train: pd.Series, h: int) -> np.ndarray:
    ratio = float(np.mean(train.iloc[-3:].values / train.iloc[-15:-12].values))
    return np.array([train.iloc[-12 + k] * ratio for k in range(h)])


def _holt_winters(train: pd.Series, h: int) -> np.ndarray:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = ExponentialSmoothing(train, trend="add", damped_trend=True, seasonal="add", seasonal_periods=12,
                                   initialization_method="estimated").fit()
        return np.asarray(fit.forecast(h))


MODELES = {
    "Naïf saisonnier (même mois l'an dernier)": _naif_saisonnier,
    "Ratio annuel (saison × tendance récente)": _ratio_annuel,
    "Holt-Winters (tendance amortie + saison)": _holt_winters,
}


def backtest(y: pd.Series, h=HORIZON, n_orig=N_ORIGINES):
    """Erreurs absolues par modèle, origine et horizon : dict nom → tableau (n_origines, h) d'erreurs signées."""
    n = len(y)
    debut = max(36, n - h - n_orig + 1)
    origines = list(range(debut, n - h + 1))
    res = {nom: [] for nom in MODELES}
    for t in origines:
        train, reel = y.iloc[:t], y.iloc[t:t + h].values
        for nom, f in MODELES.items():
            res[nom].append(f(train, h) - reel)
    return {nom: np.array(e) for nom, e in res.items()}, origines


def prevoir(y: pd.Series, h=HORIZON):
    """y : série mensuelle d'EVP (index MS, sans trou). Renvoie un dictionnaire prêt à être affiché."""
    if y.isna().any():
        trous = ", ".join(d.strftime("%Y-%m") for d in y.index[y.isna()][:4])
        return {"ok": False, "raison": f"mois manquants dans la série ({trous}…) : la saisonnalité serait faussée, prévision suspendue"}
    y = y.dropna()
    if len(y) < 40:
        return {"ok": False, "raison": f"historique trop court ({len(y)} mois) pour une prévision saisonnière"}
    erreurs, origines = backtest(y, h)
    table = []
    for nom, e in erreurs.items():
        ae = np.abs(e)
        reel_moyen = float(y.iloc[origines[0]:].mean())
        table.append({"modele": nom, "mae": float(ae.mean()), "wape": float(ae.mean() / reel_moyen), "wape_pct": float(ae.mean() / reel_moyen * 100),
                      "mae_par_horizon": [float(x) for x in ae.mean(axis=0)]})
    meilleur = min(table, key=lambda t: t["mae"])
    naif = next(t for t in table if t["modele"].startswith("Naïf"))
    f = MODELES[meilleur["modele"]](y, h)
    e_best = np.abs(erreurs[meilleur["modele"]])
    mae_h = e_best.mean(axis=0)
    p80_h = np.quantile(e_best, 0.8, axis=0)
    dans_bande = float(np.mean(e_best <= mae_h))  # part des erreurs passées couvertes par « ± MAE »
    mois = pd.date_range(y.index[-1] + pd.offsets.MonthBegin(1), periods=h, freq="MS")
    prevision = []
    for k in range(h):
        ref = float(y.loc[mois[k] - pd.DateOffset(years=1)]) if (mois[k] - pd.DateOffset(years=1)) in y.index else None
        prevision.append({"mois": mois[k].strftime("%Y-%m"), "valeur": float(f[k]), "bas": float(f[k] - mae_h[k]),
                          "haut": float(f[k] + mae_h[k]), "bas80": float(f[k] - p80_h[k]), "haut80": float(f[k] + p80_h[k]),
                          "mae": float(mae_h[k]), "annee_precedente": ref,
                          "ecart_annee_prec_pct": (float(f[k] / ref - 1) * 100 if ref else None)})
    # contrôle de vraisemblance : une prévision négative ou hors de [30 %, 300 %] du dernier niveau est refusée
    niveau = float(y.iloc[-12:].mean())
    if any(p["valeur"] < 0.3 * niveau or p["valeur"] > 3 * niveau for p in prevision):
        return {"ok": False, "raison": "prévision invraisemblable : affichage suspendu par sécurité"}
    return {
        "ok": True, "modele": meilleur["modele"], "horizon": h, "n_origines": len(origines),
        "backtest": sorted(table, key=lambda t: t["mae"]),
        "gain_vs_naif_pct": float((1 - meilleur["mae"] / naif["mae"]) * 100),
        "couverture_mae": dans_bande,
        "historique": [{"mois": d.strftime("%Y-%m"), "valeur": float(v)} for d, v in y.items()],
        "prevision": prevision,
        "dernier_mois": y.index[-1].strftime("%Y-%m"),
    }
