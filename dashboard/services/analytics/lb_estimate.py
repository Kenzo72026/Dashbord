"""Long Beach : EVP observés (BTS, jusqu'en août 2023) puis ESTIMATION à partir des tonnes de conteneurs du complexe (PortWatch).

Principe. Le rapport « tonnes de conteneurs du complexe (PortWatch) / EVP du complexe (Los Angeles + Long Beach) » est stable
(≈ 7,5 à 8,0 t/EVP). Sur la période où Long Beach est observé (2019-01 → 2023-08), on mesure ce rapport mois par mois. Après
août 2023, on l'interpole entre sa valeur des 12 derniers mois observés et celle des mois d'ancrage de 2026, puis :

    EVP du complexe estimés = tonnes PortWatch / rapport ;   EVP de Long Beach estimés = EVP du complexe − EVP de Los Angeles (publiés).

Honnêteté sur la fiabilité. C'est une ESTIMATION, jamais présentée comme une donnée du port :
  * le rétro-test (rapport des 12 mois précédents, appliqué aux 1 à 12 mois suivants, sur 2021-2023) donne l'erreur moyenne du
    complexe, utilisée pour la bande d'incertitude ;
  * trois mois de 2026 (janvier, juin, juillet) sont laissés de côté pour contrôler l'estimation ;
  * les erreurs sur Long Beach sont environ le double de celles du complexe, car Long Beach n'est qu'une moitié du complexe.

Chiffres de 2026 (totaux mensuels de Long Beach publiés par le port dans ses communiqués, repris par la presse spécialisée :
Cyprus Shipping News, WorldCargo News, DataPortuaria, Seatrade Maritime). Août et septembre 2026 sont confirmés par une seconde source
(page MacroMicro consultée par l'étudiant le 19/11/2026 : 997 177 en septembre, 919 992 en août).
"""
import numpy as np
import pandas as pd

ANCRES = {"2026-08": 919_992, "2026-09": 997_177}                     # servent à caler le rapport (deux sources concordantes)
CONTROLES = {"2026-01": 847_765, "2026-06": 779_331, "2026-07": 928_508}  # laissés de côté : servent uniquement à contrôler
SOURCE_2026 = ("communiqués mensuels du Port of Long Beach repris par la presse (Cyprus Shipping News, WorldCargo News, DataPortuaria) ; "
               "août et septembre 2026 confirmés par MacroMicro")
MIN_MOIS_RETRO = 24


def _rapport(tonnes, la, lb):
    com = lb.index.intersection(la.index).intersection(tonnes.index)
    cx = (lb + la).loc[com]
    return com, cx, tonnes.loc[com] / cx


def retro_test(tonnes, la, lb) -> dict:
    """Erreur moyenne du complexe quand on applique le rapport des 12 mois précédents aux 1 à 12 mois suivants."""
    com, cx, ratio = _rapport(tonnes, la, lb)
    if len(com) < MIN_MOIS_RETRO + 12:
        return {"ok": False}
    erreurs = []
    for i in range(MIN_MOIS_RETRO, len(com) - 1):
        r = ratio.iloc[i - 12:i].mean()
        for k in range(0, min(12, len(com) - i)):
            erreurs.append(abs(tonnes.loc[com[i + k]] / r - cx.iloc[i + k]) / cx.iloc[i + k])
    return {"ok": True, "mape": float(np.mean(erreurs)), "n": len(erreurs)}


def estimer(lb_obs: pd.Series, la: pd.Series, tonnes: pd.Series, ancres=None, controles=None) -> dict:
    """lb_obs, la, tonnes : séries mensuelles (index = premier jour du mois). Renvoie un dictionnaire prêt pour l'affichage."""
    ancres = ANCRES if ancres is None else ancres
    controles = CONTROLES if controles is None else controles
    com, cx_obs, ratio_obs = _rapport(tonnes, la, lb_obs)
    if len(com) < 36:
        return {"ok": False, "raison": f"seulement {len(com)} mois communs Long Beach / Los Angeles / PortWatch : calibration impossible"}
    rt = retro_test(tonnes, la, lb_obs)
    mape = rt["mape"] if rt["ok"] else 0.05
    # points de calibration du rapport : moyenne des 12 derniers mois observés + mois d'ancrage
    dernier12 = ratio_obs.iloc[-12:]
    xs = [float(dernier12.index.to_series().map(pd.Timestamp.toordinal).mean())]
    ys = [float(dernier12.mean())]
    for m, v in ancres.items():
        ts = pd.Timestamp(m + "-01")
        if ts in tonnes.index and ts in la.index:
            xs.append(float(ts.toordinal()))
            ys.append(float(tonnes[ts] / (v + la[ts])))
    ordre = np.argsort(xs)
    xs, ys = np.array(xs)[ordre], np.array(ys)[ordre]
    mois = tonnes.index[(tonnes.index > lb_obs.index.max()) & tonnes.index.isin(la.index)]
    est, bas, haut = {}, {}, {}
    for m in mois:
        r = float(np.interp(m.toordinal(), xs, ys))
        cx = float(tonnes[m] / r)
        est[m] = cx - float(la[m])
        marge = mape * cx
        bas[m], haut[m] = est[m] - marge, est[m] + marge
    controle = []
    for m, v in {**controles}.items():
        ts = pd.Timestamp(m + "-01")
        if ts in est:
            controle.append({"mois": m, "publie": v, "estime": float(est[ts]), "erreur_pct": float((est[ts] - v) / v * 100),
                             "erreur_complexe_pct": float((est[ts] - v) / (v + la[ts]) * 100)})
    fmt = lambda d: [float(d[m]) for m in mois]
    return {
        "ok": True, "mape_complexe": mape, "n_retro": rt.get("n", 0),
        "observe": {"mois": [m.strftime("%Y-%m") for m in lb_obs.index], "valeurs": [float(v) for v in lb_obs.values]},
        "estime": {"mois": [m.strftime("%Y-%m") for m in mois], "valeurs": fmt(est), "bas": fmt(bas), "haut": fmt(haut)},
        "la": {"mois": [m.strftime("%Y-%m") for m in la.index], "valeurs": [float(v) for v in la.values]},
        "communiques": {m: v for m, v in {**controles, **ancres}.items()},
        "controle": controle, "ancres": list(ancres), "source_2026": SOURCE_2026,
        "rapport": {"observe_moyen": float(ratio_obs.mean()), "observe_min": float(ratio_obs.min()), "observe_max": float(ratio_obs.max()),
                    "points": [{"mois": pd.Timestamp.fromordinal(int(x)).strftime("%Y-%m"), "valeur": float(y)} for x, y in zip(xs, ys)]},
        "complexe_dernier": {"mois": mois[-1].strftime("%Y-%m"), "evp": float(est[mois[-1]] + la[mois[-1]]), "marge_pct": float(mape * 100)} if len(mois) else None,
    }
