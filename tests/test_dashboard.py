"""Tests du tableau de bord : python manage.py test tests

Les messages AIS et le CSV de Long Beach ci-dessous sont des JEUX D'ESSAI écrits d'après la documentation des fournisseurs
(le flux aisstream a été écouté en direct le 19/11/2026 : 23 navires en 75 s ; polb.com refuse les téléchargements automatiques).
Ils ne sont jamais chargés dans la base du tableau de bord.
"""
import os
import re
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
from django.apps import apps
from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from dashboard.models import AisPosition, DataSource, MonthlyVolume, PortCallDaily, WeatherPoint
from dashboard.services.analytics import alerts, anomalies, forecast, lb_estimate
from dashboard.services.collectors import ais, bts, pola, polb
from dashboard.services.collectors.common import SourceUnavailable

PAGES = ["/", "/volumes/", "/monde/", "/direct/", "/decision/", "/sources/", "/fiche/"]


def serie_saisonniere(n=84, bruit=0.02, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2019-01-01", periods=n, freq="MS")
    t = np.arange(n)
    return pd.Series(800_000 * (1 + 0.002 * t) * (1 + 0.08 * np.sin(2 * np.pi * t / 12)) * (1 + bruit * rng.standard_normal(n)), index=idx)


class PagesAvecBaseVide(TestCase):
    """Chaque page doit s'afficher même si aucune source n'a été chargée (message clair, pas d'erreur 500)."""

    def test_toutes_les_pages_repondent(self):
        for url in PAGES:
            with self.subTest(url=url):
                r = self.client.get(url, HTTP_HOST="localhost")
                self.assertEqual(r.status_code, 200, url)

    def test_api_live_sans_donnees(self):
        r = self.client.get("/api/live/", HTTP_HOST="localhost")
        self.assertEqual(r.status_code, 200)
        self.assertIn("direct", r.json())

    def test_refresh_refuse_get(self):
        self.assertEqual(self.client.get("/api/refresh/", HTTP_HOST="localhost").status_code, 405)


class Prevision(TestCase):
    def test_prevision_coherente(self):
        res = forecast.prevoir(serie_saisonniere())
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["prevision"]), 6)
        for p in res["prevision"]:
            self.assertLess(p["bas80"], p["bas"])
            self.assertLess(p["bas"], p["valeur"])
            self.assertLess(p["valeur"], p["haut"])
            self.assertLess(p["haut"], p["haut80"])
            self.assertGreater(p["mae"], 0)
        # sur une série saisonnière régulière, le modèle retenu bat le « même mois l'an dernier »
        self.assertGreater(res["gain_vs_naif_pct"], 0)

    def test_historique_trop_court_refuse(self):
        res = forecast.prevoir(serie_saisonniere(n=30))
        self.assertFalse(res["ok"])
        self.assertIn("trop court", res["raison"])


class Anomalies(TestCase):
    def test_choc_detecte(self):
        s = serie_saisonniere(bruit=0.01)
        s.iloc[50] *= 0.6  # -40 % un mois donné
        df = pd.DataFrame({"total_teu": s, "loaded_imports": s * .5, "empty_imports": s * .01, "loaded_exports": s * .1, "empty_exports": s * .39})
        res = anomalies.anomalies_mensuelles(df)
        self.assertTrue(res["ok"])
        mois = {a["mois"] for a in res["anomalies"]}
        self.assertIn(s.index[50].strftime("%Y-%m"), mois)
        self.assertLess(len(mois), 6, "trop de fausses alertes sur une série presque propre")

    def test_hebdo_pic_detecte(self):
        idx = pd.date_range("2024-01-01", periods=80, freq="W-MON")
        s = pd.Series(40 + np.random.default_rng(2).normal(0, 1.5, 80), index=idx)
        s.iloc[-1] = 70
        res = anomalies.anomalies_hebdo(s)
        self.assertTrue(res["ok"])
        self.assertGreaterEqual(res["derniere"]["z"], 3)


