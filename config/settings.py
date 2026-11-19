"""Réglages Django du tableau de bord San Pedro Bay.

Aucun secret n'est écrit ici : tout vient de l'environnement (fichier .env, voir .env.example).
"""
import os
from pathlib import Path

from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent


def _charger_env(chemin: Path) -> None:
    """Mini lecteur de .env (évite une dépendance). Les variables déjà définies gagnent."""
    if not chemin.exists():
        return
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, valeur = ligne.partition("=")
        os.environ.setdefault(cle.strip(), valeur.strip().strip('"').strip("'"))


_charger_env(BASE_DIR / ".env")

# Une clé aléatoire par processus si aucune n'est fournie (suffisant en local : pas de sessions sensibles).
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or get_random_secret_key()
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]

# Hébergement sur Render : le nom d'hôte public est fourni par la plateforme (RENDER_EXTERNAL_HOSTNAME), rien à écrire à la main.
_hote_render = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "")
if _hote_render:
    ALLOWED_HOSTS.append(_hote_render)
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]
if _hote_render:
    CSRF_TRUSTED_ORIGINS.append(f"https://{_hote_render}")
if not DEBUG:
    # Derrière le proxy HTTPS de l'hébergeur : la requête d'origine était en https.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3", "OPTIONS": {"timeout": 20}}}

LANGUAGE_CODE = "fr"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Réglages propres au tableau de bord (sans secret) ---
DATA_DIR = BASE_DIR / "data"
WEATHER_TTL_SECONDS = int(os.environ.get("WEATHER_TTL_SECONDS", "900"))
AIS_STALE_SECONDS = int(os.environ.get("AIS_STALE_SECONDS", "900"))
# La clé AIS est lue uniquement ici, à l'exécution, depuis l'environnement. Elle n'est jamais affichée ni stockée.
AISSTREAM_API_KEY = os.environ.get("AISSTREAM_API_KEY", "")
