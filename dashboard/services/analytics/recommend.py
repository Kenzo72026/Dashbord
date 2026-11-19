"""Recommandations d'action (niveau PRESCRIPTIF du cours : « que faire ? »).

Le système propose, l'humain choisit : niveau d'automatisation 3 sur l'échelle du cours (« recommande une option,
l'humain valide ou refuse »). Chaque recommandation affiche ses preuves chiffrées, l'effet attendu, qui décide et
dans quel cas ne PAS la suivre (parades au biais d'automatisation et à la boîte noire).

Critères du cours appliqués : fréquence de la décision (quelques-unes par semaine), temps disponible (heures),
coût d'une erreur (élevé : sécurité et délais), réversibilité (partielle), qualité des données (partielle : modèles
globaux, sources publiques décalées) → on s'arrête au niveau 3, jamais d'exécution automatique.
"""
from ..fmt import mois_fr, nb, signe_pct

AUTOMATISATION = {"niveau": 3, "libelle": "Niveau 3 · l'outil recommande, un humain valide ou refuse"}


def _rec(id, priorite, horizon, titre, action, pourquoi, effet, qui, limites):
    return {"id": id, "priorite": priorite, "horizon": horizon, "titre": titre, "action": action, "pourquoi": pourquoi,
            "effet": effet, "qui": qui, "limites": limites, "automatisation": AUTOMATISATION}


