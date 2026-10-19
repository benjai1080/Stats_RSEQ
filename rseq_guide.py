"""Annexe des rapports : explication des stats et guide d'interprétation.

Chaque fiche dit à quelle question la stat répond, comment elle se calcule, comment la lire
et où elle trompe. Les repères chiffrés viennent de la ligue elle-même (rseq_saison.py les
calcule sur tous les matchs de la saison) ; sans eux, la fiche reste valable sans chiffres.
"""
import html


def esc(x):
    return html.escape(str(x))


def fr(x, d=1):
    return f"{x:.{d}f}".replace(".", ",")


# Fiches : titre, niveau (base | avancé), question, calcul, lecture, pièges, repères [(portée, clé, format)]
GUIDE = [
    {
        "title": "Lire ce rapport : deux sources",
        "level": "base",
        "question": "D'où viennent les chiffres ?",
        "calc": "Le box score officiel donne les stats de base (points, rebonds, passes…). Le play-by-play, "
                "rejoué action par action, donne tout ce qui demande de savoir qui était sur le terrain : "
                "+/-, minutes recalculées, ratings, on/off, quintettes, USG%, PD%…",
        "read": "Dans un match, le box score recalculé est comparé à l'officiel : s'ils concordent, le "
                "play-by-play est complet. Sur une saison, les stats de base viennent des box officiels "
                "(parfois corrigés après le match) et les stats d'impact du play-by-play.",
        "traps": "Quand la feuille oublie des changements, le rejeu les déduit des actions des joueurs "
                 "(section Validation ou Fiabilité). Plus il y a de corrections, plus le +/- et les "
                 "quintettes de ce match sont approximatifs.",
    },
    {
        "title": "Taille de l'échantillon",
        "level": "base",
        "question": "À partir de quand un chiffre veut-il dire quelque chose ?",
        "calc": "Une possession dure environ 14 à 16 secondes ; un joueur qui joue 20 minutes participe à "
                "environ 40 possessions en attaque et 40 en défense par match.",
        "read": "Règle pratique (pas une loi statistique) : moins de 100 possessions, c'est une anecdote ; "
                "100 à 300, une indication ; au-delà de 300, une tendance. Les pourcentages de tir se "
                "stabilisent plus vite que les ratings sur le terrain, qui dépendent aussi des coéquipiers "
                "et des adversaires.",
        "traps": "Un joueur entré 3 minutes peut afficher +200 de Net : c'est 3 possessions. Toujours lire "
                 "la colonne MIN ou POSS avant le reste.",
    },
    {
        "title": "Possessions et rythme",
        "level": "avancé",
        "question": "Combien de fois chaque équipe a-t-elle eu le ballon ?",
        "calc": "Une possession commence à chaque changement de main : panier réussi, rebond défensif, "
                "balle perdue, dernier lancer franc réussi. Un rebond offensif prolonge la possession en "
                "cours. Rythme = possessions par équipe ramenées à 40 minutes.",
        "read": "Les deux équipes ont presque le même nombre de possessions (à 1 ou 2 près par période). "
                "Le rythme décrit le style du match, pas sa qualité : un match rapide donne plus de points "
                "aux deux équipes. C'est pourquoi on compare les équipes par 100 possessions plutôt qu'aux "
                "points par match.",
        "traps": "L'estimation classique (tirs − rebonds offensifs + pertes + 0,44 × LF) est affichée entre "
                 "parenthèses pour contrôle. Le compte réel la dépasse souvent de quelques possessions : il "
                 "compte les possessions de fin de période sans tir, et les séquences mal notées par la "
                 "feuille (section « Possessions ambiguës ») en ajoutent. Les deux équipes d'un même match "
                 "restent à une ou deux possessions l'une de l'autre.",
        "bench": [("team", "POSS", "num")],
    },
    {
        "title": "ORtg, DRtg et Net (équipe)",
        "level": "avancé",
        "question": "Qui a été le plus efficace, une fois le rythme mis de côté ?",
        "calc": "ORtg = 100 × points marqués / possessions. DRtg = 100 × points accordés / possessions "
                "adverses. Net = ORtg − DRtg.",
        "read": "Un ORtg de 100, c'est un point par possession (dans cette ligue, la médiane est plus basse : "
                "voir repères). Le Net d'une saison prédit mieux les résultats futurs que la fiche "
                "victoires-défaites, qui dépend des matchs serrés. Un Net de +10 sur une saison, c'est une "
                "équipe nettement au-dessus de ses adversaires.",
        "traps": "Contre un calendrier faible ou fort, le Net est flatteur ou sévère : il n'est pas corrigé "
                 "selon la force des adversaires.",
        "bench": [("team", "ORtg", "num")],
    },
    {
        "title": "Les quatre facteurs (Dean Oliver)",
        "level": "avancé",
        "question": "Pourquoi une équipe gagne-t-elle ses possessions ?",
        "calc": "eFG% (qualité des tirs), BP% = pertes / possessions (garder le ballon), RO% = rebonds "
                "offensifs / (rebonds offensifs + rebonds défensifs adverses) (deuxièmes chances), "
                "LF/Tir = lancers francs réussis / tirs tentés (aller sur la ligne). Chaque facteur se lit "
                "en attaque et en défense (celui de l'adversaire).",
        "read": "Dans l'ordre d'importance habituellement cité : tir (environ 40 %), pertes (25 %), rebond "
                "offensif (20 %), lancers francs (15 %). Pour expliquer une défaite, chercher le facteur où "
                "l'écart avec l'adversaire est le plus grand ; pour fixer une priorité d'entraînement, "
                "chercher celui où l'équipe est loin du repère de la ligue.",
        "traps": "Les pondérations viennent du basket professionnel américain ; elles donnent un ordre de "
                 "grandeur, pas une règle pour le collégial.",
        "bench": [("team", "eFG%", "pct"), ("team", "TOV%", "pct"), ("team", "OREB%", "pct"),
                  ("team", "FTM/FGA", "pct")],
    },
    {
        "title": "eFG% et TS% (efficacité au tir)",
        "level": "avancé",
        "question": "Combien rapporte un tir de ce joueur ou de cette équipe ?",
        "calc": "eFG% = (paniers + 0,5 × paniers à 3) / tirs : un panier à 3 vaut 1,5 panier à 2. "
                "TS% = points / (2 × (tirs + 0,44 × LF tentés)) : ajoute les lancers francs (0,44 parce "
                "qu'une série de lancers ne consomme pas toujours une possession : and-one, techniques). "
                "PPT = points par tir tenté.",
        "read": "TS% est la meilleure mesure simple de l'efficacité d'un marqueur. À comparer au repère de "
                "la ligue : 5 points au-dessus de la médiane, c'est un marqueur nettement efficace. Lire "
                "TS% avec USG% : être efficace avec beaucoup de tirs est plus difficile qu'avec peu.",
        "traps": "Sur 10 tirs, deux paniers de plus ou de moins changent le TS% de 10 points.",
        "bench": [("player", "TS%", "pct"), ("team", "eFG%", "pct")],
    },
    {
        "title": "+/- (plus-moins)",
        "level": "avancé",
        "question": "Le score a-t-il évolué en faveur de l'équipe pendant que ce joueur jouait ?",
        "calc": "Points de l'équipe moins points de l'adversaire pendant que le joueur est sur le terrain. "
                "+/- hors = la même chose quand il est sur le banc. Les deux additionnés donnent l'écart "
                "final.",
        "read": "C'est un résultat d'équipe, pas une stat individuelle : il mesure les cinq joueurs, les "
                "cinq adversaires et un peu de chance. Utile pour repérer un joueur dont l'équipe s'effondre "
                "quand il sort, surtout sur plusieurs matchs.",
        "traps": "Un remplaçant qui joue la fin d'un match déjà gagné contre les remplaçants adverses aura "
                 "un +/- flatteur. Un titulaire d'une équipe qui perd souvent aura un +/- négatif même s'il "
                 "joue bien : comparer avec son +/- hors, et avec ses coéquipiers.",
    },
    {
        "title": "ORtg et DRtg sur le terrain, Net hors, On-Off",
        "level": "avancé",
        "question": "L'équipe est-elle meilleure avec ce joueur ou sans lui ?",
        "calc": "ORtg sur le terrain = 100 × points de l'équipe / possessions de l'équipe pendant qu'il "
                "joue ; DRtg sur le terrain = la même chose pour l'adversaire. Net = ORtg − DRtg. Net hors = "
                "le Net de l'équipe quand il est sur le banc. On-Off = Net − Net hors.",
        "read": "Un On-Off de +10, c'est 10 points par 100 possessions de mieux avec lui. On l'explique en "
                "regardant de quel côté vient l'écart : ORtg (l'attaque marque plus) ou DRtg (la défense "
                "accorde moins). C'est la mesure qui capte ce que le box score ignore : écrans, "
                "communication, défense sans interception.",
        "traps": "Le On-Off d'un titulaire est comparé aux minutes des remplaçants, et celui d'un "
                 "remplaçant aux minutes des titulaires : ce n'est pas symétrique. Deux joueurs qui jouent "
                 "toujours ensemble ont le même On-Off, impossible de les séparer. Sur une saison, il faut "
                 "plusieurs centaines de possessions dans chaque situation pour qu'il veuille dire quelque "
                 "chose.",
        "bench": [("player", "OnOff", "signed")],
    },
    {
        "title": "USG% (taux d'utilisation)",
        "level": "avancé",
        "question": "Quelle part des possessions le joueur termine-t-il lui-même ?",
        "calc": "(tirs + 0,44 × LF tentés + pertes) du joueur / la même somme pour l'équipe pendant qu'il "
                "joue. Cinq joueurs sur le terrain : la moyenne est donc 20 %.",
        "read": "Dans le haut de la fourchette de la ligue (voir repères), c'est une option principale de "
                "l'attaque ; dans le bas, un joueur de rôle. À croiser avec TS% : un USG% élevé avec un TS% "
                "faible signale un joueur qui prend trop de tirs difficiles, ou une attaque qui manque "
                "d'autres solutions.",
        "traps": "Ne compte pas les passes décisives : un meneur qui crée beaucoup pour les autres peut "
                 "avoir un USG% moyen. Lire PD% à côté.",
        "bench": [("player", "USG%", "pct")],
    },
    {
        "title": "PD%, BP% et PD/BP (création et soin du ballon)",
        "level": "avancé",
        "question": "Le joueur crée-t-il pour les autres, et à quel prix ?",
        "calc": "PD% = passes décisives / paniers des coéquipiers pendant qu'il joue. BP% = pertes / "
                "(tirs + 0,44 × LF + pertes) : part de ses actions qui finissent en perte. PD/BP = passes "
                "décisives par perte.",
        "read": "Un meneur créateur se situe dans le haut de la fourchette de PD% de la ligue ; un meneur "
                "près de la médiane crée peu pour son poste. Pour BP%, comparer à la médiane de la ligue : "
                "un meneur en a naturellement plus qu'un ailier, et un PD/BP au-dessus de 1 veut dire qu'il "
                "crée plus de paniers qu'il ne perd de ballons.",
        "traps": "La passe décisive dépend du marqueur (son panier doit suivre la passe) et du jugement du "
                 "marqueur officiel, qui varie d'une salle à l'autre.",
        "bench": [("player", "AST%", "pct"), ("player", "TOV%", "pct")],
    },
    {
        "title": "RO% et RD% (rebond)",
        "level": "avancé",
        "question": "Quelle part des rebonds disponibles le joueur prend-il ?",
        "calc": "RO% = rebonds offensifs / (rebonds offensifs de l'équipe + rebonds défensifs adverses) "
                "pendant qu'il joue. RD% = l'inverse en défense.",
        "read": "Corrige le nombre de rebonds par le nombre de tirs ratés : 8 rebonds dans un match à 40 % "
                "au tir valent moins que 8 rebonds dans un match à 55 %. Pour un intérieur, comparer avec "
                "les autres intérieurs de la ligue.",
        "traps": "Un joueur qui bloque son adversaire pour qu'un coéquipier prenne le rebond n'en est pas "
                 "crédité : le RD% de l'équipe sur le terrain (+/- et quintettes) le montre mieux.",
        "bench": [("player", "OREB%", "pct"), ("player", "DREB%", "pct"), ("team", "OREB%", "pct")],
    },
    {
        "title": "INT% et CTR%",
        "level": "avancé",
        "question": "Le joueur provoque-t-il des pertes ou des tirs contrés ?",
        "calc": "INT% = interceptions / possessions adverses pendant qu'il joue. CTR% = contres / tirs de "
                "2 points adverses pendant qu'il joue.",
        "read": "Mesure l'activité défensive visible, pas la qualité défensive : regarder aussi le DRtg sur "
                "le terrain.",
        "traps": "Chercher l'interception ou le contre fait parfois perdre sa position : un INT% élevé avec "
                 "un mauvais DRtg sur le terrain mérite une vidéo.",
        "bench": [("player", "STL%", "pct"), ("player", "BLK%", "pct")],
    },
    {
        "title": "Quintettes",
        "level": "avancé",
        "question": "Quels groupes de cinq fonctionnent ensemble ?",
        "calc": "Pour chaque combinaison de cinq joueurs : temps joué ensemble, possessions en attaque et en "
                "défense, points pour et contre, ratings.",
        "read": "La stat la plus directement utile pour les rotations, mais la plus sensible à "
                "l'échantillon : un quintette n'a de sens qu'avec beaucoup de minutes ensemble. Repérer les "
                "deux ou trois quintettes les plus utilisés et comparer leur Net.",
        "traps": "Les quintettes souffrent le plus des changements oubliés par la feuille : vérifier la "
                 "fiabilité des matchs concernés.",
    },
    {
        "title": "Game Score et EVAL",
        "level": "base",
        "question": "Un seul chiffre pour résumer le box score d'un joueur ?",
        "calc": "Game Score (Hollinger) = PTS + 0,4 paniers − 0,7 tirs − 0,4 LF ratés + 0,7 RO + 0,3 RD + "
                "INT + 0,7 PD + 0,7 CTR − 0,4 F − BP. EVAL (FIBA) = PTS + REB + PD + INT + CTR − tirs ratés "
                "− LF ratés − BP.",
        "read": "Utile pour classer les joueurs d'un même match ou d'une même équipe. Dans la NBA, 10 est un "
                "match moyen et 20 un excellent match ; au collégial, où les équipes marquent moins, les "
                "valeurs sont plus basses. EVAL est l'indice utilisé par la FIBA.",
        "traps": "Ces indices ne voient que le box score : rien sur la défense sans ballon, et une prime "
                 "aux joueurs qui tirent beaucoup.",
    },
    {
        "title": "Sources de points",
        "level": "base",
        "question": "Comment l'équipe marque-t-elle ?",
        "calc": "Raquette et contre-attaque : étiquettes [Pnt] et [FB] posées par le marqueur officiel. "
                "Deuxième chance : points après un rebond offensif, dans la même possession. Après balle "
                "perdue : points dans une possession commencée par une perte adverse. Banc : points des "
                "remplaçants.",
        "read": "À lire face à l'adversaire : une équipe battue en raquette et en deuxième chance perd la "
                "bataille physique ; beaucoup de points accordés après ses pertes signale des pertes vivantes "
                "(interceptions) plutôt que mortes (sorties, marchers).",
        "traps": "Raquette et contre-attaque dépendent du marqueur de chaque salle : les comparer d'un "
                 "match à l'autre avec prudence.",
    },
    {
        "title": "Rotations",
        "level": "base",
        "question": "Qui joue quand, et comment ça se passe ?",
        "calc": "Une ligne par joueur, une barre par présence sur le terrain, colorée selon le +/- de "
                "cette présence.",
        "read": "Montre la gestion des minutes : longues présences, retours en fin de match, joueurs "
                "utilisés seulement quand l'écart est fait.",
        "traps": "Les présences dépendent des changements notés ; voir Validation pour les corrections.",
    },
]


