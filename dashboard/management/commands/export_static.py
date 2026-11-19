"""Exporte un instantané statique du tableau de bord (HTML autonome) dans docs/export/.

  python manage.py export_static

Utile pour consulter ou rendre le tableau de bord sans installer Python : ouvrir docs/export/index.html dans un navigateur.
C'est une PHOTO du moment de l'export (date affichée en pied de page) : le bouton « Actualiser » et le direct ne fonctionnent
que dans l'application Django. Les graphiques et la carte (Leaflet) sont embarqués ; seuls le fond de carte et les polices
nécessitent Internet.
"""
import re
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import Client

PAGES = {"/": "index.html", "/volumes/": "volumes.html", "/monde/": "monde.html", "/direct/": "direct.html",
         "/decision/": "decision.html", "/sources/": "sources.html", "/fiche/": "fiche.html"}


class Command(BaseCommand):
    help = "Écrit un instantané HTML statique dans docs/export/."

    def handle(self, *args, **opts):
        sortie = settings.BASE_DIR / "docs" / "export"
        if sortie.exists():
            shutil.rmtree(sortie)
        shutil.copytree(settings.BASE_DIR / "dashboard" / "static" / "dashboard", sortie / "static" / "dashboard")
        client = Client(HTTP_HOST="localhost")
        cle_ais, settings.AISSTREAM_API_KEY = settings.AISSTREAM_API_KEY, ""  # la photo ne se connecte à rien : elle ne doit pas promettre un direct
        for url, fichier in PAGES.items():
            html = client.get(url).content.decode("utf-8")
            html = html.replace('href="/static/', 'href="static/').replace('src="/static/', 'src="static/')
            for u, f in PAGES.items():
                html = html.replace(f'href="{u}"', f'href="{f}"')
            html = html.replace("<body>", '<body data-export="1">', 1)
            (sortie / fichier).write_text(html, encoding="utf-8")
            self.stdout.write(f"  {fichier}  ({len(html) // 1024} Ko)")
        settings.AISSTREAM_API_KEY = cle_ais
        self.stdout.write(self.style.SUCCESS(f"Instantané écrit dans {sortie} : ouvrir index.html"))
