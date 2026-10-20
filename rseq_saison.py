#!/usr/bin/env python3
"""Saison complète d'une équipe RSEQ : chaque match rejoué, puis cumulé dans un seul rapport HTML.

Le rapport s'ouvre sur le total de la saison ; une liste déroulante affiche chaque match.
Les matchs sont trouvés en parcourant les pages m001, m002… de la saison (la page d'index du
site est fermée) et gardés dans un dossier cache pour ne pas les retélécharger.

Sources : les stats de base de la saison (points, rebonds, minutes…) viennent des box scores
officiels, parfois corrigés après le match. Tout ce qui demande de savoir qui était sur le
terrain (+/-, on/off, ratings, quintettes, USG%…) vient du play-by-play rejoué.

Usage :
  python3 rseq_saison.py "Edouard-Montpetit" [-o saison.html] [--json saison.json]
      [--ligue collegial/basketball-m-d1] [--saison 2526] [--cache .cache]
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import rseq_stats as rs
from rseq_guide import annex_section
from rseq_rapport import (View, assists_section, efficiency_section, esc, game_body, game_header,
                          impact_section, lineups_section, made, num, page, pct, shots_section, signed,
                          split_diffs, table, tagged, tone, with_games)

BASE = "https://www.rseq-stats.ca/{ligue}/stats/{saison}/m{n:03d}.htm"
SEASON_SIDE, OPP_SIDE = rs.HOME, rs.VIS     # côtés fictifs de l'équipe cumulée et de ses adversaires


# ---------------------------------------------------------------------------
# Matchs de la saison

def fetch_pages(ligue, saison, cache, max_miss=5, delay=0.3):
    """Télécharge m001, m002… jusqu'à `max_miss` pages absentes de suite. Retourne {code: (fichier, url)}."""
    folder = Path(cache) / ligue.replace("/", "_") / saison
    folder.mkdir(parents=True, exist_ok=True)
    pages, miss, n = {}, 0, 0
    while miss < max_miss:
        n += 1
        code, url = f"m{n:03d}", BASE.format(ligue=ligue, saison=saison, n=n)
        path = folder / f"{code}.htm"
        if not path.exists():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Stats_RSEQ"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    path.write_bytes(resp.read())
            except urllib.error.HTTPError as err:
                if err.code != 404:
                    raise
                miss += 1
                continue
            time.sleep(delay)
        miss = 0
        pages[code] = (path, url)
    return pages


def page_title(path):
    text = rs.load_source(str(path))
    m = re.search(r"<title>(.*?)</title>", text, re.S | re.I)
    return m.group(1).strip() if m else ""


def team_games(pages, team=None):
    """Rejoue les matchs de l'équipe (ou tous) qui ont un play-by-play. Retourne [(code, game, côté)] et les ignorés.

    Sans équipe, chaque match revient deux fois, une par côté.
    """
    games, skipped = [], []
    key = rs.norm(team) if team else None
    for code, (path, url) in sorted(pages.items()):
        title = page_title(path)
        if key and key not in rs.norm(title):
            continue
        try:
            game = rs.analyse(str(path))
        except SystemExit as err:
            skipped.append((code, title, str(err)))
            continue
        game.source = url
        sides = [s for s in rs.SIDES if key is None or rs.norm(game.teams[s].name) == key]
        if not sides:
            skipped.append((code, title, "équipe introuvable dans le box score"))
            continue
        games.extend((code, game, side) for side in sides)
    return games, skipped


# ---------------------------------------------------------------------------
# Repères de la ligue

