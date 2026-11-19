"""Outils communs aux collecteurs : accès HTTP prudent (délai, nouvelles tentatives) et chemins de données."""
import time

import requests
from django.conf import settings

from ...constants import USER_AGENT

RAW = settings.DATA_DIR / "raw"
PROCESSED = settings.DATA_DIR / "processed"


class SourceUnavailable(Exception):
    """La source ne répond pas ou renvoie un contenu inattendu. Le message est affiché à l'utilisateur."""


def http_get(url, params=None, timeout=45, tries=3, binary=False):
    """GET avec 3 tentatives. Identifie clairement le client (projet universitaire) et n'imite aucun navigateur."""
    derniere = None
    for essai in range(tries):
        try:
            r = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            if r.status_code == 200:
                return r.content if binary else r.text
            derniere = f"HTTP {r.status_code}"
            if r.status_code in (401, 403, 404):  # inutile de réessayer
                break
        except requests.RequestException as exc:
            derniere = type(exc).__name__
        time.sleep(1.5 * (essai + 1))
    raise SourceUnavailable(f"{url} : {derniere}")