def bench_line(bench, scope, key, fmt):
    """« Ligue : médiane X ; 8 sur 10 entre A et B (N …) », ou rien si le repère manque."""
    b = (bench or {}).get(scope, {}).get(key)
    if not b:
        return ""
    med, p10, p90 = b["p50"], b["p10"], b["p90"]

    def f(x):
        if fmt == "pct":
            return f"{fr(100 * x)} %"
        if fmt == "signed":
            return f"{x:+.1f}".replace(".", ",")
        return fr(x)
    who = (f"{bench['n_players']} joueurs d'au moins {bench['min_minutes']} minutes" if scope == "player"
           else f"{bench['n_team_games']} matchs d'équipe")
    label = {"POSS": "possessions par match", "ORtg": "ORtg", "eFG%": "eFG%", "TOV%": "BP%", "OREB%": "RO%",
             "FTM/FGA": "LF/Tir", "TS%": "TS%", "OnOff": "On-Off", "USG%": "USG%", "AST%": "PD%",
             "DREB%": "RD%", "STL%": "INT%", "BLK%": "CTR%"}.get(key, key)
    return (f"<li><b>{esc(label)}</b> ({'joueurs' if scope == 'player' else 'équipes'}) : médiane {f(med)} ; "
            f"8 sur 10 entre {f(p10)} et {f(p90)} <span class=\"muted\">({esc(who)})</span></li>")