class AlertesMeteo(TestCase):
    def _points(self, rafales):
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        WeatherPoint.objects.bulk_create([
            WeatherPoint(time=now + timedelta(hours=h), wind_kn=10, gust_kn=g, wave_m=1.0, visibility_m=20000, fetched_at=now)
            for h, g in enumerate(rafales)] + [WeatherPoint(time=now, is_current=True, wind_kn=10, gust_kn=rafales[0], wave_m=1.0, fetched_at=now)])

    def test_un_episode_une_alerte(self):
        # 5 heures consécutives de rafales à 36 nœuds = UNE alerte (pas cinq)
        self._points([12, 14, 36, 36, 37, 36, 36, 15, 12] + [12] * 40)
        res = alerts.alertes_meteo()
        rafales = [a for a in res["alertes"] if a["variable"] == "rafales"]
        self.assertEqual(len(rafales), 1)
        self.assertEqual(rafales[0]["niveau"], "alerte")
        self.assertEqual(rafales[0]["pic"], 37.0)
        self.assertEqual(res["niveau"], "alerte")

    def test_calme_aucune_alerte(self):
        self._points([10] * 49)
        res = alerts.alertes_meteo()
        self.assertEqual(res["niveau"], "ok")
        self.assertEqual(res["alertes"], [])

    def test_sans_meteo_message_clair(self):
        res = alerts.alertes_meteo()
        self.assertFalse(res["disponible"])
        self.assertIn("indisponibles", res["message"])


class AisMessages(TestCase):
    POS = {"MessageType": "PositionReport",
           "MetaData": {"MMSI": 366999001, "ShipName": "TEST VESSEL  ", "latitude": 33.71, "longitude": -118.25, "time_utc": "2026-11-18 20:01:02.123456 +0000 UTC"},
           "Message": {"PositionReport": {"Sog": 0.1, "Cog": 87.2, "NavigationalStatus": 1}}}
    STAT = {"MessageType": "ShipStaticData", "MetaData": {"MMSI": 366999001, "ShipName": "TEST VESSEL"},
            "Message": {"ShipStaticData": {"Type": 70, "Name": "TEST VESSEL", "Dimension": {"A": 250, "B": 60, "C": 20, "D": 22}}}}

    def test_position_et_statique(self):
        pos, stat = {}, {}
        ais.traiter_message(self.POS, pos, stat)
        ais.traiter_message(self.STAT, pos, stat)
        p = pos["366999001"]
        self.assertEqual((p["lat"], p["lon"], p["nav_status"]), (33.71, -118.25, 1))
        self.assertEqual(p["name"], "TEST VESSEL")
        self.assertEqual(stat["366999001"]["ship_type"], 70)
        self.assertEqual(stat["366999001"]["length"], 310)

    def test_message_invalide_ignore(self):
        pos, stat = {}, {}
        ais.traiter_message({"MessageType": "PositionReport", "MetaData": {"MMSI": 123}}, pos, stat)
        ais.traiter_message({"MessageType": "PositionReport", "MetaData": {"MMSI": 366999002}, "Message": {"PositionReport": {}}}, pos, stat)
        self.assertEqual(pos, {})

    def test_sans_cle_message_actionnable(self):
        with self.settings(AISSTREAM_API_KEY=""):
            self.assertEqual(ais.collect_live(1), 0)
        src = DataSource.objects.get(key="ais_live")
        self.assertEqual(src.status, "missing")
        self.assertIn("AISSTREAM_API_KEY", src.message)


class LongBeach(TestCase):
    def _fichier(self, contenu, suffixe=".csv"):
        d = tempfile.mkdtemp()
        p = Path(d) / f"polb{suffixe}"
        p.write_text(contenu, encoding="utf-8")
        return p

    def test_import_colonnes_variees(self):
        p = self._fichier("Date,Loaded Inbound,Loaded Outbound,Empty Inbound,Empty Outbound,Total\n"
                          "JANUARY 2019,500000,150000,20000,230000,900000\nFEBRUARY 2019,400000,140000,15000,200000,755000\n"
                          "MARCH 2018,1,1,1,1,4\n")
        df = polb.parse_fichier(p)
        self.assertEqual(len(df), 2)  # 2018 écarté (avant 2019)
        self.assertEqual(df.iloc[0].total_teu, 900000)

    def test_total_incoherent_refuse(self):
        p = self._fichier("Date,Loaded Inbound,Loaded Outbound,Empty Inbound,Empty Outbound,Total\nJANUARY 2019,500000,150000,20000,230000,999999\n")
        with self.assertRaises(SourceUnavailable):
            polb.parse_fichier(p)

    def test_colonne_manquante_explicite(self):
        p = self._fichier("Date,Loaded Inbound,Total\nJANUARY 2019,1,1\n")
        with self.assertRaisesMessage(SourceUnavailable, "colonnes introuvables"):
            polb.parse_fichier(p)

    def test_sans_fichier_source_declaree_manquante(self):
        polb.load.__globals__["CSV"] = Path(tempfile.mkdtemp()) / "absent.csv"
        self.assertEqual(polb.load(), 0)
        self.assertEqual(DataSource.objects.get(key="polb").status, "missing")


