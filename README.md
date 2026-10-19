# Stats_RSEQ : box score recalculé et stats avancées

Outil Python (bibliothèque standard seulement) qui lit une page de match de [rseq-stats.ca](https://www.rseq-stats.ca/), rejoue le play-by-play action par action et produit :

- le **box score recalculé**, comparé colonne par colonne au box score officiel de la même page ;
- le **+/-** de chaque joueur et ses **minutes** (déduites des entrées et sorties) ;
- les stats **sur le terrain / hors du terrain** (ORtg, DRtg, Net, On-Off) ;
- les **stats avancées individuelles** (eFG%, TS%, USG%, PD%, BP%, RO%, RD%, INT%, CTR%, Game Score, évaluation FIBA) ;
- les **quintettes** (temps, possessions, points pour et contre, ratings) ;
- les **rotations** (présences de chaque joueur, avec leur +/-) et l'**écart au score** dans le temps ;
- les **quatre facteurs** d'équipe, le rythme, l'origine des points (raquette, contre-attaque, deuxième chance, après une balle perdue, banc), changements de meneur, plus grande avance, plus longue série ;
- **qui sert qui** (passeur → marqueur).

Exemple : [`exemples/m001.html`](exemples/m001.html) (Montmorency 92 – Édouard-Montpetit 67, 2025-10-17), produit à partir de [`exemples/m001.htm`](exemples/m001.htm). Les mêmes données en JSON : [`exemples/m001.json`](exemples/m001.json).

## Commandes

```bash
python3 rseq_stats.py https://www.rseq-stats.ca/collegial/basketball-m-d1/stats/2526/m001.htm \
    -o rapport.html --json stats.json
python3 -m unittest                    # tests
```

La source peut être une URL ou une page enregistrée (`.htm`). Sans `-o`, l'outil affiche seulement le résumé et les écarts.

## Comment le match est rejoué

Le play-by-play StatCrew a trois colonnes : actions des locaux à gauche, chrono et score au centre, actions des visiteurs à droite.

1. **Ordre des actions.** Deux actions sur la même ligne sont remises dans l'ordre logique : faute avant lancers francs, tir avant rebond, changements à la fin.
2. **Joueurs sur le terrain.** Partants de la 1re période : les `*` du box score. Pour les périodes suivantes : les joueurs qui agissent (ou sortent) avant d'entrer, complétés par les joueurs présents à la fin de la période précédente. Ensuite, chaque `SUB IN` / `SUB OUT` met le quintette à jour.
3. **Possessions.** Une possession commence chaque fois que le ballon change de main : panier réussi, rebond défensif (d'un joueur ou d'équipe), balle perdue, dernier lancer franc réussi. Le rebond offensif prolonge la possession. Un lancer franc seul (*and-one*) ou un lancer franc de faute technique ne donne pas de nouvelle possession. La possession est attribuée aux quintettes présents à la première action qui suit (donc après les changements faits pendant l'arrêt de jeu).
4. **Crédits.** Chaque stat va au joueur nommé, à son équipe, à chaque joueur et quintette sur le terrain (« pour » son équipe, « contre » l'adversaire). Le +/- d'un joueur est la différence de points pendant qu'il est sur le terrain.

## Formules

« Sur le terrain » = pendant que le joueur joue. Les dénominateurs viennent du play-by-play, pas d'une estimation au prorata des minutes.

| Stat | Formule |
|---|---|
| eFG% | (paniers + 0,5 × paniers à 3) / tirs |
| TS% | points / (2 × (tirs + 0,44 × LF tentés)) |
| USG% | (tirs + 0,44 × LF + pertes) du joueur / mêmes actions de l'équipe sur le terrain |
| PD% | passes décisives / paniers des coéquipiers sur le terrain |
| BP% | pertes / (tirs + 0,44 × LF + pertes) |
| RO% / RD% | rebonds offensifs (défensifs) / rebonds offensifs (défensifs) disponibles sur le terrain |
| INT% | interceptions / possessions adverses sur le terrain |
| CTR% | contres / tirs de 2 points adverses sur le terrain |
| ORtg / DRtg | 100 × points marqués (accordés) / possessions sur le terrain |
| On-Off | Net sur le terrain − Net de l'équipe quand le joueur est sur le banc |
| Game Score | PTS + 0,4 PR − 0,7 TT − 0,4 LF ratés + 0,7 RO + 0,3 RD + INT + 0,7 PD + 0,7 CTR − 0,4 F − BP |
| EVAL (FIBA) | PTS + REB + PD + INT + CTR − tirs ratés − LF ratés − BP |
| Rythme | possessions par équipe × 40 / minutes jouées |
| Possessions estimées | tirs − rebonds offensifs + pertes + 0,44 × LF tentés (affichées pour contrôle) |

Deuxième chance : points marqués après un rebond offensif, dans la même possession. Après balle perdue : points marqués dans une possession commencée par une perte adverse. Raquette et contre-attaque : étiquettes `[Pnt]` et `[FB]` du play-by-play.

## Validation et limites

- **m001** : box score recalculé identique au box score officiel (toutes les colonnes, tous les joueurs ; minutes à ±1). La somme des +/- vaut 5 × l'écart final et les minutes totalisent 200 par équipe (tests).
- Essayé aussi sur m003, m010 et m025 : quelques écarts (rebonds défensifs, passes, minutes) que le play-by-play ne contient pas. Ils viennent de la feuille officielle, corrigée après coup ou saisie avec des erreurs ; le rapport les liste dans **Validation**.
- **Erreurs de la feuille de match.** Il arrive qu'un joueur soit crédité d'une action alors que les changements notés le placent sur le banc. Si son entrée est notée au plus 5 secondes plus tard (`SUB_TOLERANCE`), ses changements sont avancés au moment de l'action ; sinon, la stat lui reste créditée mais le +/- suit les changements notés, et l'incohérence est listée.
- **Changements pendant la pause** non écrits : les partants de la période sont déduits (voir plus haut) ; un joueur sans action ni changement pendant toute une période ne peut pas être détecté.
- **Un seul match, c'est peu.** Les ratings d'un joueur qui a joué quelques minutes, ou d'un quintette resté 30 secondes ensemble, reposent sur une poignée de possessions : lire d'abord le temps joué.
- Certaines pages (ex. m002) n'ont pas de play-by-play : rien à recalculer.
- Durée des périodes : 10 minutes (FIBA), prolongations de 5 minutes (`PERIOD_SECONDS`, `OT_SECONDS`).
