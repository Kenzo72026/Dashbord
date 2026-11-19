"""Registre des sources : chaque collecteur y note l'adresse, la date de récupération et l'état."""
from datetime import timedelta

from django.utils import timezone

from ..constants import SOURCES
from ..models import DataSource


def declare(key, status, message="", rows=0, last_period="", notes="", url=None, retrieved=True):
    """Crée ou met à jour la fiche d'une source. `retrieved=False` conserve l'ancienne date de récupération."""
    meta = SOURCES[key]
    src, _ = DataSource.objects.get_or_create(key=key, defaults={"name": meta["name"], "url": meta["url"], "kind": meta["kind"]})
    src.name, src.kind = meta["name"], meta["kind"]
    src.url = url or meta["url"]
    src.status = status
    src.message = message
    if rows:
        src.rows = rows
    if last_period:
        src.last_period = last_period
    if notes:
        src.notes = notes
    if retrieved:
        src.retrieved_at = timezone.now()
    src.save()
    return src


def age_seconds(key):
    """Âge de la dernière récupération (None si jamais récupérée)."""
    src = DataSource.objects.filter(key=key).first()
    if not src or not src.retrieved_at:
        return None
    return (timezone.now() - src.retrieved_at).total_seconds()


def is_fresh(key, ttl_seconds):
    age = age_seconds(key)
    return age is not None and age < ttl_seconds


def mark_stale_live(key, max_age):
    """Passe une source « live » en état périmé si sa dernière récupération est trop ancienne."""
    src = DataSource.objects.filter(key=key).first()
    if src and src.retrieved_at and src.status == "ok" and timezone.now() - src.retrieved_at > timedelta(seconds=max_age):
        src.status = "stale"
        src.save(update_fields=["status"])
