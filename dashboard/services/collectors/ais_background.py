"""Collecte AIS en tâche de fond DANS le processus web.

Sur un hébergement gratuit (Render), on ne peut pas lancer un second processus `collect_ais --loop`.
Si AIS_AUTOSTART=1 et si la clé AISSTREAM_API_KEY est définie, le serveur démarre un fil qui écoute le flux
45 s toutes les ~5 minutes, comme la commande. En local, on garde la commande `collect_ais` (rien ne démarre seul).
Le fil s'arrête avec le processus ; quand l'hébergeur met le service en veille, la collecte attend le réveil.
"""
import logging
import threading
import time

from django.db import close_old_connections

journal = logging.getLogger(__name__)
_verrou = threading.Lock()
_lance = False


def _boucle(ecoute: int, pause: int) -> None:
    from dashboard.services.analytics.insights import compute_live
    from dashboard.services.collectors import ais

    time.sleep(20)  # laisse le serveur finir de démarrer
    while True:
        try:
            close_old_connections()
            n = ais.collect_live(ecoute)
            compute_live()
            journal.info("AIS : %s navires reçus", n)
        except Exception:  # une erreur ne doit jamais arrêter la collecte
            journal.exception("collecte AIS")
        finally:
            close_old_connections()
        time.sleep(pause)


def demarrer(ecoute: int = 45, pause: int = 255) -> bool:
    """Démarre le fil une seule fois par processus. Retourne False s'il tournait déjà."""
    global _lance
    with _verrou:
        if _lance:
            return False
        _lance = True
    threading.Thread(target=_boucle, args=(ecoute, pause), daemon=True, name="ais-collecte").start()
    return True
