"""Construit l'archive AIS (dernier jour + référence horaire) à partir du gros fichier AIS du TP."""
from django.core.management.base import BaseCommand, CommandError

from dashboard.services.collectors import ais


class Command(BaseCommand):
    help = "python manage.py build_ais_archive <chemin vers ais_clean.csv>"

    def add_arguments(self, parser):
        parser.add_argument("source_csv")

    def handle(self, *args, **opts):
        try:
            navires, jours = ais.build_archive(opts["source_csv"])
        except (OSError, ValueError, KeyError) as exc:
            raise CommandError(f"lecture impossible : {exc}")
        n = ais.load_archive()
        self.stdout.write(self.style.SUCCESS(f"Archive : {navires} navires, référence horaire sur {jours} jours, {n} lignes en base."))
