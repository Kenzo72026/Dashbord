#!/usr/bin/env bash
# Étapes de construction sur Render : dépendances, fichiers statiques, schéma de la base.
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