def recommander(prev, anom_m, anom_h, meteo, ais, alerte_file, cppi_ctx, polb_ok, perimetre):
    recs = []

    # --- 1. météo : décision immédiate (0-48 h) ---
    if meteo.get("disponible"):
        fortes = [a for a in meteo["alertes"] if a["niveau"] == "alerte"]
        vig = [a for a in meteo["alertes"] if a["niveau"] == "vigilance" and a["variable"] in ("vent", "rafales", "vagues")]
        if fortes:
            a = fortes[0]
            recs.append(_rec(
                "meteo-alerte", 1, "0 à 48 h", "Anticiper l'épisode de vent ou de vagues fortes",
                "Prévenir la capitainerie et les pilotes ; avancer ou différer les mouvements de navires prévus pendant l'épisode ; "
                "informer les transporteurs des retards possibles.",
                [a["message"], *[b["message"] for b in fortes[1:3]]],
                "Éviter des manœuvres dans la fenêtre à risque et limiter l'attente au mouillage.",
                "Capitainerie (harbor master) avec les chefs de terminal",
                "Prévision de modèle global (grille de plusieurs km), pas une mesure au quai : la capitainerie applique ses propres limites d'exploitation."))
        elif vig:
            recs.append(_rec(
                "meteo-vigilance", 2, "0 à 48 h", "Surveiller la dégradation météo",
                "Garder le plan d'escales actuel, mais vérifier la prévision toutes les 6 heures et prévenir les pilotes d'une possible dégradation.",
                [a["message"] for a in vig[:3]], "Réagir tôt si la prévision se durcit, sans déclencher d'alerte inutile.",
                "Chef de quart de la capitainerie", "Seuils de vigilance indicatifs (inspirés des avis du NWS)."))
    else:
        recs.append(_rec("meteo-absente", 2, "immédiat", "Météo indisponible : décider avec une autre source",
                         "Consulter le service météo officiel (NWS) avant toute décision de pilotage.",
                         [meteo.get("message", "Source météo non récupérée.")], "Ne pas décider à l'aveugle.", "Capitainerie",
                         "Aucune alerte météo automatique tant que la source est indisponible."))

    # --- 2. file d'attente AIS ---
    if alerte_file:
        recs.append(_rec("file-attente", 2, "0 à 24 h", "Réguler la file au mouillage",
                         "Revoir l'ordre d'entrée des navires en attente et prévenir les terminaux concernés.",
                         [alerte_file["message"]], "Réduire le temps d'attente avant le poste à quai.", "Capitainerie et planificateurs de terminal",
                         "Couverture AIS gratuite variable : vérifier sur le radar/VTS avant d'agir."))

    # --- 3. charge du mois suivant (tactique) ---
    if prev and prev.get("ok"):
        p = prev["prevision"][0]
        pct = p["ecart_annee_prec_pct"]
        preuve = [f"Prévision {mois_fr(p['mois'])} : {nb(p['valeur'])} EVP (fourchette {nb(p['bas'])} à {nb(p['haut'])}).",
                  f"Même mois un an avant : {nb(p['annee_precedente'])} EVP ({signe_pct(pct)})." if pct is not None else "",
                  f"Périmètre : {perimetre}. Erreur moyenne du modèle {prev['modele']} : ±{nb(p['mae'])} EVP."]
        preuve = [x for x in preuve if x]
        lim = "La prévision ne voit pas les chocs (grève, tempête, changement de service des armateurs) : revoir si une anomalie apparaît."
        if pct is not None and pct >= 5:
            recs.append(_rec("charge-hausse", 2, "ce mois-ci", "Préparer la montée en charge", "Planifier des équipes et des postes à quai supplémentaires "
                             "pour les semaines de pointe ; reporter les maintenances lourdes non urgentes.", preuve,
                             "Absorber le pic sans allonger le temps d'escale.", "Planification / exploitation des terminaux", lim))
        elif pct is not None and pct <= -5:
            recs.append(_rec("charge-baisse", 2, "ce mois-ci", "Profiter de la baisse d'activité", "Avancer les maintenances et formations ; ajuster les équipes "
                             "sans les réduire en deçà de la fourchette basse.", preuve, "Utiliser le creux sans perdre en réactivité.",
                             "Planification / maintenance", lim))
        else:
            recs.append(_rec("charge-stable", 3, "ce mois-ci", "Maintenir le plan de ressources", "Conserver le dimensionnement actuel et surveiller "
                             "l'écart entre réel et prévision en début de mois.", preuve, "Éviter un surdimensionnement injustifié.",
                             "Planification / exploitation des terminaux", lim))

    # --- 4. anomalies : vérifier avant d'ajuster ---
    recentes = []
    if anom_m and anom_m.get("ok"):
        recentes = [a for a in anom_m["anomalies"] if a["mois"] >= (anom_m["serie"][-6]["mois"] if len(anom_m["serie"]) >= 6 else "0000")]
    if recentes:
        a = recentes[-1]
        diag = a["diagnostic"][0] if a["diagnostic"] else None
        recs.append(_rec("anomalie-mensuelle", 2, "cette semaine", f"Vérifier la cause de l'écart de {mois_fr(a['mois'])}",
                         "Chercher la cause avec les terminaux et les armateurs (grève, retard de navires, tempête, changement de service) avant "
                         "d'ajuster les plans.",
                         [f"{mois_fr(a['mois'])} : {nb(a['valeur'])} EVP, soit {signe_pct(a['ecart_pct'])} par rapport à l'attendu ({nb(a['attendu'])}).",
                          f"Flux le plus touché : {diag['flux']} ({signe_pct(diag['variation_pct'])} sur un an)." if diag else ""],
                         "Ne pas corriger un événement ponctuel comme s'il était durable.", "Direction d'exploitation",
                         "L'outil détecte l'écart, il n'en connaît pas la cause."))
    if anom_h and anom_h.get("ok"):
        d = anom_h["derniere"]
        if abs(d.get("z") or 0) >= 2:
            recs.append(_rec("anomalie-hebdo", 2, "cette semaine", "Escales inhabituelles cette semaine",
                             "Comparer avec les arrivées annoncées par les agents maritimes et ajuster les postes de la semaine.",
                             [f"Semaine du {d['semaine'][8:10]}/{d['semaine'][5:7]} : {nb(d['valeur'])} escales de porte-conteneurs contre "
                              f"{nb(d['mediane'])} habituellement (z = {(d.get('z') or 0):+.1f})."], "Adapter la capacité à une semaine hors norme.",
                             "Planification de l'exploitation", "Données PortWatch publiées avec quelques jours de décalage."))

    # --- 5. structure : conteneurs vides (diagnostic → action) ---
    if anom_m and anom_m.get("ok") and anom_m.get("structure"):
        s = anom_m["structure"]
        recs.append(_rec("vides", 3, "trimestre", "Sécuriser le repositionnement des conteneurs vides",
                         "Prévoir des surfaces de stockage de vides et des créneaux d'évacuation dédiés dans les terminaux et les parcs d'appui.",
                         [f"Les conteneurs vides représentent {s['part_vides_exports']:.0f} % des exportations ({mois_fr(s['mois'])}).",
                          f"Les exportations chargées ne pèsent que {s['part_exports_charges']:.0f} % du total contre {s['part_imports_charges']:.0f} % pour les importations chargées."],
                         "Libérer de l'espace dans le parc et éviter que les vides n'occupent des postes utiles.", "Exploitation des parcs",
                         "Constat tiré des chiffres du port ; l'optimum dépend des contrats des armateurs."))

    # --- 6. stratégique : temps au port (CPPI) ---
    if cppi_ctx:
        recs.append(_rec("cppi", 3, "année", "Cibler le temps passé par les navires au port",
                         "Mesurer chaque mois le temps d'attente au mouillage et le temps à quai par terminal (données AIS), puis fixer une cible "
                         "de réduction et publier le suivi.",
                         cppi_ctx, "Remonter dans le classement CPPI, qui ne mesure que le temps au port.",
                         "Direction des ports et des terminaux", "Le CPPI est un score de temps, pas de volume ni de qualité de service : "
                         "à lire avec le trafic traité."))

    # --- 7. qualité des données ---
    if not polb_ok:
        recs.append(_rec("donnees-polb", 2, "aujourd'hui", "Compléter les volumes avec Long Beach",
                         "Obtenir le CSV mensuel de Long Beach par une voie légitime (polb.com refuse l'accès depuis ce réseau : autre réseau, camarade, enseignante), l'enregistrer dans data/raw/polb_teu_monthly.csv puis lancer la commande « python manage.py import_polb ».",
                         ["Les volumes et la prévision portent actuellement sur Los Angeles seul."],
                         "Prévisions et indicateurs sur l'ensemble de San Pedro Bay.", "Administrateur du tableau de bord",
                         "Sans Long Beach, ne pas présenter les chiffres comme ceux du complexe (source inaccessible, voir la page Sources)."))

    recs.sort(key=lambda r: r["priorite"])
    return recs
