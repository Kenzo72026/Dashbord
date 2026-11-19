from django.urls import path

from . import views

urlpatterns = [
    path("", views.accueil, name="accueil"),
    path("volumes/", views.volumes, name="volumes"),
    path("monde/", views.monde, name="monde"),
    path("direct/", views.direct, name="direct"),
    path("decision/", views.decision, name="decision"),
    path("sources/", views.sources, name="sources"),
    path("fiche/", views.fiche, name="fiche"),
    path("api/live/", views.api_live, name="api_live"),
    path("api/refresh/", views.api_refresh, name="api_refresh"),
]
