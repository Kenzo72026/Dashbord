"""Écoute le flux AIS en direct (aisstream.io).

  python manage.py collect_ais                    # une écoute de 45 s
  python manage.py collect_ais --loop --every 300 # en continu : écoute 45 s toutes les 5 minutes (à laisser tourner)

Planification Windows : tâche planifiée toutes les 5 minutes avec `python manage.py collect_ais`.
La clé est lue dans AISSTREAM_API_KEY (variable d'environnement ou .env) : elle n'est jamais écrite dans le code.
"""
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from dashboard.services.collectors import ais


class Command(BaseCommand):
    help = "Collecte les positions AIS autour du port de Los Angeles / Long Beach."

    def add_arguments(self, parser):
        parser.add_argument("--seconds", type=int, default=45, help="durée d'écoute")
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--every", type=int, default=300, help="pause entre deux écoutes (avec --loop)")

    def handle(self, *args, **opts):
        if not settings.AISSTREAM_API_KEY:
            ais.collect_live()  # enregistre l'état « indisponible » avec son message
            self.stdout.write(self.style.WARNING(ais.MESSAGE_SANS_CLE))
            return
        from dashboard.services.analytics.insights import compute_live
        while True:
            n = ais.collect_live(opts["seconds"])
            compute_live()
            self.stdout.write(self.style.SUCCESS(f"AIS : {n} navires reçus."))
            if not opts["loop"]:
                break
            time.sleep(opts["every"])
