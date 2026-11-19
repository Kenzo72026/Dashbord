"""Télécharge (ou recharge hors ligne) toutes les sources statiques, puis recalcule les analyses.

  python manage.py fetch_all             # télécharge pola, cppi, unctad, portwatch + météo, recharge polb/ais, recalcule
  python manage.py fetch_all --offline   # ne télécharge rien : recharge les CSV déjà présents dans data/processed
  python manage.py fetch_all --only cppi # une seule source
"""
from django.core.management.base import BaseCommand

from dashboard.services.collectors import ais, bts, cppi, pola, polb, portwatch, unctad, weather
from dashboard.services.collectors.common import SourceUnavailable

ETAPES = ["pola", "polb", "bts", "cppi", "unctad", "portwatch", "weather", "ais_archive", "ais_live"]


class Command(BaseCommand):
    help = "Récupère les données sources, les charge en base et recalcule les analyses."

    def add_arguments(self, parser):
        parser.add_argument("--offline", action="store_true", help="recharge uniquement les CSV de data/processed")
        parser.add_argument("--only", choices=ETAPES, help="limiter à une source")
        parser.add_argument("--no-insights", action="store_true", help="ne pas recalculer les prévisions/alertes")

    def handle(self, *args, **opts):
        hors_ligne = opts["offline"]
        actions = {
            "pola": pola.load if hors_ligne else pola.refresh,
            "polb": polb.load,
            "bts": bts.load if hors_ligne else bts.refresh,
            "cppi": cppi.load if hors_ligne else cppi.refresh,
            "unctad": unctad.load if hors_ligne else unctad.refresh,
            "portwatch": portwatch.load if hors_ligne else portwatch.refresh,
            "weather": (lambda: weather.refresh(force=True)) if not hors_ligne else (lambda: 0),
            "ais_archive": ais.load_archive,
            "ais_live": (lambda: ais.collect_live(20)) if not hors_ligne else (lambda: 0),  # sans clé : enregistre « indisponible » + message
        }
        for cle in ([opts["only"]] if opts["only"] else ETAPES):
            try:
                n = actions[cle]()
                self.stdout.write(self.style.SUCCESS(f"[{cle}] {n} lignes"))
            except SourceUnavailable as exc:
                self.stdout.write(self.style.WARNING(f"[{cle}] indisponible : {exc}"))
        if not opts["no_insights"]:
            from dashboard.services.analytics.insights import compute_all
            compute_all()
            self.stdout.write(self.style.SUCCESS("[insights] prévisions, anomalies, alertes et recommandations recalculées"))
