"""Filtres de gabarit : JSON pour les mini-courbes, dates et nombres à la française."""
import json
from datetime import datetime

from django import template

from ..services import fmt

register = template.Library()


@register.filter
def tojson(valeur):
    return json.dumps(valeur, ensure_ascii=False)


@register.filter
def frdate(iso):
    """'2026-11-18T20:15:00+00:00' → '18/11/2026 20:15 UTC'."""
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d/%m/%Y %H:%M UTC")
    except ValueError:
        return str(iso)


@register.filter
def frjour(iso):
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(str(iso)).strftime("%d/%m/%Y")
    except ValueError:
        return str(iso)


@register.filter
def nbfr(x, d=0):
    return fmt.nb(x, int(d))


@register.filter
def moisfr(x):
    return fmt.mois_fr(x)


@register.filter
def get(d, cle):
    return d.get(cle) if isinstance(d, dict) else None
