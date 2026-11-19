"""Modèles de données.

Principe : les collecteurs écrivent ici, les vues ne lisent QUE ici. Ainsi, rafraîchir la page n'appelle
aucune API externe (consigne de l'énoncé). Chaque source garde son adresse et sa date de récupération.
"""
from django.db import models


class DataSource(models.Model):
    """Registre des sources : adresse, date de récupération et état (pour les messages « source indisponible »)."""

    STATUS = [("ok", "À jour"), ("stale", "Périmée"), ("error", "Erreur"), ("missing", "Indisponible")]

    key = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    url = models.CharField(max_length=500, blank=True)
    kind = models.CharField(max_length=10, default="static")  # static | live
    retrieved_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default="missing")
    message = models.TextField(blank=True)
    rows = models.IntegerField(default=0)
    last_period = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.key


class MonthlyVolume(models.Model):
    """Volumes mensuels en EVP (TEU) d'un port : importations/exportations, chargés/vides."""

    port = models.CharField(max_length=3)  # LA | LB
    month = models.DateField()  # premier jour du mois
    loaded_imports = models.FloatField(default=0)
    empty_imports = models.FloatField(default=0)
    loaded_exports = models.FloatField(default=0)
    empty_exports = models.FloatField(default=0)
    total_teu = models.FloatField(default=0)

    class Meta:
        unique_together = ("port", "month")
        ordering = ["month", "port"]

    @property
    def total_imports(self):
        return self.loaded_imports + self.empty_imports

    @property
    def total_exports(self):
        return self.loaded_exports + self.empty_exports


class CppiRecord(models.Model):
    """Container Port Performance Index (Banque mondiale) : score et rang par port et par année."""

    port_name = models.CharField(max_length=80)
    locode = models.CharField(max_length=6)
    country = models.CharField(max_length=60, blank=True)
    year = models.IntegerField()
    score = models.FloatField(null=True, blank=True)
    rank = models.IntegerField(null=True, blank=True)
    rank_kind = models.CharField(max_length=12, default="publie")  # publie | recalcule
    edition = models.CharField(max_length=60)

    class Meta:
        ordering = ["year", "rank"]


class UnctadValue(models.Model):
    """Valeurs CNUCED (UNCTADstat), format long : une ligne = une mesure d'une entité pour une période."""

    series = models.CharField(max_length=30)  # port_calls | median_time | teu_throughput | plsci
    entity = models.CharField(max_length=20)
    entity_label = models.CharField(max_length=80)
    period = models.CharField(max_length=10)  # "2023" ou "2026Q3"
    value = models.FloatField(null=True)

    class Meta:
        ordering = ["series", "entity", "period"]


class PortCallDaily(models.Model):
    """Escales quotidiennes (IMF PortWatch), utilisées pour l'activité des navires et la comparaison mondiale."""

    port_id = models.CharField(max_length=12)
    port_name = models.CharField(max_length=60)
    date = models.DateField()
    container = models.IntegerField(default=0)
    dry_bulk = models.IntegerField(default=0)
    general_cargo = models.IntegerField(default=0)
    roro = models.IntegerField(default=0)
    tanker = models.IntegerField(default=0)
    total = models.IntegerField(default=0)
    import_container_t = models.FloatField(default=0)  # tonnes de conteneurs importées (estimation AIS du FMI)
    export_container_t = models.FloatField(default=0)

    class Meta:
        unique_together = ("port_id", "date")
        ordering = ["port_id", "date"]


class WeatherPoint(models.Model):
    """Météo du port (Open-Meteo) : un point « current » et des points horaires de prévision."""

    time = models.DateTimeField()
    is_current = models.BooleanField(default=False)
    wind_kn = models.FloatField(null=True)
    gust_kn = models.FloatField(null=True)
    wind_dir = models.FloatField(null=True)
    visibility_m = models.FloatField(null=True)
    wave_m = models.FloatField(null=True)
    wave_period_s = models.FloatField(null=True)
    wave_dir = models.FloatField(null=True)
    swell_m = models.FloatField(null=True)
    fetched_at = models.DateTimeField()

    class Meta:
        ordering = ["time"]


class AisPosition(models.Model):
    """Dernière position connue de chaque navire. origin = live (aisstream) ou archive (jeu AIS du TP)."""

    mmsi = models.CharField(max_length=9)
    name = models.CharField(max_length=60, blank=True)
    lat = models.FloatField()
    lon = models.FloatField()
    sog = models.FloatField(null=True)
    cog = models.FloatField(null=True)
    nav_status = models.IntegerField(null=True)
    ship_type = models.IntegerField(null=True)
    type_group = models.CharField(max_length=40, blank=True)
    length = models.FloatField(null=True)
    seen_at = models.DateTimeField()
    origin = models.CharField(max_length=8, default="live")

    class Meta:
        unique_together = ("mmsi", "origin")


class Insight(models.Model):
    """Résultats calculés (prévisions, anomalies, alertes, recommandations) : recalculés à chaque actualisation."""

    key = models.CharField(max_length=40, unique=True)
    payload = models.JSONField(default=dict)
    computed_at = models.DateTimeField()
