"""Constantes du tableau de bord : sources, géographie, seuils d'alerte, ports de comparaison."""

# ---------------------------------------------------------------- sources (adresse officielle de chaque jeu)
SOURCES = {
    "pola": {
        "name": "Port of Los Angeles · statistiques de conteneurs (EVP mensuels)",
        "url": "https://www.portoflosangeles.org/business/statistics/container-statistics",
        "kind": "static",
    },
    "polb": {
        "name": "Port of Long Beach · statistiques de conteneurs (EVP mensuels)",
        "url": "https://polb.com/business/port-statistics/",
        "kind": "static",
    },
    "bts": {
        "name": "BTS (ministère américain des Transports) · EVP mensuels de Long Beach, 2019 → août 2023",
        "url": "https://data.bts.gov/d/rd72-aq8r",
        "kind": "static",
    },
    "cppi": {
        "name": "Banque mondiale · Container Port Performance Index (CPPI 2023, 2020-2024 et 2020-2025)",
        "url": "https://documents1.worldbank.org/curated/en/099091925073051415/pdf/P509479-9781ba16-3dbc-4064-9d8f-8eaf9951e09d.pdf",
        "kind": "static",
    },
    "unctad": {
        "name": "CNUCED · UNCTADstat (escales, temps au port, débit EVP, connectivité)",
        "url": "https://unctadstat.unctad.org/datacentre/",
        "kind": "static",
    },
    "portwatch": {
        "name": "FMI · PortWatch (escales quotidiennes, signaux AIS des Nations unies)",
        "url": "https://portwatch.imf.org/",
        "kind": "static",
    },
    "weather": {
        "name": "Open-Meteo · prévisions de vent et de vagues",
        "url": "https://open-meteo.com/",
        "kind": "live",
    },
    "ais_live": {
        "name": "aisstream.io · positions AIS en direct",
        "url": "https://aisstream.io/documentation",
        "kind": "live",
    },
    "ais_archive": {
        "name": "MarineCadastre (NOAA/BOEM) · extrait AIS du TP, 23/02-01/03/2026",
        "url": "https://marinecadastre.gov/ais/",
        "kind": "static",
    },
}

# Adresses précises des fichiers téléchargés (traçabilité complète dans le README et la page « Sources »)
POLA_YEAR_URL = "https://www.portoflosangeles.org/business/statistics/container-statistics/historical-teu-statistics-{year}"
CPPI_2024_PDF = SOURCES["cppi"]["url"]
CPPI_2025_XLSX = "https://openknowledge.worldbank.org/server/api/core/bitstreams/9cf20807-7dcd-4de7-9de2-fdb2d0589a73/content"  # annexe Excel « CPPI 2020-2025 » (juin 2026)
BTS_RD72 = "https://data.bts.gov/api/views/rd72-aq8r/rows.csv?accessType=DOWNLOAD"   # « Monthly TEU Data » 2019-01 → 2022-10
BTS_IAHN = "https://data.bts.gov/resource/iahn-a7j4.json"                            # « TEU Handled by Select U.S. Container Ports » 2020-01 → 2023-08
CPPI_2025_PAGE = "https://www.worldbank.org/en/topic/transport/publication/cppi"
CPPI_2023_PDF = "https://documents1.worldbank.org/curated/en/099060324114539683/pdf/P17583313892300871be641a5ea7b90e0e6.pdf"
UNCTAD_BULK = "https://unctadstat-api.unctad.org/bulkdownload/{code}/{name}"
UNCTAD_DATASETS = ["US.PortCalls", "US.PortCallsArrivals", "US.ContPortThroughput", "US.PLSCI", "US.LSCI"]
PORTWATCH_DAILY = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/Daily_Ports_Data/FeatureServer/0/query"
OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_MARINE = "https://marine-api.open-meteo.com/v1/marine"
AISSTREAM_WS = "wss://stream.aisstream.io/v0/stream"

USER_AGENT = "dashboard-academique-master2/1.0 (projet universitaire, usage non commercial)"