def annex_section(note="", bench=None, anchor="glossaire"):
    """Annexe : explication des stats et guide d'interprétation, avec les repères de la ligue s'il y en a."""
    out = [f'<h2 id="{anchor}">Annexe : comprendre et interpréter les stats</h2>']
    if note:
        out.append(f'<p class="note">{esc(note)}</p>')
    if bench:
        out.append(f'<p class="note">Repères : {esc(bench["label"])}, calculés par cet outil sur '
                   f'{bench["n_games"]} matchs avec play-by-play. « 8 sur 10 entre A et B » : 80 % des valeurs '
                   'sont dans cette fourchette (10e et 90e centiles).</p>')
    out.append('<p class="note">Survoler un titre de colonne affiche sa définition courte ; cliquer trie le '
               'tableau.</p><div class="guide">')
    for entry in GUIDE:
        reps = "".join(bench_line(bench, *b) for b in entry.get("bench", []))
        out.append(
            f'<details class="fiche"{" open" if entry["level"] == "base" and entry is GUIDE[0] else ""}>'
            f'<summary><span class="lvl {entry["level"]}">{esc(entry["level"])}</span> '
            f'{esc(entry["title"])}</summary><dl>'
            f'<dt>Question</dt><dd>{esc(entry["question"])}</dd>'
            f'<dt>Calcul</dt><dd>{esc(entry["calc"])}</dd>'
            f'<dt>Comment lire</dt><dd>{esc(entry["read"])}</dd>'
            f'<dt>Pièges</dt><dd>{esc(entry["traps"])}</dd>'
            + (f"<dt>Repères de la ligue</dt><dd><ul>{reps}</ul></dd>" if reps else "")
            + "</dl></details>")
    out.append("</div>")
    return "".join(out)


GUIDE_CSS = """
.guide{display:grid;gap:8px}
.fiche{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:8px 12px}
.fiche summary{cursor:pointer;font-weight:600;padding:4px 0}
.fiche dl{grid-template-columns:120px 1fr;margin:8px 0 4px}
.fiche dd ul{margin:0;padding-left:18px}
.lvl{font-size:.7rem;text-transform:uppercase;letter-spacing:.04em;padding:1px 7px;border-radius:8px;
vertical-align:1px}
.lvl.base{background:#EEF2F8;color:var(--navy2)}.lvl.avancé{background:#F5EEDC;color:var(--goldInk)}
@media (max-width:560px){.fiche dl{grid-template-columns:1fr}.fiche dt{margin-top:6px}}
"""
