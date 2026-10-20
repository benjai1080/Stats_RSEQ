"""Lecture des feuilles de match XML PrestoSports (format du RSEQ depuis 2026-2027).

Depuis la saison 2026-2027, les feuilles de match ne sont plus des pages texte en colonnes :
le site de statistiques lit des fichiers XML PrestoSports (« bbgame »), un par match. Chaque
action y est un élément <play> avec la période, le chrono, l'équipe, le numéro, le nom et le
type d'action ; les changements (SUB IN / SUB OUT) y sont tous, alors que le site ne les
affiche qu'avec « Afficher les substitutions ».

Ce module traduit chaque action dans le texte du format StatCrew, que rseq_stats sait déjà
classer : le rejeu (quintettes, possessions, +/-…) reste le même pour les deux formats.
"""
import xml.etree.ElementTree as ET
from datetime import datetime

import rseq_stats as rs

# Colonnes du box score (rseq_stats.BOX_COLUMNS) -> attributs <stats> du XML
XML_STATS = {"FGM": "fgm", "FGA": "fga", "3PM": "fgm3", "3PA": "fga3", "FTM": "ftm", "FTA": "fta",
             "OREB": "oreb", "DREB": "dreb", "REB": "treb", "PF": "pf", "PTS": "tp", "AST": "ast",
             "TOV": "to", "BLK": "blk", "STL": "stl", "MIN": "min"}

SHOTS = {"JUMPER": "JUMPER", "3PTR": "3 PTR", "FT": "FT SHOT", "LAYUP": "LAYUP", "DUNK": "DUNK",
         "TIPIN": "TIP-IN", "HOOK": "HOOK"}


def to_int(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 0


def play_text(pl, name):
    """Texte StatCrew d'une action XML, ou None si l'action ne compte pas."""
    action, kind = pl.get("action", ""), pl.get("type") or ""
    if action in ("GOOD", "MISS"):
        shot = SHOTS.get(kind, kind or "JUMPER")
        tags = [t for t, attr in (("Pnt", "paint"), ("FB", "fastb")) if pl.get(attr) == "Y"]
        suffix = f" [{'/'.join(tags)}]" if tags else ""
        return f"{'GOOD!' if action == 'GOOD' else 'MISSED'} {shot} by {name}{suffix}"
    if action == "REBOUND":
        if kind == "DEADB":
            return "REBOUND (OFF) by (DEADBALL)"
        return f"REBOUND ({'OFF' if kind == 'OFF' else 'DEF'}) by {name}"
    if action == "SUB":
        return f"SUB IN : {name}" if kind == "IN" else f"SUB OUT: {name}"
    if action == "TIMEOUT":
        return f"TIMEOUT {kind or 'FULL'} by (TEAM)"
    if action == "FOUL" and kind.upper().startswith("TECH"):
        return f"FOUL TE TECHNCL by {name}"
    simple = {"ASSIST": "ASSIST", "TURNOVER": "TURNOVR", "STEAL": "STEAL", "BLOCK": "BLOCK", "FOUL": "FOUL"}
    if action in simple:
        return f"{simple[action]} by {name}"
    return f"{action} {kind} by {name}".strip()


def parse_xml(source, names=None):
    """Lit une feuille XML. `names` : {'V': nom, 'H': nom} pour remplacer les noms longs du XML
    (« Cégep Édouard-Montpetit ») par ceux du calendrier (« Édouard-Montpetit »).

    Retourne (teams, meta, events, n_periods), comme les fonctions du format texte.
    """
    root = ET.fromstring(rs.load_source(source).encode("utf-8")) if not hasattr(source, "tag") else source
    names = names or {}
    teams, by_uni = {}, {}
    for t in root.findall("team"):
        side = rs.VIS if t.get("vh") == "V" else rs.HOME
        team = teams[side] = rs.Team(side, names.get(side) or t.get("name", side))
        used = set()
        for p in t.findall("player"):
            uni = p.get("uni", "")
            if uni == "TM":
                continue
            stats = p.find("stats")
            official = {k: to_int(stats.get(a)) for k, a in XML_STATS.items()} if stats is not None else \
                {k: 0 for k in XML_STATS}
            name = (p.get("name") or p.get("checkname") or uni).strip()
            if rs.norm(name) in used:                    # deux joueurs au même nom : on ajoute le numéro
                name = f"{name} #{uni}"
            used.add(rs.norm(name))
            player = rs.Player(side, uni, name, p.get("gs") == "1", official)
            team.players[player.key] = player
            by_uni[(side, uni)] = player
            by_uni[(side, (p.get("checkname") or "").upper())] = player
        totals = t.find("totals/stats")
        if totals is not None:
            team.official_totals = {k: to_int(totals.get(a)) for k, a in XML_STATS.items()}
        line = t.find("linescore")
        if line is not None and line.get("line"):
            team.official_periods = [to_int(x) for x in line.get("line").split(",")]

    venue = root.find("venue")
    meta = {}
    if venue is not None:
        try:
            meta["date"] = datetime.strptime(venue.get("date", ""), "%m/%d/%Y").date().isoformat()
        except ValueError:
            meta["date"] = venue.get("date", "")
        meta["site"] = venue.get("location", "")
        if to_int(venue.get("attend")):
            meta["attendance"] = to_int(venue.get("attend"))

    events = []
    periods = root.findall("plays/period")
    for per in periods:
        period = to_int(per.get("number")) or len(events) + 1
        for pl in per.iter("play"):
            side = rs.VIS if pl.get("vh") == "V" else rs.HOME
            uni = pl.get("uni", "")
            if uni == "TM" or (pl.get("checkname") or "").upper() == "TEAM":
                name = "(TEAM)"
            else:
                player = by_uni.get((side, uni)) or by_uni.get((side, (pl.get("checkname") or "").upper()))
                name = player.name if player else (pl.get("checkname") or uni)
            text = play_text(pl, name)
            if not text:
                continue
            score = None
            if pl.get("vscore") is not None and pl.get("hscore") is not None:
                score = {rs.VIS: to_int(pl.get("vscore")), rs.HOME: to_int(pl.get("hscore"))}
            ev = rs.Event(period, rs.clock(pl.get("time", "00:00")), side, text, None)
            rs.classify(ev)
            if ev.made:
                ev.score = score
            events.append(ev)
    for i, ev in enumerate(events):
        ev.idx = i
    return teams, meta, events, len(periods)


def analyse_xml(source, names=None, url=""):
    teams, meta, events, n_periods = parse_xml(source, names)
    if not events:
        raise SystemExit("Cette feuille XML n'a pas de jeu par jeu : rien à recalculer.")
    game = rs.Game(teams, meta, events, n_periods, url or str(source))
    return game.run()
