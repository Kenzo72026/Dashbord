"""Lien PERMANENT avec le flux AIS en direct d'aisstream.io, côté serveur.

Pourquoi côté serveur : la clé est secrète (une clé écrite dans une page web est publique) et aisstream.io interdit les
connexions directes depuis un navigateur. Le serveur garde donc la connexion WebSocket ouverte, tient en mémoire la dernière
position de chaque navire, et la diffuse aux navigateurs en continu (voir `views.api_ais_stream`, Server-Sent Events).

Une copie est écrite en base toutes les 20 s (indicateurs de l'accueil, reprise après un redémarrage, instantané statique).
La connexion se rétablit seule après une coupure (attente 3 s, puis jusqu'à 60 s).
"""
import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone as tz

from django.conf import settings
from django.db import close_old_connections

from ...constants import AIS_BBOX, AISSTREAM_WS, type_group
from ..registry import declare
from . import ais

journal = logging.getLogger(__name__)

FENETRE_MIN = 30           # un navire est « en direct » s'il a émis dans les 30 dernières minutes
PERSISTER_TOUTES_S = 20    # copie en base
CALCULER_TOUTES_S = 60     # indicateurs de l'accueil (lisent la base)
SILENCE_MAX_S = 120        # aucun message pendant 2 minutes : on se reconnecte
CONSERVER_H = 6


