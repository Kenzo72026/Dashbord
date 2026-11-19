"""Actualise la météo (respecte la durée de validité sauf avec --force) puis recalcule alertes et recommandations."""
from django.core.management.base import BaseCommand

from dashboard.services.collectors import weather


class Command(BaseCommand):
    help = "Récupère la météo Open-Meteo (vent, rafales, vagues) si les données ont expiré."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **opts):
        n = weather.refresh(force=opts["force"])
        from dashboard.services.analytics.insights import compute_live
        compute_live()
        self.stdout.write(self.style.SUCCESS(f"Météo : {n} points en base ; alertes recalculées."))