# ---------------------------------------------------------------- géographie
PORT_POINT = (33.72, -118.25)          # chenal principal, vent
MARINE_POINT = (33.60, -118.30)        # au large de la jetée, vagues (grille marine Open-Meteo)
AIS_BBOX = [[33.55, -118.45], [33.85, -118.05]]  # [lat, lon] des deux coins : baie de San Pedro et approches
MAP_CENTER = (33.70, -118.24)

# ---------------------------------------------------------------- ports de comparaison
# Noms tels qu'écrits dans le rapport CPPI (annexe) → étiquette d'affichage
CPPI_PORTS = {
    "Los Angeles": "Los Angeles",
    "Long Beach": "Long Beach",
    "Djibouti": "Djibouti",
    "Fuzhou": "Fuzhou (1ᵉʳ en 2025)",
    "Singapore": "Singapour",
    "Rotterdam": "Rotterdam",
    "Savannah": "Savannah",
    "Jeddah": "Djeddah",
}
CPPI_2023_NAMES = {n.upper(): n for n in CPPI_PORTS}  # noms en majuscules dans l'édition 2023

PORTWATCH_PORTS = {
    "port664": "Los Angeles-Long Beach",
    "port294": "Djibouti",
    "port1201": "Singapour",
    "port1114": "Rotterdam",
}
PORTWATCH_SINCE = "2019-01-01"

UNCTAD_COUNTRIES_CALLS = ["United States of America", "China", "Netherlands (Kingdom of the)", "Germany", "Singapore", "Japan"]
UNCTAD_COUNTRIES_TEU = ["United States", "Djibouti", "China", "Singapore", "Netherlands (Kingdom of the)", "Egypt", "Saudi Arabia", "Kenya"]
UNCTAD_PLSCI_PORTS = {
    "USLAX": "Los Angeles", "USLGB": "Long Beach", "DJJIB": "Djibouti", "SGSIN": "Singapour",
    "NLRTM": "Rotterdam", "CNSHA": "Shanghai", "SAJED": "Djeddah", "USSAV": "Savannah",
}
UNCTAD_LSCI_ECONOMIES = ["United States", "Djibouti", "China", "Singapore", "Netherlands (Kingdom of the)", "Egypt", "Saudi Arabia"]

# ---------------------------------------------------------------- seuils météo (paramétrables)
# Inspirés des avis du service météo américain (NWS) : « small craft advisory » 21-33 nœuds, « gale warning » ≥ 34 nœuds.
# Ce sont des seuils pédagogiques : la capitainerie fixe ses propres limites d'exploitation.
WIND_WARN_KN = 21.0
WIND_ALERT_KN = 34.0
GUST_WARN_KN = 28.0
GUST_ALERT_KN = 34.0
WAVE_WARN_M = 2.5
WAVE_ALERT_M = 4.0
VISIBILITY_WARN_M = 2000.0

# ---------------------------------------------------------------- AIS
NAV_STATUS = {
    0: "En route (moteur)", 1: "À l'ancre", 2: "Sans maîtrise", 3: "Manœuvre restreinte", 4: "Contraint par le tirant d'eau",
    5: "À quai", 6: "Échoué", 7: "En pêche", 8: "À la voile", 15: "Non défini",
}


def type_group(ship_type):
    """Regroupe le code de type de navire AIS en familles lisibles."""
    if ship_type is None:
        return "Inconnu"
    t = int(ship_type)
    if 70 <= t <= 79:
        return "Cargo (conteneurs, vrac)"
    if 80 <= t <= 89:
        return "Pétrolier / chimiquier"
    if 60 <= t <= 69:
        return "Passagers"
    if t in (31, 32, 52):
        return "Remorqueur"
    if t == 30:
        return "Pêche"
    if t in (36, 37):
        return "Plaisance / voilier"
    if t in (50, 51, 53, 54, 55, 35):
        return "Service portuaire / sécurité"
    if 20 <= t <= 29:
        return "Autre (aéroglisseur…)"
    return "Autre"