class Securite(TestCase):
    def test_aucune_cle_dans_les_fichiers_rendus(self):
        racine = settings.BASE_DIR
        motifs = [re.compile(r"[0-9a-f]{40}"), re.compile(r"AISSTREAM_API_KEY\s*=\s*['\"]?[A-Za-z0-9]{20,}"),
                  re.compile(r"(?i)api[_-]?key['\"]?\s*[:=]\s*['\"][A-Za-z0-9]{16,}['\"]")]
        trouves = []
        for f in list(racine.glob("**/*.py")) + list(racine.glob("**/*.html")) + list(racine.glob("*.md")) + list(racine.glob(".env*")):
            if {"vendor", ".venv", "tests", "data"} & set(f.relative_to(racine).parts):
                continue
            texte = f.read_text(encoding="utf-8", errors="ignore")
            for m in motifs:
                if m.search(texte):
                    trouves.append((f.name, m.pattern))
        self.assertEqual(trouves, [], "motif ressemblant à une clé d'API trouvé")

    def test_env_non_fourni(self):
        self.assertFalse((settings.BASE_DIR / ".env").exists(), "un fichier .env ne doit pas être livré")


class LosAngelesParsing(TestCase):
    """Jeu d'essai calqué sur la mise en forme du site du port, y compris la coquille réelle de novembre 2020."""

    LIGNE = "<tr><td>{m}</td><td>{li}</td><td>{ei}</td><td>0</td><td>{le}</td><td>{ee}</td><td>0</td><td>{t}</td><td>1%</td></tr>"

    def _html(self, lignes):
        entete = "<tr><td></td><td>Loaded Imports</td><td>Empty Imports</td><td>Total Imports</td><td>Loaded Exports</td><td>Empty Exports</td><td>Total Exports</td><td>Total TEUs</td><td>Prior Year Change</td></tr>"
        return "<html><body><table>" + entete + "".join(lignes) + "</table></body></html>"

    def test_total_illisible_est_reconstitue_et_signale(self):
        html = self._html([self.LIGNE.format(m="October", li=500000, ei=1000, le=130000, ee=300000, t="931,000.00"),
                           self.LIGNE.format(m="November", li=464819.7, ei=1247.7, le=130916.5, ee=292762.25, t="889.,748.15")])
        lignes = pola._lire_annee(html, 2020)
        self.assertEqual(len(lignes), 2, "le mois à total illisible ne doit pas être ignoré en silence")
        nov = lignes[1]
        self.assertAlmostEqual(nov["total_teu"], 889746.15, places=2)
        self.assertIn("reconstitué", nov["note"])

    def test_total_incoherent_refuse(self):
        html = self._html([self.LIGNE.format(m="January", li=500000, ei=1000, le=130000, ee=300000, t="1,200,000.00")])
        with self.assertRaises(SourceUnavailable):
            pola._lire_annee(html, 2021)

    def test_mois_non_publies_ignores(self):
        html = self._html([self.LIGNE.format(m="January", li=500000, ei=1000, le=130000, ee=300000, t="931,000.00"),
                           self.LIGNE.format(m="February", li="", ei="", le="", ee="", t="")])
        self.assertEqual(len(pola._lire_annee(html, 2026)), 1)

    def test_prevision_refuse_une_serie_a_trous(self):
        s = serie_saisonniere()
        s.iloc[40] = np.nan
        res = forecast.prevoir(s)
        self.assertFalse(res["ok"])
        self.assertIn("manquants", res["raison"])


