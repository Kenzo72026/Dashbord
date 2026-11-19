import os
import sys

from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dashboard"
    verbose_name = "San Pedro Bay · tableau de bord portuaire"

    def ready(self):
        """Démarre la collecte AIS en tâche de fond seulement si on le demande (AIS_AUTOSTART=1) et si la clé existe."""
        if os.environ.get("AIS_AUTOSTART") != "1" or not os.environ.get("AISSTREAM_API_KEY"):
            return
        # jamais pendant les commandes de gestion (tests, migrate, collectstatic…) : seulement sous un serveur
        if sys.argv and sys.argv[0].endswith("manage.py") and (len(sys.argv) < 2 or sys.argv[1] != "runserver"):
            return
        from dashboard.services.collectors import ais_background
        ais_background.demarrer()
