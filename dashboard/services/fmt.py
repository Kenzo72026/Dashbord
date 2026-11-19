"""Mise en forme à la française (espaces pour les milliers, virgule décimale, mois en toutes lettres)."""
import math

MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
FIN_ESPACE = " "  # espace fine insécable


def nb(x, d=0):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "—"
    s = f"{x:,.{d}f}".replace(",", FIN_ESPACE).replace(".", ",")
    return s


def signe_pct(x, d=1):
    if x is None:
        return "—"
    return f"{'+' if x > 0 else '−' if x < 0 else ''}{nb(abs(x), d)} %"


def mois_fr(yyyy_mm):
    """'2026-10' → 'oct. 2026'."""
    a, m = str(yyyy_mm)[:7].split("-")
    return f"{MOIS[int(m) - 1]} {a}"


def date_fr(dt):
    return dt.strftime("%d/%m/%Y") if dt else "—"


def rang(n):
    return f"{n}ᵉ" if n != 1 else "1ᵉʳ"
