import os
import sys

from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dashboard"
    verbose_name = "San Pedro Bay · tableau de bord portuaire"

    def ready(self):
        """Ouvre le lien permanent avec le flux AIS dès que le serveur démarre, si une clé existe (AIS_AUTOSTART=0 pour l'empêcher)."""
        if not os.environ.get("AISSTREAM_API_KEY") or os.environ.get("AIS_AUTOSTART") == "0":
            return
        argv = sys.argv or [""]
        # jamais pendant les commandes de gestion (tests, migrate, collectstatic…) : seulement sous un serveur
        if argv[0].endswith("manage.py") and (len(argv) < 2 or argv[1] != "runserver"):
            return
        # runserver lance deux processus (surveillant + serveur) : on n'ouvre la connexion que dans le serveur
        if argv[0].endswith("manage.py") and "--noreload" not in argv and os.environ.get("RUN_MAIN") != "true":
            return
        if argv[0].endswith("gunicorn") or "gunicorn" in argv[0]:
            return  # sous gunicorn, le lien s'ouvre à la première page, dans le processus de travail (voir ais_stream.assurer)
        from dashboard.services.collectors import ais_stream
        ais_stream.demarrer()