class TonnesPortWatch(TestCase):
    def _jours(self, debut, n, imp=1000.0, exp=200.0):
        d0 = pd.Timestamp(debut)
        PortCallDaily.objects.bulk_create([
            PortCallDaily(port_id="port664", port_name="Los Angeles-Long Beach", date=(d0 + pd.Timedelta(days=i)).date(),
                          import_container_t=imp, export_container_t=exp) for i in range(n)])

    def test_mois_partiel_exclu_et_total_correct(self):
        from dashboard.services.analytics.series import tonnes_mensuelles
        self._jours("2025-01-01", 31)     # janvier complet
        self._jours("2025-02-01", 10)     # février partiel : doit être écarté
        m = tonnes_mensuelles()
        self.assertEqual([d.strftime("%Y-%m") for d in m.index], ["2025-01"])
        self.assertEqual(m.iloc[0].import_t, 31000.0)
        self.assertEqual(m.iloc[0].total_t, 31 * 1200.0)

    def test_page_volumes_avec_et_sans_portwatch(self):
        r = self.client.get("/volumes/", HTTP_HOST="localhost")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('id="c-pw-complexe"', r.content.decode())    # pas de données : section absente, pas d'erreur


class BtsLongBeach(TestCase):
    def _rd72(self, lb, la):
        return pd.DataFrame({"Port": [f"{m}/1/2020" for m in range(1, len(lb) + 1)], "Long Beach, CA": lb, "Los Angeles, CA": la})

    def _iahn(self, lb, la):
        return pd.DataFrame({"unnamed_column": [f"2020-{m:02d}-01T00:00:00.000" for m in range(1, len(lb) + 1)], "long_beach": lb, "los_angeles": la})

    def test_arrondis_ignores_et_divergence_signalee(self):
        rd72 = self._rd72([600000, 610000, 783523], [800000, 810000, 820000])
        iahn = self._iahn([600001, 610000, 753524], [800000, 810000, 820000])   # +1 EVP (arrondi) puis une vraie divergence
        df = bts.assembler(rd72, iahn)
        self.assertEqual(df.total_teu.tolist(), [600000.0, 610000.0, 783523.0])    # jeu rd72 retenu
        self.assertEqual(df.note.tolist()[:2], ["", ""])
        self.assertIn("divergents", df.note.iloc[2])

    def test_mois_present_dans_un_seul_jeu_conserve(self):
        df = bts.assembler(self._rd72([600000, 610000], [800000, 810000]), self._iahn([610000, 620000, 630000], [810000, 820000, 830000]))
        self.assertEqual(len(df), 3)
        self.assertEqual(df.source.iloc[-1], "iahn-a7j4")

    def test_controle_los_angeles_echoue_si_ecart(self):
        pola_df = pd.DataFrame({"year": [2020, 2020, 2020], "month": [1, 2, 3], "total_teu": [800000.0, 810000.0, 999999.0]})
        with self.assertRaisesMessage(SourceUnavailable, "contrôle échoué"):
            bts.assembler(self._rd72([1, 2, 3], [800000, 810000, 820000]), self._iahn([1, 2, 3], [800000, 810000, 820000]), pola_df)


class EstimationLongBeach(TestCase):
    def _donnees(self):
        idx = pd.date_range("2019-01-01", periods=60, freq="MS")
        rng = np.random.default_rng(3)
        la = pd.Series(900_000 * (1 + 0.04 * rng.standard_normal(60)), index=idx)
        lb_vrai = pd.Series(800_000 * (1 + 0.05 * rng.standard_normal(60)), index=idx)
        ratio = pd.Series(np.linspace(7.8, 7.5, 60), index=idx)                 # rapport tonnes/EVP qui dérive lentement
        tonnes = (la + lb_vrai) * ratio * (1 + 0.01 * rng.standard_normal(60))
        return la, lb_vrai, tonnes, idx

    def test_estimation_proche_du_vrai_et_dans_la_bande(self):
        la, lb_vrai, tonnes, idx = self._donnees()
        obs = lb_vrai.iloc[:44]                                                  # 44 mois observés, 16 à estimer
        ancres = {idx[56].strftime("%Y-%m"): float(lb_vrai.iloc[56]), idx[58].strftime("%Y-%m"): float(lb_vrai.iloc[58])}
        controles = {idx[50].strftime("%Y-%m"): float(lb_vrai.iloc[50])}
        r = lb_estimate.estimer(obs, la, tonnes, ancres=ancres, controles=controles)
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["estime"]["mois"]), 16)
        est = np.array(r["estime"]["valeurs"]); vrai = lb_vrai.iloc[44:].values
        self.assertLess(np.mean(np.abs(est - vrai) / vrai), 0.08)
        for e, b, h in zip(est, r["estime"]["bas"], r["estime"]["haut"]):
            self.assertLess(b, e); self.assertLess(e, h)
        self.assertEqual(len(r["controle"]), 1)
        self.assertLess(abs(r["controle"][0]["erreur_pct"]), 10)

    def test_historique_trop_court_refuse(self):
        la, lb_vrai, tonnes, idx = self._donnees()
        r = lb_estimate.estimer(lb_vrai.iloc[:20], la, tonnes)
        self.assertFalse(r["ok"])
        self.assertIn("calibration impossible", r["raison"])


