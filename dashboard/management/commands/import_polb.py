"""Importe le fichier mensuel de Long Beach téléchargé manuellement depuis polb.com (voir README, étape 2)."""
from django.core.management.base import BaseCommand, CommandError

from dashboard.services.collectors import polb
from dashboard.services.collectors.common import SourceUnavailable


class Command(BaseCommand):
    help = "Importe data/raw/polb_teu_monthly.csv (ou .xlsx), le charge en base et recalcule les analyses."

    def handle(self, *args, **opts):
        try:
            df = polb.import_fichier()
        except SourceUnavailable as exc:
            raise CommandError(str(exc))
        n = polb.load()
        self.stdout.write(self.style.SUCCESS(f"Long Beach : {n} mois importés ({int(df.iloc[0].year)}-{int(df.iloc[0].month):02d} → "
                                             f"{int(df.iloc[-1].year)}-{int(df.iloc[-1].month):02d})."))
        from dashboard.services.analytics.insights import compute_all
        compute_all()
        self.stdout.write(self.style.SUCCESS("Analyses recalculées."))
