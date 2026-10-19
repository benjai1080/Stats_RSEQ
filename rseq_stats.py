#!/usr/bin/env python3
"""Box score recalculé et statistiques avancées d'un match RSEQ, à partir du play-by-play.

Source : les pages de match de rseq-stats.ca (format StatCrew), par exemple
https://www.rseq-stats.ca/collegial/basketball-m-d1/stats/2526/m001.htm

Le play-by-play est rejoué action par action : on suit les cinq joueurs de chaque équipe
sur le terrain, le score et la possession du ballon. On en tire le box score (comparé au
box score officiel de la même page), le +/- et les minutes de chaque joueur, les stats
« sur le terrain / hors du terrain », les quintettes et les facteurs d'efficacité.
Formules : voir README.md.

Usage :
  python3 rseq_stats.py URL_OU_FICHIER [-o rapport.html] [--json stats.json]
"""
import argparse
import html
import json
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

PERIOD_SECONDS = 600     # FIBA : quatre périodes de 10 minutes
OT_SECONDS = 300         # prolongation de 5 minutes
SUB_TOLERANCE = 5        # secondes : écart toléré entre une action et l'entrée notée du joueur
HOME, VIS = "H", "V"
SIDES = (VIS, HOME)      # ordre d'affichage de la page : visiteurs puis locaux

BOX_COLUMNS = ["FGM", "FGA", "3PM", "3PA", "FTM", "FTA", "OREB", "DREB", "REB",
               "PF", "PTS", "AST", "TOV", "BLK", "STL", "MIN"]


def other(side):
    return HOME if side == VIS else VIS


def norm(name):
    """Nom comparable : sans points de remplissage ni casse ni espaces doubles."""
    return re.sub(r"\s+", " ", name.rstrip(". ").strip()).lower()


# ---------------------------------------------------------------------------
# Lecture de la page