class FluxAis:
    """Connexion permanente + mémoire des dernières positions. Une seule instance par processus (voir `flux`)."""

    def __init__(self):
        self.verrou = threading.Lock()
        self.positions, self.statiques = {}, {}
        self.connectee = False
        self.depuis = None            # début de la connexion en cours
        self.dernier_message = None   # heure de réception du dernier message
        self.nb_messages = 0
        self.erreur = ""
        self.version = 0              # change à chaque message : les diffuseurs n'envoient que s'il y a du nouveau
        self._lance = False

    # ------------------------------------------------------------ réception
    def recevoir(self, msg):
        """Traite un message déjà décodé (fonction testable sans réseau)."""
        with self.verrou:
            ais.traiter_message(msg, self.positions, self.statiques)
            self.nb_messages += 1
            self.dernier_message = datetime.now(tz.utc)
            self.version += 1

    def liste(self, fenetre_min=FENETRE_MIN):
        """Navires émis dans la fenêtre, avec leurs données statiques (type, longueur) : liste de dictionnaires."""
        limite = datetime.now(tz.utc) - timedelta(minutes=fenetre_min)
        with self.verrou:
            copie = [(m, dict(p), dict(self.statiques.get(m, {}))) for m, p in self.positions.items() if p["seen_at"] >= limite]
        sortie = []
        for mmsi, p, s in copie:
            sortie.append({"mmsi": mmsi, "name": p["name"] or s.get("name", ""), "lat": p["lat"], "lon": p["lon"], "sog": p["sog"], "cog": p["cog"],
                           "nav_status": p["nav_status"], "ship_type": s.get("ship_type"), "type_group": type_group(s.get("ship_type")),
                           "length": s.get("length"), "seen_at": p["seen_at"]})
        return sortie

    def etat(self):
        """Résumé de la connexion pour l'affichage (« connecté, N messages, dernier il y a … »)."""
        return {"active": self._lance, "connectee": self.connectee, "messages": self.nb_messages, "erreur": self.erreur,
                "depuis": self.depuis.isoformat() if self.depuis else None,
                "dernier_message": self.dernier_message.isoformat() if self.dernier_message else None}

    # ------------------------------------------------------------ connexion
    async def _ecouter(self):
        import websockets
        async with websockets.connect(AISSTREAM_WS, open_timeout=15, max_size=2 ** 22, ping_interval=20) as ws:
            # l'abonnement doit partir dans les 3 secondes suivant la connexion
            await ws.send(json.dumps({"APIKey": settings.AISSTREAM_API_KEY, "BoundingBoxes": [AIS_BBOX],
                                      "FilterMessageTypes": ["PositionReport", "ShipStaticData"]}))
            self.connectee, self.erreur, self.depuis = True, "", datetime.now(tz.utc)
            boucle = asyncio.get_running_loop()
            await boucle.run_in_executor(None, self._persister, False)  # l'état « OK » s'affiche tout de suite, sans attendre la prochaine copie
            derniere_copie = derniere_analyse = boucle.time()
            while True:
                brut = await asyncio.wait_for(ws.recv(), timeout=SILENCE_MAX_S)
                msg = json.loads(brut)
                if "error" in msg:
                    raise RuntimeError(f"aisstream a refusé la connexion : {msg['error']}")
                self.recevoir(msg)
                maintenant = boucle.time()
                if maintenant - derniere_copie >= PERSISTER_TOUTES_S:
                    derniere_copie = maintenant
                    analyser = maintenant - derniere_analyse >= CALCULER_TOUTES_S
                    if analyser:
                        derniere_analyse = maintenant
                    await boucle.run_in_executor(None, self._persister, analyser)

    def _persister(self, analyser):
        """Copie en base (dans un fil à part : l'ORM Django est synchrone)."""
        try:
            close_old_connections()
            with self.verrou:
                limite = datetime.now(tz.utc) - timedelta(hours=CONSERVER_H)
                self.positions = {m: p for m, p in self.positions.items() if p["seen_at"] >= limite}
                positions, statiques = dict(self.positions), dict(self.statiques)
            ais.enregistrer(positions, statiques, "Flux permanent connecté : {total} navires suivis (positions < 6 h).")
            if analyser:
                from ..analytics.insights import compute_live
                compute_live()
        except Exception:
            journal.exception("copie AIS en base")
        finally:
            close_old_connections()

    async def _boucle(self):
        attente = 3
        while True:
            try:
                await self._ecouter()
            except Exception as exc:  # coupure, quota, clé refusée… : on le dit et on se reconnecte
                self.connectee = False
                self.erreur = f"{type(exc).__name__} : {exc}"[:200]
                journal.warning("flux AIS interrompu (%s) ; nouvelle tentative dans %s s", self.erreur, attente)
                try:
                    await asyncio.get_running_loop().run_in_executor(None, self._declarer_erreur)
                except Exception:
                    pass
            else:
                attente = 3
            await asyncio.sleep(attente)
            attente = min(attente * 2, 60)

    def _declarer_erreur(self):
        try:
            close_old_connections()
            declare("ais_live", "error", f"Flux AIS interrompu ({self.erreur}) : reconnexion automatique, dernières positions conservées.", retrieved=False)
        finally:
            close_old_connections()

    def _precharger(self):
        """Au démarrage : reprend les dernières positions enregistrées en base (< 30 min), pour ne pas repartir d'une carte vide."""
        try:
            from ...models import AisPosition
            limite = datetime.now(tz.utc) - timedelta(minutes=FENETRE_MIN)
            with self.verrou:
                for r in AisPosition.objects.filter(origin="live", seen_at__gte=limite):
                    self.positions[r.mmsi] = {"name": r.name, "lat": r.lat, "lon": r.lon, "sog": r.sog, "cog": r.cog,
                                              "nav_status": r.nav_status, "seen_at": r.seen_at}
                    self.statiques[r.mmsi] = {"ship_type": r.ship_type, "length": r.length, "name": r.name}
                self.version += 1
        except Exception:
            journal.exception("préchargement AIS")
        finally:
            close_old_connections()

    def _fil(self):
        self._precharger()
        asyncio.run(self._boucle())

    def demarrer(self):
        """Ouvre la connexion dans un fil de fond (une seule fois par processus). Retourne False si elle tournait déjà."""
        with self.verrou:
            if self._lance:
                return False
            self._lance = True
        threading.Thread(target=self._fil, daemon=True, name="ais-flux").start()
        return True


flux = FluxAis()


def demarrer():
    return flux.demarrer()