def quantile(values, q):
    v = sorted(values)
    if not v:
        return None
    pos = (len(v) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


TEAM_KEYS = ["POSS", "ORtg", "eFG%", "TOV%", "OREB%", "FTM/FGA", "TS%"]
PLAYER_KEYS = ["TS%", "USG%", "AST%", "TOV%", "OREB%", "DREB%", "STL%", "BLK%", "OnOff", "Net"]


def league_benchmarks(all_games, label, min_minutes=100):
    """Médiane et 10e/90e centiles par match d'équipe et par joueur-saison (au moins `min_minutes`)."""
    team_vals = defaultdict(list)
    by_team = defaultdict(list)
    codes = set()
    for code, game, side in all_games:
        codes.add(code)
        t, o = game.teams[side], game.teams[rs.other(side)]
        line = game_line_boxes(t.box, o.box)
        line["POSS"] = t.box["POSS"]
        line["TS%"] = rs.shooting(t.box)["TS%"]
        for k in TEAM_KEYS:
            if line.get(k) is not None:
                team_vals[k].append(line[k])
        by_team[rs.norm(t.name)].append((code, game, side))
    player_vals = defaultdict(list)
    n_players = 0
    for games in by_team.values():
        season = Season(games[0][1].teams[games[0][2]].name, games)
        for key, p in season.team.players.items():
            if season.official[key]["MIN"] < min_minutes:
                continue
            n_players += 1
            adv = rs.player_advanced(p, season.team, season.opp)
            for k in PLAYER_KEYS:
                if adv.get(k) is not None:
                    player_vals[k].append(adv[k])

    def summary(vals):
        return {k: {"p10": quantile(v, .1), "p50": quantile(v, .5), "p90": quantile(v, .9), "n": len(v)}
                for k, v in vals.items()}
    return {"label": label, "n_games": len(codes), "n_team_games": len(team_vals["ORtg"]),
            "n_players": n_players, "min_minutes": min_minutes,
            "team": summary(team_vals), "player": summary(player_vals)}


# ---------------------------------------------------------------------------
# Noms : une même personne s'écrit parfois « Dumont », « Keysean Dumont » ou « Bukovesan »

def close(a, b):
    """Noms de famille égaux, ou à une lettre près pour les noms d'au moins 6 lettres."""
    if a == b:
        return True
    if min(len(a), len(b)) < 6 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def build_aliases(games):
    """Clé normalisée -> clé canonique. Un nom seul ou mal orthographié rejoint le nom complet proche."""
    keys = Counter()
    for _, game, side in games:
        for p in game.teams[side].players.values():
            keys[p.key] += 1
    full = [k for k in keys if len(k.split()) >= 2]
    alias = {}
    for k in keys:
        last = k.split()[-1]
        cands = [f for f in full if f != k and close(f.split()[-1], last)
                 and (len(k.split()) == 1 or f.split()[0] == k.split()[0])]
        alias[k] = max(cands, key=lambda f: keys[f]) if len(cands) == 1 or (cands and len(k.split()) > 1) else k
    return alias


# ---------------------------------------------------------------------------
# Cumul

class SeasonGame:
    """Le rejeu d'un match, vu par l'équipe suivie."""

    def __init__(self, code, game, side):
        self.code, self.game, self.side = code, game, side
        self.team, self.opp = game.teams[side], game.teams[rs.other(side)]
        self.pts, self.opp_pts = game.score[side], game.score[rs.other(side)]
        # Résultat officiel du RSEQ (calendrier) : il prime sur le score rejoué de la feuille.
        official = getattr(game, "official_score", None)
        self.score_differs = bool(official) and official != game.score
        if official:
            self.pts, self.opp_pts = official[side], official[rs.other(side)]
        self.home = side == rs.HOME
        self.win = self.pts > self.opp_pts
        self.date = game.meta.get("date", "")

    def label(self):
        lieu = "vs" if self.home else "à"
        res = "V" if self.win else "D"
        return f"{self.date} · {lieu} {self.opp.name} · {res} {self.pts}-{self.opp_pts}"


class Season:
    def __init__(self, team_name, games, skipped=()):
        self.games = [SeasonGame(*g) for g in sorted(games, key=lambda g: g[1].meta.get("date", ""))]
        self.skipped = list(skipped)
        self.name = self.games[0].team.name if self.games else team_name
        self.alias = build_aliases(games)
        self.team = rs.Team(SEASON_SIDE, self.name)
        self.opp = rs.Team(OPP_SIDE, "Adversaires")
        self.official = defaultdict(Counter)   # clé -> stats officielles cumulées
        self.gp, self.gs = Counter(), Counter()
        self.numbers = defaultdict(set)
        self.names = defaultdict(Counter)      # clé canonique -> orthographes rencontrées
        self.lineups = {}
        self.assists = Counter()
        self.bench = 0
        self.timeouts = 0
        self.seconds = 0.0
        for g in self.games:
            self.add(g)
        for key, p in self.team.players.items():
            # Orthographe la plus fréquente parmi celles du nom canonique (pas « Dumont » seul).
            same = [n for n, _ in self.names[key].most_common() if rs.norm(n) == key]
            p.name = same[0] if same else self.names[key].most_common(1)[0][0]
            p.num = "/".join(sorted(self.numbers[key]))

    def player(self, p):
        key = self.alias.get(p.key, p.key)
        self.names[key][p.name] += 1
        sp = self.team.players.get(key)
        if sp is None:
            sp = self.team.players[key] = rs.Player(SEASON_SIDE, p.num, p.name)
        return key, sp

    def add(self, g):
        t, o = g.team, g.opp
        self.team.box.update(t.box)
        self.team.team_box.update(t.team_box)
        self.opp.box.update(o.box)
        self.seconds += g.game.game_seconds
        self.timeouts += g.game.timeouts[g.side]
        for p in t.players.values():
            played = p.seconds > 0 or (p.official and p.official.get("MIN", 0) > 0)
            if not played and not sum(p.box.values()):
                continue
            key, sp = self.player(p)
            sp.box.update(p.box)
            sp.on_tm.update(p.on_tm)
            sp.on_op.update(p.on_op)
            sp.seconds += p.seconds
            if p.official:
                self.official[key].update(p.official)
            self.gp[key] += 1
            self.gs[key] += p.starter
            self.numbers[key].add(p.num)
            if not p.starter:
                self.bench += p.box["PTS"]
        for lu in g.game.lineups[g.side].values():
            keys = frozenset(self.alias.get(q.key, q.key) for q in lu.players)
            slu = self.lineups.get(keys)
            if slu is None:
                slu = self.lineups[keys] = rs.Lineup(SEASON_SIDE, [self.team.players[k] for k in keys
                                                                   if k in self.team.players])
            slu.seconds += lu.seconds
            slu.on_tm.update(lu.on_tm)
            slu.on_op.update(lu.on_op)
        for (sd, a, s), n in g.game.assists.items():
            if sd == g.side:
                self.assists[(self.alias.get(a, a), self.alias.get(s, s))] += n

    def view(self):
        for slu in self.lineups.values():   # joueurs triés par numéro, une fois les numéros connus
            slu.players.sort(key=lambda p: (p.num.split("/")[0], p.name))
        return View(self.team, self.opp, list(self.lineups.values()),
                    [(n, a, s) for (a, s), n in self.assists.items()], games=self.gp)

    def record(self, games=None):
        games = self.games if games is None else games
        w = sum(g.win for g in games)
        return w, len(games) - w

    def team_numbers(self):
        b, ob = self.team.box, self.opp.box
        minutes = self.seconds / 60
        out = rs.shooting(b)
        out.update({
            "POSS": b["POSS"], "PACE": rs.div((b["POSS"] + ob["POSS"]) / 2 * 40, minutes),
            "ORtg": rs.div(100 * b["PTS"], b["POSS"]), "DRtg": rs.div(100 * ob["PTS"], ob["POSS"]),
            "TOV%": rs.div(b["TOV"], b["POSS"]), "OREB%": rs.div(b["OREB"], b["OREB"] + ob["DREB"]),
            "DREB%": rs.div(b["DREB"], b["DREB"] + ob["OREB"]), "FTM/FGA": rs.div(b["FTM"], b["FGA"]),
            "AST_RATIO": rs.div(b["AFGM"], b["FGM"]),
        })
        out["Net"] = out["ORtg"] - out["DRtg"] if out["ORtg"] is not None and out["DRtg"] is not None else None
        return out


# ---------------------------------------------------------------------------
# Rapport

def game_line(g):
    """Indicateurs d'un match pour le tableau des résultats."""
    return game_line_boxes(g.team.box, g.opp.box)


def game_line_boxes(b, ob):
    o = rs.div(100 * b["PTS"], b["POSS"])
    d = rs.div(100 * ob["PTS"], ob["POSS"])
    return {"ORtg": o, "DRtg": d, "eFG%": rs.div(b["FGM"] + 0.5 * b["3PM"], b["FGA"]),
            "TOV%": rs.div(b["TOV"], b["POSS"]), "OREB%": rs.div(b["OREB"], b["OREB"] + ob["DREB"]),
            "FTM/FGA": rs.div(b["FTM"], b["FGA"])}


def reliability(g):
    stats, mins = split_diffs(g.game)
    level = "ok" if len(stats) <= 4 and len(g.game.repairs) <= 15 else "bof" if len(stats) <= 20 else "bad"
    label = {"ok": "bonne", "bof": "moyenne", "bad": "faible"}[level]
    tip = (f"{len(stats)} écart(s) de stats avec le box officiel, {len(mins)} écart(s) de minutes, "
           f"{len(g.game.repairs)} correction(s) de quintette")
    return f'<span class="rel {level}" title="{esc(tip)}">{label}</span>', level


def results_section(season):
    heads = [("Date", ""), ("Adversaire", ""), ("Lieu", ""), ("Résultat", ""), ("Écart", ""),
             ("POSS", "Possessions de l'équipe"), ("ORtg", "Points marqués par 100 possessions"),
             ("DRtg", "Points accordés par 100 possessions"), ("eFG%", "Pourcentage effectif au tir"),
             ("BP%", "Balles perdues par possession"), ("RO%", "Rebonds offensifs captés / disponibles"),
             ("LF/Tir", "Lancers francs réussis par tir"), ("Meilleur marqueur", ""),
             ("Fiabilité", "Accord du play-by-play avec le box score officiel")]
    rows = []
    for g in season.games:
        x = game_line(g)
        top = max(g.team.players.values(), key=lambda p: (p.official or {}).get("PTS", p.box["PTS"]))
        top_pts = (top.official or {}).get("PTS", top.box["PTS"])
        top = season.team.players.get(season.alias.get(top.key, top.key), top)
        margin = g.pts - g.opp_pts
        rel, level = reliability(g)
        rows.append([(esc(g.date), "", g.date),
                     (f'<a href="#{g.code}">{esc(g.opp.name)}</a>', "name", g.opp.name),
                     "domicile" if g.home else "extérieur",
                     (f'{"V" if g.win else "D"} {g.pts}-{g.opp_pts}', "pos" if g.win else "neg", margin),
                     (signed(margin), tone(margin), margin), g.team.box["POSS"],
                     num(x["ORtg"]), num(x["DRtg"]), pct(x["eFG%"]), pct(x["TOV%"]), pct(x["OREB%"]),
                     pct(x["FTM/FGA"]), (f"{esc(top.name)} ({top_pts})", "name", top_pts),
                     (rel, "", level)])
    return table(heads, rows)


def margins_chart(season):
    """Écart final de chaque match, en barres."""
    games = season.games
    W, H, PAD_T, PAD_B, PAD_L = 900, 220, 14, 46, 30
    top = max([5] + [abs(g.pts - g.opp_pts) for g in games])
    top = (top + 4) // 5 * 5
    step = (W - PAD_L - 10) / max(1, len(games))

    def y(m):
        return PAD_T + (H - PAD_T - PAD_B) * (top - m) / (2 * top)

    parts = []
    for m in range(-top, top + 1, 10 if top > 20 else 5):
        parts.append(f'<line x1="{PAD_L}" x2="{W - 10}" y1="{y(m):.1f}" y2="{y(m):.1f}" '
                     f'class="{"zero" if m == 0 else "grid"}"/><text x="{PAD_L - 4}" y="{y(m) + 3:.1f}" '
                     f'class="tick" text-anchor="end">{m:+d}</text>'.replace("+0<", "0<"))
    for i, g in enumerate(games):
        m = g.pts - g.opp_pts
        x0 = PAD_L + i * step + step * 0.18
        w = step * 0.64
        y0, y1 = sorted((y(0), y(m)))
        tip = f"{g.label()}"
        parts.append(f'<a href="#{g.code}"><rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" '
                     f'height="{max(1, y1 - y0):.1f}" rx="3" class="stint {"pos" if m > 0 else "neg"}">'
                     f"<title>{esc(tip)}</title></rect></a>")
        short = re.sub(r"[^A-Za-zÀ-ÿ]", "", g.opp.name)[:6]
        parts.append(f'<text x="{x0 + w / 2:.1f}" y="{H - PAD_B + 14}" class="tick" text-anchor="middle">'
                     f'{esc(g.date[5:])}</text>'
                     f'<text x="{x0 + w / 2:.1f}" y="{H - PAD_B + 27}" class="tick" text-anchor="middle">'
                     f'{"" if g.home else "@"}{esc(short)}</text>')
    return (f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Écart final de chaque match">'
            + "".join(parts) + '</svg><p class="note">@ : match à l\'extérieur.</p>')


def team_table(season, bench=None):
    a = season.team_numbers()
    league = (bench or {}).get("team", {})
    b, ob = season.team.box, season.opp.box
    n = len(season.games)

    def row(label, tip, mine, theirs, higher=True, fmt=pct, lkey=None):
        cls = ["", ""]
        if mine is not None and theirs is not None and mine != theirs and higher is not None:
            best = (mine > theirs) == higher
            cls = ["best", ""] if best else ["", "best"]
        lg = league.get(lkey, {}).get("p50") if lkey else None
        return (f'<tr><th title="{esc(tip)}">{esc(label)}</th><td class="{cls[0]}">{fmt(mine)}</td>'
                f'<td class="{cls[1]}">{fmt(theirs)}</td><td class="muted">{fmt(lg) if lg is not None else ""}'
                f"</td></tr>")

    def avg(x):
        return num(x / n) if n else "–"

    o = rs.shooting(ob)
    ox = {"TOV%": rs.div(ob["TOV"], ob["POSS"]), "OREB%": rs.div(ob["OREB"], ob["OREB"] + b["DREB"]),
          "FTM/FGA": rs.div(ob["FTM"], ob["FGA"]), "AST_RATIO": rs.div(ob["AFGM"], ob["FGM"])}
    lines = [
        row("Points par match", "", b["PTS"] / n, ob["PTS"] / n, fmt=num),
        row("Possessions par match", "", b["POSS"] / n, ob["POSS"] / n, fmt=num, higher=None, lkey="POSS"),
        row("ORtg", "Points marqués par 100 possessions", a["ORtg"], a["DRtg"], fmt=num, lkey="ORtg"),
        '<tr class="sep"><th colspan="4">Quatre facteurs (Dean Oliver)</th></tr>',
        row("eFG%", "Pourcentage effectif au tir", a["eFG%"], o["eFG%"], lkey="eFG%"),
        row("BP%", "Balles perdues par possession", a["TOV%"], ox["TOV%"], higher=False, lkey="TOV%"),
        row("RO%", "Rebonds offensifs captés / disponibles", a["OREB%"], ox["OREB%"], lkey="OREB%"),
        row("LF/Tir", "Lancers francs réussis par tir", a["FTM/FGA"], ox["FTM/FGA"], lkey="FTM/FGA"),
        '<tr class="sep"><th colspan="4">Tir</th></tr>',
        row("Tir %", "", a["FG%"], o["FG%"]), row("3 pts %", "", a["3P%"], o["3P%"]),
        row("LF %", "", a["FT%"], o["FT%"]), row("TS%", "Tir vrai", a["TS%"], o["TS%"], lkey="TS%"),
        row("Part de 3 pts", "Tirs de 3 / tirs", a["3PAr"], o["3PAr"], higher=None),
        row("Paniers assistés", "", a["AST_RATIO"], ox["AST_RATIO"]),
        '<tr class="sep"><th colspan="4">D\'où viennent les points (par match)</th></tr>',
    ] + ([
        row("Dans la raquette", "", b["PNT"] / n, ob["PNT"] / n, fmt=num),
        row("Contre-attaque", "", b["FB"] / n, ob["FB"] / n, fmt=num),
    ] if tagged(b, ob) else []) + [
        row("Deuxième chance", "", b["2CH"] / n, ob["2CH"] / n, fmt=num),
        row("Après une balle perdue adverse", "", b["PTO"] / n, ob["PTO"] / n, fmt=num),
    ]
    head = (f'<div class="scroll"><table class="team"><thead><tr><th></th><th>{esc(season.name)}</th>'
            f'<th>Adversaires</th><th title="Médiane des matchs d\'équipe de la ligue">Ligue</th></tr></thead><tbody>')
    note = (f'<p class="note">Rythme : {num(a["PACE"])} possessions par 40 minutes · banc : '
            f'{avg(season.bench)} points par match · temps morts : {avg(season.timeouts)} par match.</p>')
    return head + "".join(lines) + "</tbody></table></div>" + note


def official_tables(season):
    """Stats de base cumulées des box scores officiels : moyennes par match et totaux."""
    players = sorted(season.team.players.items(), key=lambda kv: -season.official[kv[0]]["MIN"])
    heads_avg = [("Joueur", ""), ("MJ", "Matchs joués"), ("TIT", "Matchs commencés"), ("MIN", "Minutes par match"),
                 ("PTS", "Points par match"), ("REB", "Rebonds par match"), ("RO", "Rebonds offensifs"),
                 ("PD", "Passes décisives"), ("BP", "Balles perdues"), ("INT", "Interceptions"),
                 ("CTR", "Contres"), ("F", "Fautes"), ("TIR%", "Paniers / tirs"), ("3PTS%", ""),
                 ("LF%", ""), ("TS%", "Tir vrai")]
    rows_avg, rows_tot = [], []
    for key, p in players:
        o, gp = season.official[key], season.gp[key]
        if not gp:
            continue
        sh = rs.shooting(o)
        name = (f'<span class="num">{esc(p.num)}</span> {esc(p.name)}', "name", p.name)

        def per(k):
            return (num(o[k] / gp), "", o[k] / gp)
        rows_avg.append(with_games([name, gp, season.gs[key], per("MIN"), per("PTS"), per("REB"), per("OREB"),
                                    per("AST"), per("TOV"), per("STL"), per("BLK"), per("PF"),
                                    pct(sh["FG%"]), pct(sh["3P%"]), pct(sh["FT%"]), pct(sh["TS%"])], gp))
        rows_tot.append(with_games([name, gp, o["MIN"], o["PTS"], (made(o["FGM"], o["FGA"]), "", o["FGM"]),
                                    (made(o["3PM"], o["3PA"]), "", o["3PM"]),
                                    (made(o["FTM"], o["FTA"]), "", o["FTM"]), o["OREB"], o["DREB"], o["REB"],
                                    o["AST"], o["TOV"], o["STL"], o["BLK"], o["PF"]], gp))
    heads_tot = [("Joueur", ""), ("MJ", ""), ("MIN", ""), ("PTS", ""), ("TIR", ""), ("3PTS", ""), ("LF", ""),
                 ("RO", ""), ("RD", ""), ("REB", ""), ("PD", ""), ("BP", ""), ("INT", ""), ("CTR", ""), ("F", "")]
    return ("<h3>Moyennes par match</h3>" + table(heads_avg, rows_avg)
            + "<h3>Totaux</h3>" + table(heads_tot, rows_tot))


def reliability_section(season):
    rows = []
    for g in season.games:
        stats, mins = split_diffs(g.game)
        rel, level = reliability(g)
        xml = g.game.score
        score_note = (f'{xml[g.side]}-{xml[rs.other(g.side)]} ≠ officiel' if g.score_differs else "identique")
        rows.append([(f'<a href="#{g.code}">{esc(g.label())}</a>', "name", g.date), len(stats), len(mins),
                     len(g.game.repairs), len(g.game.corrections),
                     (score_note, "neg" if g.score_differs else "", int(g.score_differs)), (rel, "", level)])
    out = [table([("Match", ""), ("Écarts de stats", "Avec le box score officiel"),
                  ("Écarts de minutes", "Plus d'une minute"), ("Quintettes corrigés", ""),
                  ("Changements avancés", ""),
                  ("Score de la feuille", "Score rejoué à partir de la feuille, comparé au résultat officiel"),
                  ("Fiabilité", "")], rows)]
    if any(g.score_differs for g in season.games):
        out.append('<p class="note">Quand le score de la feuille diffère du résultat officiel du RSEQ, le '
                   'résultat officiel est affiché ; les stats du match viennent quand même de la feuille, '
                   'à laquelle il manque alors des points.</p>')
    merged = defaultdict(list)
    for k, canon in season.alias.items():
        if k != canon:
            merged[canon].append(k)
    if merged:
        out.append("<h4>Noms regroupés</h4><p class=\"note\">Le même joueur est écrit différemment selon "
                   "les feuilles.</p><ul>" + "".join(
                       f"<li>{esc(season.team.players[c].name)} ← {esc(', '.join(sorted(v)))}</li>"
                       for c, v in merged.items() if c in season.team.players) + "</ul>")
    if season.skipped:
        out.append("<h4>Matchs non rejoués</h4><ul>" + "".join(
            f"<li>{esc(code)} · {esc(title)} : {esc(why)}</li>" for code, title, why in season.skipped)
            + "</ul>")
    return "".join(out)


SEASON_CSS = """
.picker{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-top:12px}
.picker label{color:#C9D3E3;font-size:.85rem}
.picker select{font:inherit;font-size:.95rem;padding:6px 10px;border-radius:8px;border:1px solid var(--gold);
background:#fff;color:var(--navy);max-width:100%}
.gamehead{background:var(--navy2);color:#fff;border-radius:10px;padding:12px 14px;margin-top:14px}
.gamehead .t{font-size:1.2rem}.gamehead .n{font-size:1.6rem}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:14px 0}
.cards div{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.cards b{display:block;font-size:1.5rem;font-stretch:condensed}
.cards span{color:var(--muted);font-size:.8rem}
.rel{font-size:.78rem;padding:2px 8px;border-radius:10px;font-weight:600}
.rel.ok{background:#E7F3EC;color:var(--keep)}.rel.bof{background:#FBF1E6;color:var(--goldInk)}
.rel.bad{background:#F8E5E1;color:var(--drop)}
.filtre{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;margin:12px 0 0}
.filtre button{font:inherit;font-size:.88rem;padding:6px 12px;border-radius:16px;cursor:pointer;
border:1px solid var(--navy2);background:var(--surface);color:var(--navy2)}
.filtre button[aria-pressed="true"]{background:var(--navy2);color:#fff}
.filtre span{font-size:.8rem}
"""

FEW_GAMES = 2      # le bouton de filtre masque les joueurs qui ont joué ce nombre de matchs ou moins

SEASON_JS = """
(function(){
  var btn=document.getElementById('filtre-mj');
  function filtre(on){
    var max=+btn.dataset.max;
    document.querySelectorAll('section.vue[data-vue="saison"] tr[data-mj]').forEach(function(tr){
      tr.hidden=on&&+tr.dataset.mj<=max;
    });
    btn.setAttribute('aria-pressed',on?'true':'false');
    btn.textContent=(on?'Afficher':'Masquer')+' les joueurs de '+max+' matchs ou moins';
    try{localStorage.setItem('filtre-mj',on?'1':'0')}catch(e){}
  }
  btn.addEventListener('click',function(){filtre(btn.getAttribute('aria-pressed')!=='true')});
  try{if(localStorage.getItem('filtre-mj')==='1')filtre(true)}catch(e){}
})();
(function(){
  var sel=document.getElementById('vue');
  function show(v){
    document.querySelectorAll('section.vue').forEach(function(s){s.hidden=s.dataset.vue!==v});
    sel.value=v;
  }
  function fromHash(){
    var h=decodeURIComponent(location.hash.slice(1)), v=h.split('-')[0]||'saison';
    if(!document.querySelector('section.vue[data-vue="'+v+'"]')) v='saison';
    show(v);
    var el=h&&h!==v?document.getElementById(h):null;
    if(el) el.scrollIntoView(); else window.scrollTo(0,0);
  }
  sel.addEventListener('change',function(){location.hash=sel.value});
  window.addEventListener('hashchange',fromHash);
  fromHash();
})();
"""


def upcoming_section(upcoming):
    """Matchs à venir de l'équipe : [{date, heure, adversaire, domicile, lieu}]."""
    if not upcoming:
        return ""
    rows = [[(esc(m["date"]), "", m["date"]), esc(m.get("heure", "")),
             (esc(m["adversaire"]), "name", m["adversaire"]), "domicile" if m["domicile"] else "extérieur",
             (esc(m.get("lieu", "")), "name", m.get("lieu", ""))] for m in upcoming]
    return ("<h3>À venir</h3>" + table([("Date", ""), ("Heure", ""), ("Adversaire", ""), ("Lieu", ""),
                                         ("Salle", "")], rows, sortable=False))


def render_season(season, saison_label, bench=None, quintettes=True, upcoming=(), extra_header="",
                  intro=""):
    w, l = season.record()
    home = [g for g in season.games if g.home]
    away = [g for g in season.games if not g.home]
    a = season.team_numbers()
    n = len(season.games)
    options = [f'<option value="saison">Saison complète · {n} match{"s" if n > 1 else ""} · {w} V – {l} D</option>']
    options += [f'<option value="{g.code}">{esc(g.label())}</option>' for g in season.games]
    header = (f"<h1>{esc(season.name)} · saison {esc(saison_label)}</h1>"
              f'<div class="score"><span class="t">Fiche</span><span class="n">{w}-{l}</span></div>'
              f'<div class="picker"><label for="vue">Afficher</label><select id="vue">{"".join(options)}'
              f"</select></div>{extra_header}")
    v = season.view()
    body = ['<section class="vue" data-vue="saison">']
    nav = [("bilan", "Bilan"), ("resultats", "Résultats"), ("equipe", "Équipe"), ("joueurs", "Joueurs"),
           ("impact", "Impact"), ("quintettes", "Quintettes") if quintettes else ("passes", "Passes"),
           ("fiabilite", "Fiabilité"), ("annexe", "Annexe")]
    body.append("<nav>" + "".join(f'<a href="#saison-{x}">{esc(y)}</a>' for x, y in nav) + "</nav>")
    few = sum(1 for k in season.team.players if season.gp[k] <= FEW_GAMES)
    body.append(f'<div class="filtre"><button type="button" id="filtre-mj" aria-pressed="false" '
                f'data-max="{FEW_GAMES}">Masquer les joueurs de {FEW_GAMES} matchs ou moins</button>'
                f'<span class="muted" id="filtre-info">{few} joueur(s) concerné(s) ; le filtre touche aussi '
                f'{"les quintettes et " if quintettes else ""}les passes où ils apparaissent.</span></div>')
    if intro:
        body.append(f'<p class="note">{intro}</p>')
    cards = [(f"{w}-{l}", "victoires – défaites"),
             (f"{season.record(home)[0]}-{season.record(home)[1]}", "à domicile"),
             (f"{season.record(away)[0]}-{season.record(away)[1]}", "à l'extérieur"),
             (num(sum(g.pts for g in season.games) / n), "points marqués par match"),
             (num(sum(g.opp_pts for g in season.games) / n), "points accordés par match"),
             (num(a["ORtg"]), "ORtg (pts / 100 poss.)"), (num(a["DRtg"]), "DRtg"),
             (signed(a["Net"], 1), "Net")]
    body.append('<h2 id="saison-bilan">Bilan</h2><div class="cards">'
                + "".join(f"<div><b>{x}</b><span>{esc(y)}</span></div>" for x, y in cards) + "</div>")
    body.append('<h2 id="saison-resultats">Résultats</h2>' + margins_chart(season) + results_section(season)
                + '<p class="note">Cliquer sur un adversaire ou une barre ouvre le match.</p>'
                + upcoming_section(upcoming))
    body.append(f'<h2 id="saison-equipe">{esc(season.name)} contre ses adversaires</h2>'
                + team_table(season, bench))
    body.append('<h2 id="saison-joueurs">Joueurs : stats de base</h2><p class="note">Source : box scores '
                'officiels (corrigés après le match quand la ligue l\'a fait).</p>' + official_tables(season))
    body.append('<h2 id="saison-impact">Impact sur le terrain</h2><p class="note">Source : play-by-play rejoué, '
                'cumulé sur la saison. Les ratings sont plus fiables qu\'en un seul match, mais restent '
                'sensibles aux quintettes corrigés (voir Fiabilité).</p>' + impact_section(v)
                + "<h3>Efficacité individuelle</h3>" + efficiency_section(v)
                + "<h3>Tirs et sources de points</h3>" + shots_section(v))
    if quintettes:
        body.append('<h2 id="saison-quintettes">Quintettes</h2>' + lineups_section(v, limit=30)
                    + "<h3>Passes décisives : qui sert qui</h3>" + assists_section(v))
    else:
        body.append('<h2 id="saison-passes">Passes décisives : qui sert qui</h2>' + assists_section(v))
    body.append('<h2 id="saison-fiabilite">Fiabilité des données</h2><p class="note">Chaque match est rejoué '
                'à partir de son play-by-play et comparé à son box score officiel. Fiabilité : bonne = au plus '
                '4 écarts de stats et 15 corrections de quintette ; faible = plus de 20 écarts de stats.</p>'
                + reliability_section(season))
    body.append(annex_section("Stats de base : box scores officiels. Tout le reste : play-by-play rejoué.",
                              bench, anchor="saison-annexe", skip=() if quintettes else ("Quintettes",)))
    body.append("</section>")
    for g in season.games:
        official = (f'<div class="meta">Résultat officiel du RSEQ : {g.pts}-{g.opp_pts} '
                    f'({esc(season.name)}) ; la feuille de match donne le score ci-dessus.</div>'
                    if g.score_differs else "")
        body.append(f'<section class="vue" data-vue="{g.code}" hidden>'
                    f'<div class="gamehead">{game_header(g.game)}{official}</div>'
                    + game_body(g.game, prefix=f"{g.code}-", quintettes=quintettes) + "</section>")
    return page(f"{season.name} · saison {saison_label}", header, "".join(body), SEASON_JS).replace(
        "</style>", SEASON_CSS + "</style>", 1)


def season_json(season):
    v = season.view()
    players = []
    for key, p in season.team.players.items():
        players.append({"name": p.name, "numbers": p.num, "games": season.gp[key], "starts": season.gs[key],
                        "official": dict(season.official[key]), "pbp": dict(p.box),
                        "seconds": round(p.seconds),
                        "advanced": rs.player_advanced(p, season.team, season.opp)})
    return {"team": season.name, "record": season.record(), "team_box": dict(season.team.box),
            "opponents_box": dict(season.opp.box), "players": players,
            "games": [{"code": g.code, "date": g.date, "opponent": g.opp.name, "home": g.home,
                       "score": [g.pts, g.opp_pts], "source": g.game.source} for g in season.games],
            "lineups": [{"players": [p.name for p in lu.players], "seconds": round(lu.seconds),
                         "for": dict(lu.on_tm), "against": dict(lu.on_op)} for lu in v.lineups],
            "aliases": {k: c for k, c in season.alias.items() if k != c}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("equipe", help="nom de l'équipe tel qu'écrit sur rseq-stats.ca (ex. Edouard-Montpetit)")
    ap.add_argument("--ligue", default="collegial/basketball-m-d1")
    ap.add_argument("--saison", default="2526", help="code de saison du site (2526 = 2025-26)")
    ap.add_argument("--cache", default=".cache", help="dossier où garder les pages téléchargées")
    ap.add_argument("-o", "--html", default="saison.html")
    ap.add_argument("--json")
    ap.add_argument("--sans-quintettes", action="store_true", help="omettre la section des quintettes")
    ap.add_argument("--lien", help="lien affiché dans l'en-tête (ex. vers la saison en cours)")
    args = ap.parse_args(argv)
    pages = fetch_pages(args.ligue, args.saison, args.cache)
    all_games, _ = team_games(pages)
    key = rs.norm(args.equipe)
    games = [g for g in all_games if rs.norm(g[1].teams[g[2]].name) == key]
    _, skipped = team_games(pages, args.equipe)
    if not games:
        raise SystemExit(f"Aucun match trouvé pour « {args.equipe} » parmi {len(pages)} pages.")
    season = Season(args.equipe, games, skipped)
    label = f"20{args.saison[:2]}-{args.saison[2:]}" if len(args.saison) == 4 else args.saison
    bench = league_benchmarks(all_games, f"RSEQ {args.ligue.split('/')[-1]} {label}")
    extra = f'<div class="meta" style="margin-top:8px"><a href="{esc(args.lien)}">saison en cours</a></div>' \
        if args.lien else ""
    Path(args.html).write_text(render_season(season, label, bench, quintettes=not args.sans_quintettes,
                                             extra_header=extra), encoding="utf-8")
    if args.json:
        data = season_json(season)
        data["league"] = bench
        Path(args.json).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    w, l = season.record()
    print(f"{season.name} : {len(season.games)} matchs ({w} V – {l} D) sur {len(pages)} pages · {args.html}")
    for g in season.games:
        stats, mins = split_diffs(g.game)
        print(f"  {g.code} {g.label():55s} écarts stats {len(stats):3d} · quintettes corrigés {len(g.game.repairs)}")
    for code, title, why in skipped:
        print(f"  {code} {title} : ignoré ({why})")


if __name__ == "__main__":
    sys.exit(main())
