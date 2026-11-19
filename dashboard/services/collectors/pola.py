"""Port of Los Angeles : volumes mensuels en EVP (importations/exportations, chargés/vides) depuis 2019.

Source : pages « Historical TEU Statistics <année> » du site du port (tableaux HTML publics).
Traitement : lecture du tableau mensuel de chaque année, conversion en nombres, écriture d'un CSV propre.
"""
import io
from datetime import date

import pandas as pd
from django.utils import timezone

from ...constants import POLA_YEAR_URL
from ...models import MonthlyVolume
from ..registry import declare
from .common import PROCESSED, RAW, SourceUnavailable, http_get

MOIS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
CSV = PROCESSED / "pola_monthly_teu.csv"
COLONNES = {
    "Loaded Imports": "loaded_imports", "Empty Imports": "empty_imports",
    "Loaded Exports": "loaded_exports", "Empty Exports": "empty_exports", "Total TEUs": "total_teu",
}


def _lire_annee(html: str, annee: int) -> list[dict]:
    """Extrait les lignes mensuelles d'une page annuelle (les mois non encore publiés sont ignorés).

    Contrôle qualité : le total publié doit égaler la somme des 4 composantes (à 0,5 % près). Si le total est illisible
    (coquille à la source, ex. « 889.,748.15 » en novembre 2020), il est reconstitué par la somme des composantes et la
    ligne est marquée dans la colonne `note` ; un écart de plus de 0,5 % est refusé.
    """
    lignes = []
    for tab in pd.read_html(io.StringIO(html), header=None):
        if not (tab.astype(str) == "Loaded Imports").any().any():
            continue
        entete = tab.index[(tab.astype(str) == "Loaded Imports").any(axis=1)][0]
        noms = [str(c).strip() for c in tab.iloc[entete]]
        for _, ligne in tab.iloc[entete + 1:].iterrows():
            mois = str(ligne.iloc[0]).strip()
            if mois not in MOIS:
                continue
            rec = {"year": annee, "month": MOIS.index(mois) + 1, "note": ""}
            for nom, champ in COLONNES.items():
                v = pd.to_numeric(str(ligne.iloc[noms.index(nom)]).replace(",", ""), errors="coerce")
                rec[champ] = None if pd.isna(v) else float(v)
            composantes = [rec["loaded_imports"], rec["empty_imports"], rec["loaded_exports"], rec["empty_exports"]]
            if any(c is None for c in composantes):
                continue  # mois pas encore publié (cases vides)
            somme = float(sum(composantes))
            if not somme:
                continue
            if rec["total_teu"] is None:
                rec["total_teu"] = somme
                rec["note"] = "total illisible à la source, reconstitué par la somme des 4 composantes"
            elif abs(rec["total_teu"] - somme) > 0.005 * somme:
                raise SourceUnavailable(f"{annee}-{rec['month']:02d} : total publié {rec['total_teu']:,.0f} ≠ somme des composantes {somme:,.0f}")
            lignes.append(rec)
        break
    return lignes


def fetch():
    """Télécharge les pages 2019 → année en cours et écrit le CSV nettoyé."""
    aujourdhui = timezone.now()
    lignes = []
    for annee in range(2019, aujourdhui.year + 1):
        url = POLA_YEAR_URL.format(year=annee)
        html = http_get(url)
        (RAW / f"pola_{annee}.html").write_text(html, encoding="utf-8")  # copie brute conservée pour l'audit
        lignes += _lire_annee(html, annee)
    if not lignes:
        raise SourceUnavailable("aucun tableau mensuel lisible sur les pages du Port of Los Angeles")
    df = pd.DataFrame(lignes).sort_values(["year", "month"])
    # aucun mois ne doit manquer entre le premier et le dernier : une série à trous fausserait la saisonnalité des prévisions
    attendus = pd.period_range(f"{int(df.iloc[0].year)}-{int(df.iloc[0].month):02d}", f"{int(df.iloc[-1].year)}-{int(df.iloc[-1].month):02d}", freq="M")
    presents = pd.PeriodIndex([f"{int(r.year)}-{int(r.month):02d}" for r in df.itertuples()], freq="M")
    manquants = [str(m) for m in attendus.difference(presents)]
    if manquants:
        raise SourceUnavailable(f"mois manquants dans les pages du port : {', '.join(manquants)}")
    df.to_csv(CSV, index=False)
    return df


def load():
    """CSV nettoyé → base de données."""
    if not CSV.exists():
        raise SourceUnavailable("fichier data/processed/pola_monthly_teu.csv absent : lancer `python manage.py fetch_all`")
    df = pd.read_csv(CSV)
    MonthlyVolume.objects.filter(port="LA").delete()
    MonthlyVolume.objects.bulk_create([
        MonthlyVolume(port="LA", month=date(int(r.year), int(r.month), 1), loaded_imports=r.loaded_imports,
                      empty_imports=r.empty_imports or 0, loaded_exports=r.loaded_exports,
                      empty_exports=r.empty_exports, total_teu=r.total_teu)
        for r in df.itertuples()
    ])
    dernier = df.iloc[-1]
    corriges = df[df["note"].fillna("") != ""] if "note" in df.columns else df.iloc[0:0]
    alerte_qualite = (" Correction à la source : " + ", ".join(f"{int(r.year)}-{int(r.month):02d}" for r in corriges.itertuples())
                      + " (total illisible sur le site du port, reconstitué par la somme des 4 composantes).") if len(corriges) else ""
    declare("pola", "ok", f"{len(df)} mois chargés ({int(df.iloc[0].year)}-{int(df.iloc[0].month):02d} → "
            f"{int(dernier.year)}-{int(dernier.month):02d}).{alerte_qualite}", rows=len(df),
            last_period=f"{int(dernier.year)}-{int(dernier.month):02d}",
            notes="Valeurs publiées par le port ; le dernier mois peut être révisé. EVP = équivalent vingt pieds (TEU).",
            url=POLA_YEAR_URL.format(year=int(dernier.year)), retrieved=False)
    return len(df)


def refresh():
    try:
        fetch()
        declare("pola", "ok", "téléchargement réussi", retrieved=True)
    except SourceUnavailable as exc:
        declare("pola", "error", f"Source injoignable ({exc}) : dernières données conservées.", retrieved=False)
    return load()