class LienAisPermanentTests(TestCase):
    """Le lien permanent avec le flux AIS : démarrage conditionnel, mémoire des positions, diffusion continue."""

    def _ready(self, env, argv, retirer=()):
        with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(sys, "argv", argv),                 mock.patch("dashboard.services.collectors.ais_stream.demarrer") as demarrer:
            for k in retirer:
                os.environ.pop(k, None)
            apps.get_app_config("dashboard").ready()
        return demarrer

    def test_ne_demarre_pas_sans_cle(self):
        self.assertFalse(self._ready({}, ["gunicorn"], retirer=["AISSTREAM_API_KEY"]).called)

    def test_ne_demarre_pas_si_desactive(self):
        self.assertFalse(self._ready({"AISSTREAM_API_KEY": "cle-factice", "AIS_AUTOSTART": "0"}, ["gunicorn"]).called)

    def test_demarre_sous_un_serveur_pas_sous_manage_test(self):
        env = {"AISSTREAM_API_KEY": "cle-factice"}
        self.assertTrue(self._ready(env, ["gunicorn"]).called)
        self.assertFalse(self._ready(env, ["manage.py", "test"]).called)

    def test_runserver_ouvre_le_lien_une_seule_fois(self):
        env = {"AISSTREAM_API_KEY": "cle-factice"}
        self.assertFalse(self._ready(env, ["manage.py", "runserver"], retirer=["RUN_MAIN"]).called)   # processus surveillant
        self.assertTrue(self._ready({**env, "RUN_MAIN": "true"}, ["manage.py", "runserver"]).called)   # processus serveur

    def test_memoire_des_positions_et_fenetre(self):
        from dashboard.services.collectors.ais_stream import FluxAis
        f = FluxAis()
        maintenant = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        vieux = (timezone.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        f.recevoir({"MessageType": "PositionReport", "MetaData": {"MMSI": 366000001, "ShipName": "TEST A", "latitude": 33.7, "longitude": -118.25, "time_utc": maintenant + ".0 +0000 UTC"},
                    "Message": {"PositionReport": {"Sog": 0.1, "Cog": 10, "NavigationalStatus": 5}}})
        f.recevoir({"MessageType": "PositionReport", "MetaData": {"MMSI": 366000002, "ShipName": "VIEUX", "latitude": 33.7, "longitude": -118.2, "time_utc": vieux + ".0 +0000 UTC"},
                    "Message": {"PositionReport": {"Sog": 5, "Cog": 90, "NavigationalStatus": 0}}})
        f.recevoir({"MessageType": "ShipStaticData", "MetaData": {"MMSI": 366000001},
                    "Message": {"ShipStaticData": {"Type": 70, "Dimension": {"A": 200, "B": 100}, "Name": "TEST A"}}})
        navires = f.liste()
        self.assertEqual([n["mmsi"] for n in navires], ["366000001"])            # le navire silencieux depuis 2 h est exclu
        self.assertEqual(navires[0]["type_group"], "Cargo (conteneurs, vrac)")   # le type vient du message statique
        self.assertEqual(navires[0]["length"], 300)
        self.assertEqual(f.etat()["messages"], 3)
        self.assertFalse(f.etat()["connectee"])                                  # aucun réseau dans ce test

    def test_canal_de_diffusion_continue(self):
        import json
        from itertools import islice
        reponse = self.client.get("/api/ais/stream/")
        self.assertEqual(reponse["Content-Type"], "text/event-stream")
        self.assertIn("no-cache", reponse["Cache-Control"])
        morceaux = [m.decode() for m in islice(reponse.streaming_content, 2)]
        reponse.close()
        self.assertTrue(morceaux[0].startswith("retry:"))
        charge = json.loads(morceaux[1].removeprefix("data: ").strip())
        self.assertIn("navires", charge["ais"])
        self.assertIn("connectee", charge["etat"])