def load_source(source):
    """Retourne le texte de la page (URL ou fichier). Les pages RSEQ sont en Latin-1."""
    if re.match(r"https?://", source):
        req = urllib.request.Request(source, headers={"User-Agent": "Stats_RSEQ"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
    else:
        raw = Path(source).read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return text.replace("\r", "")


def page_sections(text):
    """Découpe la page en sections <pre> repérées par leur ancre (GAME.BOX, GAME.PLY…)."""
    sections = {}
    for m in re.finditer(r'<a name="([^"]+)">.*?<pre>(.*?)</pre>', text, re.S | re.I):
        body = html.unescape(re.sub(r"<[^>]+>", "", m.group(2)))
        sections[m.group(1)] = body
    return sections


class Player:
    def __init__(self, side, num, name, starter=False, official=None):
        self.side, self.num, self.name = side, num, name
        self.starter = starter
        self.official = official      # stats du box score officiel (ou None)
        self.box = Counter()          # stats recalculées
        self.on_tm = Counter()        # stats de son équipe pendant qu'il est sur le terrain
        self.on_op = Counter()        # stats de l'adversaire pendant qu'il est sur le terrain
        self.seconds = 0.0
        self.stints = []              # [début, fin, +/-] en secondes de match écoulées

    @property
    def key(self):
        return norm(self.name)

    @property
    def plus_minus(self):
        return self.on_tm["PTS"] - self.on_op["PTS"]

    def label(self):
        return f"{self.num} {self.name}"


class Team:
    def __init__(self, side, name):
        self.side, self.name = side, name
        self.players = {}             # nom normalisé -> Player
        self.official_totals = None
        self.official_team_reb = None  # rebonds « TM Team » (OF, DE, TOT)
        self.official_periods = []
        self.box = Counter()          # totaux recalculés (rebonds d'équipe compris)
        self.team_box = Counter()     # rebonds, pertes… attribués à « (TEAM) »

    def find(self, name):
        k = norm(name)
        if k in self.players:
            return self.players[k]
        # Le box score coupe les noms à 20 caractères.
        for pk, p in self.players.items():
            if len(pk) >= 18 and (k.startswith(pk) or pk.startswith(k)):
                return p
        return None


# MIN vaut « 0+ » pour un joueur entré moins d'une minute.
BOX_LINE = re.compile(r"^(\S{1,2})\s+(.{20}) ([* ])\s+((?:\d+\s+){15}\d+\+?)\s*$")


def parse_box(section):
    """Box score officiel : équipes, joueurs, partants (*), totaux, score par période."""
    teams = {}
    meta = {}
    current = None
    for line in section.split("\n"):
        m = re.match(r"^(VISITORS|HOME TEAM):\s*(.+?)\s*$", line)
        if m:
            side = VIS if m.group(1) == "VISITORS" else HOME
            current = teams[side] = Team(side, m.group(2))
            continue
        if current is None:
            continue
        m = BOX_LINE.match(line)
        if m:
            nums = [int(x.rstrip("+")) for x in m.group(4).split()]
            stats = dict(zip(BOX_COLUMNS, nums))
            name = m.group(2).rstrip(". ").strip()
            p = Player(current.side, m.group(1), name, m.group(3) == "*", stats)
            current.players[p.key] = p
            continue
        m = re.match(r"^TM Team\.*\s+(\d+)\s+(\d+)\s+(\d+)", line)
        if m:
            current.official_team_reb = tuple(int(x) for x in m.groups())
            continue
        m = re.match(r"^\s+Totals\.*\s+((?:\d+\s+){15}\d+)", line)
        if m:
            current.official_totals = dict(zip(BOX_COLUMNS, (int(x) for x in m.group(1).split())))
            continue
        m = re.match(r"^Date:\s*(\S+)\s+Site:\s*(.+?)\s+Attendance:\s*(\d+)", line)
        if m:
            meta.update(date=m.group(1), site=m.group(2), attendance=int(m.group(3)))
    # Score par période : « Montmorency......... 28 12 23 29  - 92 »
    for t in teams.values():
        m = re.search(r"^" + re.escape(t.name) + r"\.*\s+([\d ]+?)\s+-\s+(\d+)\s*$", section, re.M)
        if m:
            t.official_periods = [int(x) for x in m.group(1).split()]
    return teams, meta


# ---------------------------------------------------------------------------
# Play-by-play

PBP_ROW = re.compile(r"^(?P<home>.*?)\s*(?P<time>\b\d\d:\d\d)(?:\s+|$)"
                     r"(?:(?P<score>\d+-\d+)\s+(?P<mar>[HVT]\s*\d+)\s*)?(?P<vis>.*?)\s*$")
PERIOD_HEAD = re.compile(r"^(\S+(?: OT)?)\s+PERIOD Play-by-Play", re.I)


class Event:
    __slots__ = ("idx", "period", "rem", "side", "text", "score", "kind", "who",
                 "made", "shot", "tags", "reb", "ft_last", "ft_trip", "technical",
                 "assist", "fg_ref", "anomaly", "skip")

    def __init__(self, period, rem, side, text, score):
        self.period, self.rem, self.side, self.text, self.score = period, rem, side, text, score
        self.kind = None; self.who = None; self.made = False; self.shot = None
        self.tags = (); self.reb = None; self.ft_last = True; self.ft_trip = 1
        self.technical = False; self.assist = None; self.fg_ref = None; self.anomaly = None
        self.skip = False
        self.idx = 0


EVENT_PATTERNS = [
    ("SHOT", re.compile(r"^(GOOD!|MISSED) (.+?) by (.+?)(?: \[([^\]]+)\])?$")),
    ("REB", re.compile(r"^REBOUND \((OFF|DEF)\) by (.+)$")),
    ("AST", re.compile(r"^ASSIST(?: ASSIST)? by (.+)$")),
    ("TOV", re.compile(r"^TURNOVE?R by (.+)$")),
    ("STL", re.compile(r"^STEAL by (.+)$")),
    ("BLK", re.compile(r"^BLOCK by (.+)$")),
    ("TECH", re.compile(r"^FOUL TE TECHNCL by (.+)$")),
    ("FOUL", re.compile(r"^FOUL by (.+)$")),
    ("SUBIN", re.compile(r"^SUB IN ?: ?(.+)$")),
    ("SUBOUT", re.compile(r"^SUB OUT ?: ?(.+)$")),
    ("TIMEOUT", re.compile(r"^TIMEOUT ?(.*?) by (.+)$")),
]

# Ordre logique de deux actions écrites sur la même ligne (locaux à gauche, visiteurs à droite) :
# la faute avant les lancers francs, le tir avant le rebond, les changements à la fin.
ROW_ORDER = {"FOUL": 0, "TECH": 0, "SHOT": 1, "FT": 1, "TOV": 1, "BLK": 2, "STL": 2,
             "AST": 2, "REB": 3, "OTHER": 5, "TIMEOUT": 8, "SUBIN": 9, "SUBOUT": 9}


def classify(ev):
    for kind, pat in EVENT_PATTERNS:
        m = pat.match(ev.text)
        if not m:
            continue
        if kind == "SHOT":
            ev.made = m.group(1) == "GOOD!"
            ev.shot = m.group(2).strip()
            ev.who = m.group(3).strip()
            ev.tags = tuple(m.group(4).split("/")) if m.group(4) else ()
            ev.kind = "FT" if ev.shot.startswith("FT") else "SHOT"
        elif kind == "REB":
            ev.reb, ev.who, ev.kind = m.group(1), m.group(2).strip(), kind
        elif kind == "TIMEOUT":
            ev.shot, ev.who, ev.kind = m.group(1).strip(), m.group(2).strip(), kind
        else:
            ev.who, ev.kind = m.group(1).strip(), kind
        return
    ev.kind = "OTHER"


def clock(mmss):
    mm, ss = mmss.split(":")
    return int(mm) * 60 + int(ss)


def parse_pbp(section):
    """Liste ordonnée des actions, période par période."""
    events = []
    period = 0
    labels = []
    for line in section.split("\n"):
        h = PERIOD_HEAD.match(line.strip())
        if h:
            label = h.group(1).upper()
            if label not in labels:          # « (Page 2) » d'une même période
                labels.append(label)
                period = len(labels)
            continue
        if period == 0 or line.startswith(("HOME TEAM", "---")):
            continue
        m = PBP_ROW.match(line)
        if not m or not m.group("time"):
            continue
        rem = clock(m.group("time"))
        score = None
        if m.group("score"):
            h_pts, v_pts = (int(x) for x in m.group("score").split("-"))
            score = {HOME: h_pts, VIS: v_pts}
        row = []
        for side, text in ((HOME, m.group("home")), (VIS, m.group("vis"))):
            text = re.sub(r"\s+", " ", (text or "").strip())
            if text:
                ev = Event(period, rem, side, text, None)
                classify(ev)
                row.append(ev)
        # Le score de la ligne appartient au panier marqué sur cette ligne.
        for ev in row:
            if ev.made:
                ev.score = score
        row.sort(key=lambda e: ROW_ORDER.get(e.kind, 5))
        events.extend(row)
    for i, ev in enumerate(events):
        ev.idx = i
    return events, len(labels)


def period_length(period):
    return PERIOD_SECONDS if period <= 4 else OT_SECONDS


def elapsed(period, rem):
    """Secondes de match écoulées depuis le début."""
    before = sum(period_length(p) for p in range(1, period))
    return before + period_length(period) - rem


def annotate(events, warnings):
    """Lie passes décisives et paniers, regroupe les lancers francs en séries."""
    for i, ev in enumerate(events):
        if ev.kind != "AST":
            continue
        best = None
        for j in range(max(0, i - 4), min(len(events), i + 5)):
            fg = events[j]
            if (fg.kind == "SHOT" and fg.made and fg.side == ev.side and fg.period == ev.period
                    and fg.rem == ev.rem and fg.assist is None):
                if best is None or abs(j - i) < abs(best - i):
                    best = j
        if best is None:
            warnings.append(f"P{ev.period} {fmt_clock(ev.rem)} : passe de {ev.who} sans panier associé")
        else:
            events[best].assist = ev.who
            ev.fg_ref = best

    techs = {(e.period, e.rem, e.side) for e in events if e.kind == "TECH"}
    trip = []

    def close(trip):
        for k, ft in enumerate(trip):
            ft.ft_trip = len(trip)
            ft.ft_last = k == len(trip) - 1
            ft.technical = (ft.period, ft.rem, other(ft.side)) in techs

    for ev in events:
        if ev.kind == "FT":
            if trip and (trip[-1].side != ev.side or trip[-1].rem != ev.rem
                         or trip[-1].period != ev.period):
                close(trip); trip = []
            trip.append(ev)
        elif ev.kind in ("SHOT", "TOV", "STL") or (ev.kind == "REB" and ev.who != "(DEADBALL)"):
            if trip:
                close(trip); trip = []
    if trip:
        close(trip)


def fmt_clock(rem):
    return f"{rem // 60:02d}:{rem % 60:02d}"


# ---------------------------------------------------------------------------
# Rejeu du match

class Lineup:
    def __init__(self, side, players):
        self.side = side
        self.players = players        # liste triée de Player
        self.seconds = 0.0
        self.on_tm = Counter()
        self.on_op = Counter()

    @property
    def plus_minus(self):
        return self.on_tm["PTS"] - self.on_op["PTS"]


class Game:
    def __init__(self, teams, meta, events, n_periods, source=""):
        self.teams, self.meta, self.events = teams, meta, events
        self.n_periods = n_periods
        self.source = source
        self.warnings = []
        self.corrections = []         # changements avancés (voir early_sub)
        self.on = {VIS: set(), HOME: set()}
        self.lineups = {VIS: {}, HOME: {}}
        self.score = {VIS: 0, HOME: 0}
        self.flow = []                # (secondes écoulées, score V, score H) après chaque panier
        self.period_pts = {VIS: [], HOME: []}
        self.assists = Counter()      # (côté, passeur, marqueur) -> paniers
        self.score_mismatches = []
        self.possession_log = []      # (période, chrono, côté, raison) pour vérification
        self.timeouts = Counter()

    # -- joueurs -----------------------------------------------------------
    def player(self, side, name, ev=None):
        if name.startswith("("):
            return None
        team = self.teams[side]
        p = team.find(name)
        if p is None:
            p = Player(side, "?", name)
            team.players[p.key] = p
            self.warnings.append(f"{name} ({team.name}) apparaît au play-by-play mais pas au box score")
        return p

    # -- crédits -----------------------------------------------------------
    def credit(self, side, actor, inc):
        """Ajoute des stats au joueur, à l'équipe et aux joueurs/quintettes sur le terrain."""
        inc = Counter({k: v for k, v in inc.items() if v})
        if actor is not None:
            actor.box.update(inc)
        else:
            self.teams[side].team_box.update(inc)
        self.teams[side].box.update(inc)
        for p in self.on[side]:
            p.on_tm.update(inc)
        for p in self.on[other(side)]:
            p.on_op.update(inc)
        self.lineup(side).on_tm.update(inc)
        self.lineup(other(side)).on_op.update(inc)

    def lineup(self, side):
        key = frozenset(p.key for p in self.on[side])
        lu = self.lineups[side].get(key)
        if lu is None:
            players = sorted(self.on[side], key=lambda p: (p.num if p.num.isdigit() else "99", p.name))
            lu = self.lineups[side][key] = Lineup(side, players)
        return lu

    # -- partants de chaque période -----------------------------------------
    def period_starters(self, period, previous):
        """Les partants d'une période : ceux qui agissent (ou sortent) avant d'entrer.

        Les changements faits pendant la pause ne sont pas toujours écrits. Il manque alors
        des partants : on complète avec les joueurs présents à la fin de la période précédente
        qui ne sont pas entrés en jeu par un changement pendant la période.
        """
        result = {}
        for side in SIDES:
            seen, starters, subbed_in = set(), [], set()
            for ev in self.events:
                if ev.period != period or ev.side != side or ev.who is None:
                    continue
                if ev.kind in ("TIMEOUT",) or ev.who.startswith("("):
                    continue
                p = self.player(side, ev.who)
                if p is None or p.key in seen:
                    continue
                seen.add(p.key)
                if ev.kind == "SUBIN":
                    subbed_in.add(p.key)
                else:
                    starters.append(p)
            if period == 1:
                official = [p for p in self.teams[side].players.values() if p.starter]
                if official and {p.key for p in official} != {p.key for p in starters} and len(official) == 5:
                    extra = {p.name for p in starters} - {p.name for p in official}
                    if extra:
                        self.warnings.append(
                            f"P1 {self.teams[side].name} : {', '.join(sorted(extra))} agit avant d'entrer "
                            f"mais n'est pas partant au box score")
                    starters = official
            if len(starters) > 5:
                # Trop de candidats : on garde ceux qui étaient déjà là ou qui sortent plus tard,
                # puis ceux qui agissent le plus tôt. Les autres sont des erreurs d'attribution.
                before = {q.key for q in previous.get(side, [])}
                subbed_out = {norm(e.who) for e in self.events
                              if e.period == period and e.side == side and e.kind == "SUBOUT"}
                ranked = sorted(starters, key=lambda q: (q.key not in before and q.key not in subbed_out,
                                                         starters.index(q)))
                dropped = ranked[5:]
                starters = [q for q in starters if q in ranked[:5]]
                self.warnings.append(
                    f"P{period} {self.teams[side].name} : {', '.join(q.name for q in dropped)} agit sans "
                    f"changement noté ; écarté des partants de la période")
            for p in previous.get(side, []):
                if len(starters) >= 5:
                    break
                if p.key not in subbed_in and p not in starters:
                    starters.append(p)
            if len(starters) != 5:
                self.warnings.append(
                    f"P{period} {self.teams[side].name} : {len(starters)} partants déduits au lieu de 5 "
                    f"({', '.join(p.name for p in starters)})")
            result[side] = starters
        return result

    # -- possession ----------------------------------------------------------
    def run(self):
        annotate(self.events, self.warnings)
        previous = {}
        for period in range(1, self.n_periods + 1):
            self.run_period(period, previous)
            previous = {s: list(self.on[s]) for s in SIDES}
        self.finish()
        return self

    def run_period(self, period, previous):
        starters = self.period_starters(period, previous)
        game_t0 = elapsed(period, period_length(period))
        for side in SIDES:
            for p in list(self.on[side]):
                self.leave(p, game_t0)
            for p in starters[side]:
                self.enter(p, game_t0)
        self.ball = None
        self.pending = None
        self.second_chance = {VIS: False, HOME: False}
        self.off_turnover = {VIS: False, HOME: False}
        start_pts = dict(self.score)
        prev_rem = period_length(period)
        checked = set()
        for ev in (e for e in self.events if e.period == period):
            if ev.rem > prev_rem:
                self.warnings.append(f"P{period} {fmt_clock(ev.rem)} : le chrono remonte ({ev.text})")
            dt = max(0, prev_rem - ev.rem)
            if dt:
                self.tick(dt)
                prev_rem = ev.rem
            action = ev.kind not in ("SUBIN", "SUBOUT", "TIMEOUT")
            if action:
                if self.pending:
                    self.credit_possession()
                for side in SIDES:
                    if len(self.on[side]) != 5 and (period, ev.rem, side) not in checked:
                        checked.add((period, ev.rem, side))
                        self.warnings.append(
                            f"P{period} {fmt_clock(ev.rem)} : {len(self.on[side])} joueurs de "
                            f"{self.teams[side].name} sur le terrain")
            self.handle(ev)
        if prev_rem:
            self.tick(prev_rem)
        if self.pending:
            self.credit_possession()
        end_t = elapsed(period, 0)
        for side in SIDES:
            self.period_pts[side].append(self.score[side] - start_pts[side])
            for p in self.on[side]:
                p.stints[-1][1] = end_t
        self.period_end = end_t

    def tick(self, dt):
        for side in SIDES:
            for p in self.on[side]:
                p.seconds += dt
            self.lineup(side).seconds += dt

    def enter(self, p, t):
        if p in self.on[p.side]:
            return False
        self.on[p.side].add(p)
        p.stints.append([t, t, 0, p.plus_minus])
        return True

    def leave(self, p, t):
        if p not in self.on[p.side]:
            return False
        self.on[p.side].discard(p)
        stint = p.stints[-1]
        stint[1] = t
        stint[2] = p.plus_minus - stint[3]
        return True

    def gain(self, side, ev, reason):
        """Le ballon change de mains : nouvelle possession pour `side`."""
        if self.ball == side:
            return
        if self.pending:
            self.credit_possession()
        self.ball = side
        self.second_chance[side] = False
        self.off_turnover[side] = reason == "TO"
        if ev.rem > 0:
            self.pending = side
            self.possession_log.append((ev.period, ev.rem, side, reason))

    def credit_possession(self):
        side, self.pending = self.pending, None
        self.credit(side, None, {"POSS": 1})
        # La possession n'appartient à aucun joueur : on l'enlève du « box » d'équipe.
        self.teams[side].team_box["POSS"] -= 1

    # -- une action ------------------------------------------------------------
    def handle(self, ev):
        side, opp = ev.side, other(ev.side)
        t = elapsed(ev.period, ev.rem)
        who = ev.who
        if ev.kind in ("SUBIN", "SUBOUT"):
            if ev.skip:
                return
            p = self.player(side, who)
            if p is None:
                return
            ok = self.enter(p, t) if ev.kind == "SUBIN" else self.leave(p, t)
            if not ok:
                verb = "entre alors qu'il est déjà" if ev.kind == "SUBIN" else "sort alors qu'il n'est pas"
                self.warnings.append(f"P{ev.period} {fmt_clock(ev.rem)} : {p.name} {verb} sur le terrain")
            return
        if ev.kind == "TIMEOUT":
            self.timeouts[side] += 1
            return
        if ev.kind == "OTHER":
            self.warnings.append(f"P{ev.period} {fmt_clock(ev.rem)} : action non reconnue « {ev.text} »")
            return

        p = self.player(side, who) if who else None
        if p is not None and p not in self.on[side] and not self.early_sub(ev, p):
            self.warnings.append(
                f"P{ev.period} {fmt_clock(ev.rem)} : {p.name} est crédité de « {ev.text} » "
                f"sans être sur le terrain")

        if ev.kind == "SHOT":
            if self.ball != side:
                if self.ball is not None:
                    ev.anomaly = "tir sans possession"
                self.gain(side, ev, "START" if self.ball is None else "?")
            three = ev.shot.startswith("3")
            kind = "3PT" if three else ev.shot.split()[0]
            inc = Counter({"FGA": 1, "3PA": int(three), "2PA": int(not three), kind + "_A": 1})
            if ev.made:
                pts = 3 if three else 2
                inc.update({"FGM": 1, "3PM": int(three), "PTS": pts, kind + "_M": 1,
                            "FB": pts * ("FB" in ev.tags), "PNT": pts * ("Pnt" in ev.tags),
                            "2CH": pts * self.second_chance[side],
                            "PTO": pts * self.off_turnover[side],
                            "AFGM": int(ev.assist is not None)})
            self.credit(side, p, inc)
            if ev.made:
                self.scored(ev, side, inc["PTS"])
                if ev.assist:
                    a = self.player(side, ev.assist)
                    if a is not None:
                        self.assists[(side, a.key, p.key if p else "")] += 1
                self.gain(opp, ev, "FG")
        elif ev.kind == "FT":
            if self.ball != side and not ev.technical and ev.ft_trip > 1:
                self.gain(side, ev, "FT")
            inc = Counter({"FTA": 1})
            if ev.made:
                inc.update({"FTM": 1, "PTS": 1, "2CH": int(self.second_chance[side]),
                            "PTO": int(self.off_turnover[side])})
            self.credit(side, p, inc)
            if ev.made:
                self.scored(ev, side, 1)
                if ev.ft_last and not ev.technical:
                    self.gain(opp, ev, "FT")
        elif ev.kind == "REB":
            if who == "(DEADBALL)":
                self.teams[side].team_box["DEADBALL"] += 1
                return
            key = "OREB" if ev.reb == "OFF" else "DREB"
            self.credit(side, p, {key: 1, "REB": 1})
            if key == "OREB":
                self.gain(side, ev, "OREB")
                self.second_chance[side] = True
            else:
                self.gain(side, ev, "DREB")
        elif ev.kind == "TOV":
            if self.ball != side:
                if self.ball is not None:
                    ev.anomaly = "perte sans possession"
                self.gain(side, ev, "START" if self.ball is None else "?")
            self.credit(side, p, {"TOV": 1})
            self.gain(opp, ev, "TO")
        elif ev.kind == "STL":
            self.credit(side, p, {"STL": 1})
            self.gain(side, ev, "TO")
        elif ev.kind == "BLK":
            self.credit(side, p, {"BLK": 1})
        elif ev.kind == "FOUL":
            self.credit(side, p, {"PF": 1})
        elif ev.kind == "TECH":
            self.credit(side, p, {"TF": 1})
        elif ev.kind == "AST":
            # Crédité même sans panier associé, comme le box score officiel.
            self.credit(side, p, {"AST": 1})

    def early_sub(self, ev, p):
        """Un joueur agit juste avant son entrée notée : on avance son changement.

        Le marqueur écrit souvent les changements après les actions du même arrêt de jeu.
        Si l'entrée du joueur suit de SUB_TOLERANCE secondes au plus, on applique tout de suite
        les changements de son équipe notés à ce moment-là. Au-delà, l'incohérence est signalée.
        """
        for later in self.events[ev.idx + 1:]:
            if later.period != ev.period or later.rem < ev.rem - SUB_TOLERANCE:
                return False
            if (later.kind == "SUBIN" and later.side == p.side and not later.skip
                    and self.player(p.side, later.who) is p):
                break
        else:
            return False
        t = elapsed(ev.period, ev.rem)
        block = [e for e in self.events[ev.idx + 1:]
                 if e.period == later.period and e.rem == later.rem and e.side == later.side
                 and e.kind in ("SUBIN", "SUBOUT") and not e.skip]
        for e in sorted(block, key=lambda e: e.kind == "SUBIN"):   # sorties d'abord
            q = self.player(e.side, e.who)
            if q is not None:
                (self.enter if e.kind == "SUBIN" else self.leave)(q, t)
            e.skip = True
        self.corrections.append(
            f"P{ev.period} {fmt_clock(ev.rem)} : {p.name} est crédité de « {ev.text} » avant son entrée "
            f"notée à {fmt_clock(later.rem)} ; changements de {self.teams[p.side].name} avancés")
        return True

    def scored(self, ev, side, pts):
        self.score[side] += pts
        t = elapsed(ev.period, ev.rem)
        self.flow.append((t, self.score[VIS], self.score[HOME], side, pts))
        if ev.score and ev.score != self.score:
            self.score_mismatches.append(
                f"P{ev.period} {fmt_clock(ev.rem)} : score écrit {ev.score[HOME]}-{ev.score[VIS]}, "
                f"recalculé {self.score[HOME]}-{self.score[VIS]}")
            self.score = dict(ev.score)

    def finish(self):
        for side in SIDES:
            for p in list(self.on[side]):
                self.leave(p, self.period_end)
        self.game_seconds = self.period_end


# ---------------------------------------------------------------------------
# Statistiques dérivées

def div(a, b):
    return a / b if b else None


def shooting(c):
    """Indicateurs de tir et d'efficacité à partir d'un compteur de stats."""
    fga, fta = c["FGA"], c["FTA"]
    return {
        "FG%": div(c["FGM"], fga), "3P%": div(c["3PM"], c["3PA"]), "FT%": div(c["FTM"], fta),
        "eFG%": div(c["FGM"] + 0.5 * c["3PM"], fga),
        "TS%": div(c["PTS"], 2 * (fga + 0.44 * fta)),
        "3PAr": div(c["3PA"], fga), "FTr": div(fta, fga),
    }


def player_advanced(p, team, opp):
    b, tm, op = p.box, p.on_tm, p.on_op
    out = shooting(b)
    plays = b["FGA"] + 0.44 * b["FTA"] + b["TOV"]
    tm_plays = tm["FGA"] + 0.44 * tm["FTA"] + tm["TOV"]
    off_tm = team.box - tm
    off_op = opp.box - op
    on_net = net(tm, op)
    off_net = net(off_tm, off_op)
    out.update({
        "+/-": p.plus_minus,
        "POSS": tm["POSS"], "OPP_POSS": op["POSS"],
        "ORtg": div(100 * tm["PTS"], tm["POSS"]), "DRtg": div(100 * op["PTS"], op["POSS"]),
        "Net": on_net, "OffNet": off_net,
        "OnOff": on_net - off_net if on_net is not None and off_net is not None else None,
        "OFF_+/-": off_tm["PTS"] - off_op["PTS"],
        "USG%": div(plays, tm_plays),
        "AST%": div(b["AST"], tm["FGM"] - b["FGM"]),
        "TOV%": div(b["TOV"], plays),
        "OREB%": div(b["OREB"], tm["OREB"] + op["DREB"]),
        "DREB%": div(b["DREB"], tm["DREB"] + op["OREB"]),
        "REB%": div(b["REB"], tm["REB"] + op["REB"]),
        "STL%": div(b["STL"], op["POSS"]),
        "BLK%": div(b["BLK"], op["2PA"]),
        "AST/TO": div(b["AST"], b["TOV"]),
        "PPS": div(b["PTS"], b["FGA"]),
        "AFG%": div(b["AFGM"], b["FGM"]),
        "GmSc": (b["PTS"] + 0.4 * b["FGM"] - 0.7 * b["FGA"] - 0.4 * (b["FTA"] - b["FTM"])
                 + 0.7 * b["OREB"] + 0.3 * b["DREB"] + b["STL"] + 0.7 * b["AST"]
                 + 0.7 * b["BLK"] - 0.4 * b["PF"] - b["TOV"]),
        "EFF": (b["PTS"] + b["REB"] + b["AST"] + b["STL"] + b["BLK"]
                - (b["FGA"] - b["FGM"]) - (b["FTA"] - b["FTM"]) - b["TOV"]),
    })
    return out


def net(tm, op):
    o, d = div(100 * tm["PTS"], tm["POSS"]), div(100 * op["PTS"], op["POSS"])
    return o - d if o is not None and d is not None else None


def team_advanced(game, side):
    t, o = game.teams[side], game.teams[other(side)]
    b, ob = t.box, o.box
    out = shooting(b)
    est = b["FGA"] - b["OREB"] + b["TOV"] + 0.44 * b["FTA"]
    minutes = game.game_seconds / 60
    bench = sum(p.box["PTS"] for p in t.players.values() if not p.starter)
    out.update({
        "POSS": b["POSS"], "POSS_EST": est,
        "PACE": div((b["POSS"] + ob["POSS"]) / 2 * 40, minutes),
        "ORtg": div(100 * b["PTS"], b["POSS"]), "DRtg": div(100 * ob["PTS"], ob["POSS"]),
        "Net": net(b, ob),
        "TOV%": div(b["TOV"], b["POSS"]),
        "OREB%": div(b["OREB"], b["OREB"] + ob["DREB"]),
        "DREB%": div(b["DREB"], b["DREB"] + ob["OREB"]),
        "FTM/FGA": div(b["FTM"], b["FGA"]),
        "AST_RATIO": div(b["AFGM"], b["FGM"]),
        "PPP": div(b["PTS"], b["POSS"]),
        "BENCH": bench, "PNT": b["PNT"], "FB": b["FB"], "2CH": b["2CH"], "PTO": b["PTO"],
        "TIMEOUTS": game.timeouts[side],
    })
    return out


def leader(margin):
    return VIS if margin > 0 else HOME if margin < 0 else "tie"


def lead_stats(game):
    """Changements de meneur, égalités, plus grande avance, plus longue séquence, temps en avance."""
    lead_changes = ties = 0
    largest = {VIS: (0, None), HOME: (0, None)}
    leading_time = {VIS: 0.0, HOME: 0.0, "tie": 0.0}
    last_leader = 0                   # signe du dernier écart non nul
    prev_t, prev_margin = 0.0, 0
    run_side, run_pts, run_start, best_run = None, 0, 0.0, (None, 0, None)
    for t, v, h, side, pts in game.flow:
        leading_time[leader(prev_margin)] += t - prev_t
        margin = v - h
        sign = (margin > 0) - (margin < 0)
        if sign:
            if last_leader and sign != last_leader:
                lead_changes += 1
            last_leader = sign
        elif v or h:
            ties += 1
        if margin > largest[VIS][0]:
            largest[VIS] = (margin, t)
        if -margin > largest[HOME][0]:
            largest[HOME] = (-margin, t)
        if side == run_side:
            run_pts += pts
        else:
            run_side, run_pts, run_start = side, pts, t
        if run_pts > best_run[1]:
            best_run = (run_side, run_pts, (run_start, t))
        prev_t, prev_margin = t, margin
    leading_time[leader(prev_margin)] += game.game_seconds - prev_t
    return {"lead_changes": lead_changes, "ties": ties, "largest": largest,
            "leading_time": leading_time, "best_run": best_run}


def compare_box(game):
    """Écarts entre le box score recalculé et le box score officiel."""
    diffs = []
    keys = [k for k in BOX_COLUMNS if k != "MIN"]
    for side in SIDES:
        team = game.teams[side]
        for p in team.players.values():
            if p.official is None:
                continue
            for k in keys:
                if p.box[k] != p.official[k]:
                    diffs.append((team.name, p.name, k, p.official[k], p.box[k]))
            mins = round(p.seconds / 60)
            if abs(mins - p.official["MIN"]) > 1:
                diffs.append((team.name, p.name, "MIN", p.official["MIN"], round(p.seconds / 60, 1)))
        if team.official_totals:
            for k in keys:
                if team.box[k] != team.official_totals[k]:
                    diffs.append((team.name, "Totaux", k, team.official_totals[k], team.box[k]))
        if team.official_periods and team.official_periods != game.period_pts[side]:
            diffs.append((team.name, "Score par période", "PTS",
                          team.official_periods, game.period_pts[side]))
    return diffs


def analyse(source):
    text = load_source(source)
    sections = page_sections(text)
    box = sections.get("GAME.BOX")
    if not box:
        raise SystemExit("Box score introuvable dans la page")
    teams, meta = parse_box(box)
    pbp = sections.get("GAME.PLY")
    events, n_periods = parse_pbp(pbp) if pbp else ([], 0)
    if not events:
        raise SystemExit("Cette page n'a pas de play-by-play : rien à recalculer.")
    game = Game(teams, meta, events, n_periods, source)
    game.run()
    return game


# ---------------------------------------------------------------------------
# Export

def to_json(game):
    data = {"source": game.source, "meta": game.meta, "teams": {}, "warnings": game.warnings,
            "score_mismatches": game.score_mismatches,
            "box_diffs": [list(d) for d in compare_box(game)]}
    for side in SIDES:
        t, o = game.teams[side], game.teams[other(side)]
        players = []
        for p in t.players.values():
            players.append({
                "num": p.num, "name": p.name, "starter": p.starter,
                "seconds": round(p.seconds), "box": dict(p.box),
                "advanced": player_advanced(p, t, o),
                "stints": [[round(a), round(b), pm] for a, b, pm, _ in p.stints],
            })
        lineups = [{"players": [p.name for p in lu.players], "seconds": round(lu.seconds),
                    "for": dict(lu.on_tm), "against": dict(lu.on_op), "+/-": lu.plus_minus}
                   for lu in game.lineups[side].values() if lu.seconds or lu.on_tm or lu.on_op]
        data["teams"][side] = {
            "name": t.name, "box": dict(t.box), "periods": game.period_pts[side],
            "advanced": team_advanced(game, side), "players": players, "lineups": lineups,
            "assists": [{"from": a, "to": s, "n": n} for (sd, a, s), n in game.assists.items() if sd == side],
        }
    return data


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source", help="URL d'une page de match rseq-stats.ca ou fichier .htm enregistré")
    ap.add_argument("-o", "--html", help="rapport HTML à écrire")
    ap.add_argument("--json", help="données à écrire en JSON")
    args = ap.parse_args(argv)
    game = analyse(args.source)
    diffs = compare_box(game)
    v, h = game.teams[VIS], game.teams[HOME]
    print(f"{v.name} {game.score[VIS]} – {h.name} {game.score[HOME]}")
    print(f"Box score recalculé : {'identique au box score officiel' if not diffs else f'{len(diffs)} écart(s)'}")
    for d in diffs:
        print("  ", " | ".join(str(x) for x in d))
    for w in game.corrections:
        print("  ~", w)
    for w in game.warnings + game.score_mismatches:
        print("  !", w)
    for side in SIDES:
        t = game.teams[side]
        print(f"\n{t.name} (possessions {t.box['POSS']})")
        for p in sorted(t.players.values(), key=lambda p: -p.seconds):
            if p.seconds:
                print(f"  {p.label():28s} {fmt_clock(int(round(p.seconds))):>6s}  "
                      f"{p.box['PTS']:3d} pts  +/- {p.plus_minus:+d}")
    if args.json:
        Path(args.json).write_text(json.dumps(to_json(game), ensure_ascii=False, indent=1), encoding="utf-8")
    if args.html:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from rseq_rapport import render
        Path(args.html).write_text(render(game), encoding="utf-8")
        print(f"\nRapport : {args.html}")


if __name__ == "__main__":
    main()
