"""Rapport HTML d'un match rejoué par rseq_stats.py (un seul fichier, sans dépendance).

Les sections par équipe prennent une « vue » (équipe, adversaire, quintettes, passes) : un match
ou une saison cumulée (rseq_saison.py) se présentent de la même façon.
"""
import html
from datetime import date

from rseq_guide import GUIDE_CSS, annex_section
from rseq_stats import (HOME, SIDES, VIS, compare_box, fmt_clock, lead_stats, other,
                        period_length, player_advanced, team_advanced)


def esc(x):
    return html.escape(str(x))


def num(x, d=1):
    if x is None:
        return "–"
    if isinstance(x, int):
        return str(x)
    return f"{x:.{d}f}".replace(".", ",")


def pct(x):
    return "–" if x is None else num(100 * x)


def signed(x, d=0):
    if x is None:
        return "–"
    s = f"{x:+.{d}f}".replace(".", ",")
    return s if x else s.lstrip("+")


def mmss(seconds):
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def made(a, b):
    return f"{a}-{b}"


def tone(x):
    """Classe CSS d'une valeur positive ou négative."""
    if x is None or x == 0:
        return ""
    return "pos" if x > 0 else "neg"


class Row(list):
    """Ligne de tableau ; `mj` (matchs joués) sert au filtre des joueurs de la vue saison."""
    mj = None


def with_games(cells, mj):
    if mj is None:
        return cells
    row = Row(cells)
    row.mj = mj
    return row


def games_of(v, *keys):
    """Matchs joués (le plus petit nombre si plusieurs joueurs) ; None hors de la vue saison."""
    if not v.games:
        return None
    return min(v.games.get(k, 0) for k in keys)


def table(headers, rows, cls="", sortable=True, foot=None):
    """headers : liste de (titre, infobulle) ; rows : listes de cellules (texte ou (texte, classe))."""
    out = [f'<div class="scroll"><table class="{cls}{" sortable" if sortable else ""}"><thead><tr>']
    for h, tip in headers:
        out.append(f'<th title="{esc(tip)}">{esc(h)}</th>' if tip else f"<th>{esc(h)}</th>")
    out.append("</tr></thead><tbody>")

    def row_html(r):
        cells = []
        for c in r:
            if isinstance(c, tuple):
                txt, k = c[0], c[1]
                sort = f' data-v="{esc(c[2])}"' if len(c) > 2 else ""
                cells.append(f'<td class="{k}"{sort}>{txt}</td>')
            else:
                cells.append(f"<td>{c}</td>")
        mj = f' data-mj="{r.mj}"' if getattr(r, "mj", None) is not None else ""
        return f"<tr{mj}>" + "".join(cells) + "</tr>"

    out.extend(row_html(r) for r in rows)
    out.append("</tbody>")
    if foot:
        out.append("<tfoot>" + "".join(row_html(r) for r in foot) + "</tfoot>")
    out.append("</table></div>")
    return "".join(out)


class View:
    """Ce qu'il faut pour les sections d'une équipe : elle, l'adversaire, ses quintettes et ses passes."""

    def __init__(self, team, opp, lineups, assists, games=None):
        self.team, self.opp = team, opp
        self.lineups = lineups        # objets Lineup (seconds, on_tm, on_op, players)
        self.assists = assists        # [(nombre, clé du passeur, clé du marqueur)]
        self.games = games            # saison : matchs joués par joueur (GmSc et EVAL par match)


def game_view(game, side):
    assists = [(n, a, s) for (sd, a, s), n in game.assists.items() if sd == side]
    return View(game.teams[side], game.teams[other(side)], list(game.lineups[side].values()), assists)


def ordered_players(team):
    return sorted((p for p in team.players.values() if p.seconds or sum(p.box.values())),
                  key=lambda p: (not p.starter, -p.seconds))


def player_name(p):
    star = ' <span class="star" title="Partant">★</span>' if p.starter else ""
    return (f'<span class="num">{esc(p.num)}</span> {esc(p.name)}{star}', "name", p.name)


# ---------------------------------------------------------------------------
# Sections

def box_section(v):
    t = v.team
    heads = [("Joueur", ""), ("MIN", "Minutes jouées, recalculées par les entrées et sorties"),
             ("PTS", "Points"), ("TIR", "Paniers réussis-tentés"), ("3PTS", "Tirs de 3 points"),
             ("LF", "Lancers francs"), ("RO", "Rebonds offensifs"), ("RD", "Rebonds défensifs"),
             ("REB", "Rebonds"), ("PD", "Passes décisives"), ("BP", "Balles perdues"),
             ("INT", "Interceptions"), ("CTR", "Contres"), ("F", "Fautes personnelles"),
             ("+/-", "Écart au score pendant que le joueur est sur le terrain")]
    rows = []
    for p in ordered_players(t):
        b = p.box
        rows.append([player_name(p), (mmss(p.seconds), "", p.seconds), b["PTS"],
                     (made(b["FGM"], b["FGA"]), "", b["FGM"]), (made(b["3PM"], b["3PA"]), "", b["3PM"]),
                     (made(b["FTM"], b["FTA"]), "", b["FTM"]), b["OREB"], b["DREB"], b["REB"],
                     b["AST"], b["TOV"], b["STL"], b["BLK"], b["PF"],
                     (signed(p.plus_minus), tone(p.plus_minus), p.plus_minus)])
    tb, team_b = t.box, t.team_box
    foot = [["Équipe (rebonds et pertes collectives)", "", "", "", "", "", team_b["OREB"] or "",
             team_b["DREB"] or "", team_b["REB"] or "", "", team_b["TOV"] or "", "", "", "", ""],
            ["Total", mmss(sum(p.seconds for p in t.players.values()) / 5), tb["PTS"],
             made(tb["FGM"], tb["FGA"]), made(tb["3PM"], tb["3PA"]), made(tb["FTM"], tb["FTA"]),
             tb["OREB"], tb["DREB"], tb["REB"], tb["AST"], tb["TOV"], tb["STL"], tb["BLK"], tb["PF"],
             signed(tb["PTS"] - v.opp.box["PTS"])]]
    return table(heads, rows, "box", foot=foot)


def impact_section(v):
    t, o = v.team, v.opp
    heads = [("Joueur", ""), ("MIN", "Minutes jouées"),
             ("POSS", "Possessions offensives de l'équipe pendant qu'il est sur le terrain"),
             ("+/-", "Écart au score sur le terrain"),
             ("PTS +", "Points de l'équipe sur le terrain"), ("PTS −", "Points de l'adversaire sur le terrain"),
             ("ORtg", "Points de l'équipe par 100 possessions, joueur sur le terrain"),
             ("DRtg", "Points de l'adversaire par 100 possessions, joueur sur le terrain"),
             ("Net", "ORtg − DRtg sur le terrain"),
             ("Net hors", "ORtg − DRtg de l'équipe quand le joueur est sur le banc"),
             ("On-Off", "Net sur le terrain − Net hors du terrain"),
             ("+/- hors", "Écart au score quand il est sur le banc")]
    rows = []
    for p in ordered_players(t):
        a = player_advanced(p, t, o)
        rows.append(with_games([player_name(p), (mmss(p.seconds), "", p.seconds), a["POSS"],
                     (signed(a["+/-"]), tone(a["+/-"]), a["+/-"]), p.on_tm["PTS"], p.on_op["PTS"],
                     num(a["ORtg"]), num(a["DRtg"]),
                     (signed(a["Net"], 1), tone(a["Net"]), a["Net"] or 0),
                     (signed(a["OffNet"], 1), tone(a["OffNet"]), a["OffNet"] or 0),
                     (signed(a["OnOff"], 1), tone(a["OnOff"]), a["OnOff"] or 0),
                     (signed(a["OFF_+/-"]), tone(a["OFF_+/-"]), a["OFF_+/-"])], games_of(v, p.key)))
    return table(heads, rows)


def efficiency_section(v):
    t, o = v.team, v.opp
    heads = [("Joueur", ""), ("eFG%", "Pourcentage effectif : (paniers + 0,5 × 3 pts) / tirs"),
             ("TS%", "Tir vrai : points / (2 × (tirs + 0,44 × LF tentés))"),
             ("PPT", "Points par tir tenté"),
             ("USG%", "Part des possessions de l'équipe terminées par le joueur (tir, LF, perte) sur le terrain"),
             ("PD%", "Part des paniers des coéquipiers sur le terrain qu'il a fait marquer"),
             ("BP%", "Pertes par action terminée (tirs + 0,44 × LF + pertes)"),
             ("RO%", "Part des rebonds offensifs disponibles captés sur le terrain"),
             ("RD%", "Part des rebonds défensifs disponibles captés sur le terrain"),
             ("INT%", "Interceptions par 100 possessions adverses sur le terrain"),
             ("CTR%", "Contres par tir de 2 points adverse sur le terrain"),
             ("PD/BP", "Passes décisives par balle perdue"),
             ("Assisté%", "Part de ses paniers marqués sur une passe décisive"),
             ("GmSc", "Game Score (Hollinger)" + (", par match" if v.games else "")),
             ("EVAL", "Évaluation FIBA" + (", par match" if v.games else ""))]
    rows = []
    for p in ordered_players(t):
        a = player_advanced(p, t, o)
        if v.games and v.games.get(p.key):
            a["GmSc"] /= v.games[p.key]
            a["EFF"] = round(a["EFF"] / v.games[p.key], 1)
        rows.append(with_games([player_name(p), pct(a["eFG%"]), pct(a["TS%"]), num(a["PPS"], 2),
                     pct(a["USG%"]), pct(a["AST%"]), pct(a["TOV%"]), pct(a["OREB%"]),
                     pct(a["DREB%"]), pct(a["STL%"]), pct(a["BLK%"]), num(a["AST/TO"], 2),
                     pct(a["AFG%"]), (num(a["GmSc"]), tone(a["GmSc"]), a["GmSc"]),
                     (a["EFF"], tone(a["EFF"]), a["EFF"])], games_of(v, p.key)))
    return table(heads, rows)


SHOT_KINDS = [("LAYUP", "Lay-up"), ("DUNK", "Smash"), ("JUMPER", "Tir 2 pts"), ("3PT", "3 pts")]


def shots_section(v):
    t = v.team
    heads = [("Joueur", "")] + [(k, f"{k} réussis-tentés") for _, k in SHOT_KINDS] + [
        ("Raquette", "Points dans la raquette [Pnt]"), ("Contre-att.", "Points en contre-attaque [FB]"),
        ("2e chance", "Points après un rebond offensif, dans la même possession"),
        ("Après BP", "Points dans une possession commencée par une perte adverse")]
    rows = []
    for p in ordered_players(t):
        b = p.box
        cells = [player_name(p)]
        for key, _ in SHOT_KINDS:
            a = b[key + "_A"]
            cells.append((made(b[key + "_M"], a) if a else "–", "", b[key + "_M"]))
        cells += [b["PNT"], b["FB"], b["2CH"], b["PTO"]]
        rows.append(with_games(cells, games_of(v, p.key)))
    others = sorted({k[:-2] for k in t.box if k.endswith("_A")} - {k for k, _ in SHOT_KINDS})
    note = (f'<p class="note">Autres types de tirs : {esc(", ".join(others))}.</p>' if others else "")
    return table(heads, rows) + note


def lineups_section(v, limit=None):
    lus = [lu for lu in v.lineups if lu.seconds >= 1]
    lus.sort(key=lambda lu: -lu.seconds)
    hidden = len(lus) - limit if limit and len(lus) > limit else 0
    lus = lus[:limit] if limit else lus
    heads = [("Quintette", ""), ("MIN", "Temps joué ensemble"),
             ("POSS", "Possessions offensives"), ("PTS +", "Points marqués"), ("PTS −", "Points accordés"),
             ("+/-", "Écart"), ("ORtg", "Points marqués par 100 possessions"),
             ("DRtg", "Points accordés par 100 possessions"), ("Net", "ORtg − DRtg")]
    rows = []
    for lu in lus:
        o = 100 * lu.on_tm["PTS"] / lu.on_tm["POSS"] if lu.on_tm["POSS"] else None
        d = 100 * lu.on_op["PTS"] / lu.on_op["POSS"] if lu.on_op["POSS"] else None
        n = o - d if o is not None and d is not None else None
        names = ", ".join(f'<span class="num">{esc(p.num)}</span>&nbsp;{esc(p.name.split()[-1])}'
                          for p in lu.players)
        rows.append(with_games([(names, "name lineup", lu.seconds), (mmss(lu.seconds), "", lu.seconds),
                     f'{lu.on_tm["POSS"]}/{lu.on_op["POSS"]}', lu.on_tm["PTS"], lu.on_op["PTS"],
                     (signed(lu.plus_minus), tone(lu.plus_minus), lu.plus_minus),
                     num(o), num(d), (signed(n, 1), tone(n), n or 0)],
                               games_of(v, *(p.key for p in lu.players))))
    more = f" {hidden} autres quintettes, moins utilisés, ne sont pas affichés." if hidden else ""
    return (table(heads, rows) +
            '<p class="note">POSS : possessions en attaque / en défense. Sur quelques possessions, '
            f'les ratings varient énormément : lire d\'abord le temps joué.{more}</p>')


def assists_section(v):
    t = v.team
    items = sorted(v.assists, reverse=True)
    if not items:
        return '<p class="note">Aucune passe décisive.</p>'
    rows = [with_games([esc(t.players[a].name if a in t.players else a),
                        (esc(t.players[s].name if s in t.players else s), "name"), n], games_of(v, a, s))
            for n, a, s in items]
    return table([("Passeur", ""), ("Marqueur", ""), ("Paniers", "")], rows)


def team_section(game):
    v, h = game.teams[VIS], game.teams[HOME]
    av, ah = team_advanced(game, VIS), team_advanced(game, HOME)
    lead = lead_stats(game)

    def row(label, tip, fv, fh, better=None):
        cls = ["", ""]
        if better is not None:
            try:
                a, b = better
                if a != b:
                    cls = ["best", ""] if a > b else ["", "best"]
            except TypeError:
                pass
        return f'<tr><th title="{esc(tip)}">{esc(label)}</th><td class="{cls[0]}">{fv}</td><td class="{cls[1]}">{fh}</td></tr>'

    def pair(key, fmt=pct, higher=True):
        a, b = av[key], ah[key]
        better = None
        if a is not None and b is not None:
            better = (a, b) if higher else (-a, -b)
        return fmt(a), fmt(b), better

    lines = []
    lines.append(row("Possessions", "Comptées dans le play-by-play (estimation par formule entre parenthèses)",
                     f'{av["POSS"]} <span class="muted">({num(av["POSS_EST"])})</span>',
                     f'{ah["POSS"]} <span class="muted">({num(ah["POSS_EST"])})</span>'))
    lines.append(row("Rythme", "Possessions par équipe ramenées à 40 minutes", num(av["PACE"]), num(ah["PACE"])))
    lines.append(row("ORtg", "Points marqués par 100 possessions", *pair("ORtg", num)))
    lines.append(row("DRtg", "Points accordés par 100 possessions", *pair("DRtg", num, higher=False)))
    lines.append(row("Net", "ORtg − DRtg", signed(av["Net"], 1), signed(ah["Net"], 1),
                     (av["Net"] or 0, ah["Net"] or 0)))
    lines.append('<tr class="sep"><th colspan="3">Quatre facteurs (Dean Oliver)</th></tr>')
    lines.append(row("eFG%", "Pourcentage effectif au tir", *pair("eFG%")))
    lines.append(row("BP%", "Balles perdues par possession", *pair("TOV%", higher=False)))
    lines.append(row("RO%", "Rebonds offensifs captés / disponibles", *pair("OREB%")))
    lines.append(row("LF/Tir", "Lancers francs réussis par tir tenté", *pair("FTM/FGA")))
    lines.append('<tr class="sep"><th colspan="3">Tir</th></tr>')
    for key, label, tip in [("FG%", "Tir %", "Paniers / tirs"), ("3P%", "3 pts %", ""), ("FT%", "LF %", ""),
                            ("TS%", "TS%", "Tir vrai"), ("3PAr", "Part de 3 pts", "Tirs de 3 / tirs")]:
        f = pair(key) if key != "3PAr" else pair(key)[:2] + (None,)
        lines.append(row(label, tip, *f))
    lines.append(row("Paniers assistés", "Part des paniers marqués sur une passe décisive",
                     pct(av["AST_RATIO"]), pct(ah["AST_RATIO"])))
    lines.append(row("RD%", "Rebonds défensifs captés / disponibles", *pair("DREB%")))
    lines.append('<tr class="sep"><th colspan="3">D\'où viennent les points</th></tr>')
    for key, label, tip in [("PNT", "Dans la raquette", "Paniers marqués [Pnt]"),
                            ("FB", "Contre-attaque", "Paniers marqués [FB]"),
                            ("2CH", "Deuxième chance", "Après un rebond offensif"),
                            ("PTO", "Après une balle perdue adverse", ""),
                            ("BENCH", "Banc", "Points des remplaçants")]:
        lines.append(row(label, tip, av[key], ah[key], (av[key], ah[key])))
    lines.append('<tr class="sep"><th colspan="3">Déroulement</th></tr>')
    lv, lh = lead["largest"][VIS], lead["largest"][HOME]
    lines.append(row("Plus grande avance", "", f"{lv[0]}" + (f' <span class="muted">({at(lv[1])})</span>' if lv[1] else ""),
                     f"{lh[0]}" + (f' <span class="muted">({at(lh[1])})</span>' if lh[1] else "")))
    lt = lead["leading_time"]
    lines.append(row("Temps en tête", "", mmss(lt[VIS]), mmss(lt[HOME])))
    lines.append(row("Temps morts", "Demandés (écrits au play-by-play)", av["TIMEOUTS"], ah["TIMEOUTS"]))
    run_side, run_pts, span = lead["best_run"]
    head = (f'<table class="team"><thead><tr><th></th><th>{esc(v.name)}</th><th>{esc(h.name)}</th>'
            f'</tr></thead><tbody>')
    extra = (f'<p class="note">Changements de meneur : {lead["lead_changes"]} · égalités : {lead["ties"]} · '
             f'temps à égalité : {mmss(lt["tie"])}'
             + (f' · plus longue série : {run_pts}-0 pour {esc(game.teams[run_side].name)} '
                f'({at(span[0])} à {at(span[1])})' if run_side else "") + "</p>")
    return '<div class="scroll">' + head + "".join(lines) + "</tbody></table></div>" + extra


def at(t):
    """Moment du match : « P3 04:12 » (temps restant dans la période)."""
    if t is None:
        return ""
    p, start = 1, 0
    while t > start + period_length(p):
        start += period_length(p)
        p += 1
    rem = int(round(start + period_length(p) - t))
    return f"P{p} {fmt_clock(rem)}"


def periods_table(game):
    v, h = game.teams[VIS], game.teams[HOME]
    n = game.n_periods
    heads = "".join(f"<th>{i if i <= 4 else 'Prol.' + str(i - 4)}</th>" for i in range(1, n + 1))
    rows = ""
    for t in (v, h):
        cells = "".join(f"<td>{x}</td>" for x in game.period_pts[t.side])
        rows += f'<tr><th class="name">{esc(t.name)}</th>{cells}<td class="total">{game.score[t.side]}</td></tr>'
    return (f'<div class="scroll"><table class="periods"><thead><tr><th></th>{heads}<th>Total</th></tr>'
            f"</thead><tbody>{rows}</tbody></table></div>")


# ---------------------------------------------------------------------------
# Graphiques (SVG)

def flow_chart(game, prefix=""):
    """Écart au score dans le temps (au-dessus : visiteurs devant)."""
    W, H, PAD_L, PAD_R, PAD_T, PAD_B = 900, 260, 34, 10, 14, 26
    total = game.game_seconds
    pts = [(0, 0)] + [(t, v - h) for t, v, h, _, _ in game.flow] + [(total, game.score[VIS] - game.score[HOME])]
    top = max(5, max(abs(m) for _, m in pts))
    top = (top + 4) // 5 * 5

    def x(t):
        return PAD_L + (W - PAD_L - PAD_R) * t / total

    def y(m):
        return PAD_T + (H - PAD_T - PAD_B) * (top - m) / (2 * top)

    path = [f"M{x(0):.1f},{y(0):.1f}"]
    for t, m in pts[1:]:
        path.append(f"H{x(t):.1f}V{y(m):.1f}")
    line = "".join(path)
    area_v = f'<path d="{line}V{y(0):.1f}H{x(0):.1f}Z" class="area-v" clip-path="url(#{prefix}above)"/>'
    area_h = f'<path d="{line}V{y(0):.1f}H{x(0):.1f}Z" class="area-h" clip-path="url(#{prefix}below)"/>'
    grid = []
    for m in range(-top, top + 1, 5):
        grid.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(m):.1f}" y2="{y(m):.1f}" class="{"zero" if m == 0 else "grid"}"/>'
                    f'<text x="{PAD_L - 4}" y="{y(m) + 3:.1f}" class="tick" text-anchor="end">{abs(m)}</text>')
    t0 = 0
    for p in range(1, game.n_periods + 1):
        t1 = t0 + period_length(p)
        grid.append(f'<line x1="{x(t0):.1f}" x2="{x(t0):.1f}" y1="{PAD_T}" y2="{H - PAD_B}" class="grid"/>'
                    f'<text x="{(x(t0) + x(t1)) / 2:.1f}" y="{H - 8}" class="tick" text-anchor="middle">'
                    f'{"P" + str(p) if p <= 4 else "Prol."}</text>')
        t0 = t1
    v, h = game.teams[VIS].name, game.teams[HOME].name
    return f'''<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Écart au score pendant le match">
<defs><clipPath id="{prefix}above"><rect x="0" y="0" width="{W}" height="{y(0):.1f}"/></clipPath>
<clipPath id="{prefix}below"><rect x="0" y="{y(0):.1f}" width="{W}" height="{H}"/></clipPath></defs>
{"".join(grid)}{area_v}{area_h}<path d="{line}" class="flow"/>
<text x="{PAD_L + 6}" y="{PAD_T + 12}" class="lbl v">{esc(v)} devant</text>
<text x="{PAD_L + 6}" y="{H - PAD_B - 6}" class="lbl h">{esc(h)} devant</text></svg>'''


def rotation_chart(game, side):
    """Une ligne par joueur, un segment par présence sur le terrain, coloré selon le +/- de la présence."""
    t = game.teams[side]
    players = ordered_players(t)
    total = game.game_seconds
    ROW, NAME, W, PAD_R, TOP = 22, 170, 900, 10, 18
    H = TOP + ROW * len(players) + 6

    def x(s):
        return NAME + (W - NAME - PAD_R) * s / total

    parts = []
    t0 = 0
    for p in range(1, game.n_periods + 1):
        parts.append(f'<line x1="{x(t0):.1f}" x2="{x(t0):.1f}" y1="{TOP - 4}" y2="{H}" class="grid"/>'
                     f'<text x="{x(t0) + 3:.1f}" y="{TOP - 6}" class="tick">{"P" + str(p) if p <= 4 else "Prol."}</text>')
        t0 += period_length(p)
    for i, p in enumerate(players):
        yy = TOP + i * ROW
        parts.append(f'<text x="{NAME - 8}" y="{yy + 15}" class="pname" text-anchor="end">'
                     f'{esc(p.num)} {esc(p.name)}</text>')
        parts.append(f'<line x1="{NAME}" x2="{W - PAD_R}" y1="{yy + 11}" y2="{yy + 11}" class="track"/>')
        for a, b, pm, _ in p.stints:
            if b <= a:
                continue
            cls = "pos" if pm > 0 else "neg" if pm < 0 else "even"
            tip = f"{p.name} : {at(a)} → {at(b)} ({mmss(b - a)}), {signed(pm)}"
            parts.append(f'<rect x="{x(a):.1f}" y="{yy + 3}" width="{max(1.5, x(b) - x(a)):.1f}" height="16" '
                         f'rx="3" class="stint {cls}"><title>{esc(tip)}</title></rect>')
            if x(b) - x(a) > 26 and pm:
                parts.append(f'<text x="{(x(a) + x(b)) / 2:.1f}" y="{yy + 15}" class="pm" '
                             f'text-anchor="middle">{signed(pm)}</text>')
    return (f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
            f'aria-label="Rotations de {esc(t.name)}">{"".join(parts)}</svg>')


# ---------------------------------------------------------------------------
# Validation

def bullet_list(items, limit=8):
    """Liste à puces ; au-delà de `limit`, le reste se déplie."""
    items = [f"<li>{esc(x)}</li>" for x in items]
    if len(items) <= limit:
        return "<ul>" + "".join(items) + "</ul>"
    return ("<ul>" + "".join(items[:limit]) + "</ul><details><summary>"
            f"{len(items) - limit} de plus</summary><ul>" + "".join(items[limit:]) + "</ul></details>")


def split_diffs(game):
    diffs = compare_box(game)
    return [d for d in diffs if d[2] != "MIN"], [d for d in diffs if d[2] == "MIN"]


def validation_section(game):
    stats, mins = split_diffs(game)
    out = []
    if not stats:
        out.append('<p class="ok">✔ Le box score recalculé à partir du play-by-play est identique au box score '
                   'officiel (toutes les colonnes, tous les joueurs).</p>')
    else:
        out.append(f'<p class="warn">{len(stats)} écart(s) entre le box score recalculé et le box score officiel. '
                   'Ils viennent de la feuille de match elle-même : le play-by-play et le box score officiel '
                   '(parfois corrigé après le match) ne racontent pas tout à fait la même chose.</p>')
    if stats or mins:
        rows = [[esc(a), esc(b), esc(k), esc(off), esc(calc)] for a, b, k, off, calc in stats + mins]
        out.append(table([("Équipe", ""), ("Joueur", ""), ("Stat", ""), ("Officiel", ""), ("Recalculé", "")],
                         rows, sortable=False))
    if mins:
        out.append(f'<p class="note">{len(mins)} écart(s) de minutes de plus d\'une minute : la feuille oublie '
                   'des changements, que le rejeu corrige à partir des actions des joueurs (voir plus bas).</p>')
    if game.corrections:
        out.append("<h4>Changements avancés</h4><p class=\"note\">Le joueur agit juste avant son entrée notée "
                   "(même arrêt de jeu) : ses changements sont appliqués au moment de l'action.</p>"
                   + bullet_list(game.corrections))
    if game.repairs:
        out.append("<h4>Quintettes corrigés</h4><p class=\"note\">Changement oublié par la feuille : un joueur "
                   "agit sans être entré, ou une équipe n'a pas cinq joueurs. Le rejeu se fie à la suite de la "
                   "période (qui agit, qui entre ou sort ensuite).</p>" + bullet_list(game.repairs))
    if game.score_mismatches:
        out.append("<h4>Colonne « score » du play-by-play</h4><p class=\"note\">Le score écrit diffère du score "
                   "recalculé. Certaines feuilles comptent 2 points par lancer franc dans cette colonne ; "
                   "le score recalculé est comparé au score officiel par période.</p>"
                   + bullet_list(game.score_mismatches, 3))
    anomalies = [e for e in game.events if e.anomaly]
    if game.warnings:
        out.append("<h4>Autres incohérences</h4>" + bullet_list(game.warnings))
    if anomalies:
        out.append("<h4>Possessions ambiguës</h4><p class=\"note\">Action d'une équipe qui n'avait pas le ballon "
                   "selon la séquence notée ; une possession est ajoutée.</p>"
                   + bullet_list([f"P{e.period} {fmt_clock(e.rem)} : {e.text}" for e in anomalies]))
    return "".join(out)


CSS = """
:root{--navy:#0B2545;--navy2:#13315C;--gold:#D4AF37;--goldInk:#8C6A12;--bg:#F4F6FA;--surface:#fff;
--muted:#4B5A75;--keep:#1F6E43;--drop:#A23B2A;--line:#DDE3EC}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--navy);font:15px/1.45 -apple-system,BlinkMacSystemFont,"SF Pro Text",
"Segoe UI",Roboto,sans-serif}
header{background:var(--navy);color:#fff;padding:20px 16px}
header .wrap,main{max-width:1180px;margin:0 auto}
main{padding:8px 16px 40px}
h1{margin:0;font-size:1.15rem;font-weight:600;color:var(--gold);letter-spacing:.02em}
.score{display:flex;flex-wrap:wrap;gap:6px 18px;align-items:baseline;margin-top:6px;font-stretch:condensed}
.score .t{font-size:1.5rem;font-weight:700}
.score .n{font-size:2.1rem;font-weight:800;color:var(--gold)}
.meta{color:#C9D3E3;font-size:.85rem;margin-top:6px}
.meta a{color:#fff}
h2{font-size:1.2rem;margin:30px 0 8px;border-bottom:2px solid var(--gold);padding-bottom:4px}
h3{font-size:1rem;margin:22px 0 6px;color:var(--navy2)}
h4{font-size:.95rem;margin:16px 0 4px}
nav{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0 0}
nav a{color:var(--navy);background:var(--surface);border:1px solid var(--line);border-radius:14px;
padding:3px 10px;text-decoration:none;font-size:.85rem}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px;margin:10px 0}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;background:var(--surface)}
th,td{padding:5px 7px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--line)}
thead th{background:var(--navy);color:#fff;font-weight:600;font-size:.8rem;position:sticky;top:0}
thead th[title]{cursor:help;text-decoration:underline dotted rgba(255,255,255,.5)}
table.sortable thead th{cursor:pointer}
th:first-child,td:first-child,td.name{text-align:left}
tfoot td{font-weight:600;background:#EEF2F8}
tbody tr:hover{background:#F7F4EA}
td.pos{color:var(--keep);font-weight:600}
td.neg{color:var(--drop);font-weight:600}
td.best{font-weight:700;color:var(--navy)}
td.best::after{content:" ●";color:var(--goldInk);font-size:.7em}
.num{display:inline-block;min-width:1.6em;color:var(--muted);font-size:.85em}
.star{color:var(--goldInk);font-size:.8em}
td.lineup{white-space:normal;min-width:260px}
table.team{max-width:640px}
table.team th,table.team td{white-space:normal}
table.team thead th{vertical-align:bottom}
table.team tbody th{text-align:left;font-weight:500;color:var(--muted)}
table.team tr.sep th{background:#EEF2F8;color:var(--navy);font-weight:600;text-align:left}
table.periods{max-width:520px}
table.periods td.total{font-weight:700}
.muted{color:var(--muted)}
.note{color:var(--muted);font-size:.85rem;margin:6px 0}
.ok{background:#E7F3EC;border-left:4px solid var(--keep);padding:8px 12px;border-radius:4px}
.warn{background:#FBF1E6;border-left:4px solid var(--goldInk);padding:8px 12px;border-radius:4px}
ul{padding-left:20px;font-size:.88rem}
.chart{width:100%;height:auto;display:block;background:var(--surface);border:1px solid var(--line);border-radius:8px}
.chart .grid{stroke:#E3E8F0;stroke-width:1}
.chart .zero{stroke:var(--muted);stroke-width:1}
.chart .tick{fill:var(--muted);font-size:11px}
.chart .flow{fill:none;stroke:var(--navy);stroke-width:1.6}
.chart .area-v{fill:var(--navy2);opacity:.18}
.chart .area-h{fill:var(--goldInk);opacity:.22}
.chart .lbl{font-size:12px;font-weight:600}
.chart .lbl.v{fill:var(--navy2)} .chart .lbl.h{fill:var(--goldInk)}
.chart .track{stroke:#EEF1F6;stroke-width:16}
.chart .pname{fill:var(--navy);font-size:12px}
.chart .stint.pos{fill:#2E8A57} .chart .stint.neg{fill:#B8503D} .chart .stint.even{fill:#8D99AE}
.chart .pm{fill:#fff;font-size:10.5px;font-weight:700;pointer-events:none}
.legend{display:flex;gap:14px;font-size:.8rem;color:var(--muted);margin:4px 0}
.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-2px;margin-right:4px}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;font-size:.88rem}
dt{font-weight:700} dd{margin:0;color:var(--muted)}
footer{color:var(--muted);font-size:.8rem;text-align:center;padding:20px}
"""

SORT_JS = """
document.querySelectorAll('table.sortable').forEach(function(t){
  t.querySelectorAll('thead th').forEach(function(th,i){
    th.addEventListener('click',function(){
      var tb=t.tBodies[0],rows=Array.from(tb.rows),asc=th.dataset.asc!=='1';
      t.querySelectorAll('thead th').forEach(function(x){delete x.dataset.asc});
      th.dataset.asc=asc?'1':'0';
      function v(r){var c=r.cells[i];var s=c.dataset.v!==undefined?c.dataset.v:c.textContent;
        var n=parseFloat(String(s).replace(',','.').replace('−','-'));return isNaN(n)?String(s):n}
      rows.sort(function(a,b){var x=v(a),y=v(b);
        if(typeof x==='number'&&typeof y==='number')return asc?x-y:y-x;
        return asc?String(x).localeCompare(y):String(y).localeCompare(x)});
      rows.forEach(function(r){tb.appendChild(r)});
    });
  });
});
"""


ROTATION_LEGEND = ('<div class="legend"><span><i style="background:#2E8A57"></i>présence gagnée</span>'
                   '<span><i style="background:#B8503D"></i>présence perdue</span><span>'
                   '<i style="background:#8D99AE"></i>égalité</span></div>')


def game_header(game):
    v, h = game.teams[VIS], game.teams[HOME]
    meta, src = game.meta, game.source
    src_html = (f'<a href="{esc(src)}">{esc(src)}</a>' if src.startswith("http") else esc(src.split("/")[-1]))
    crowd = f"· {meta['attendance']} spectateurs" if meta.get("attendance") else ""
    return (f'<div class="score"><span class="t">{esc(v.name)}</span><span class="n">{game.score[VIS]}</span>'
            f'<span class="t">{esc(h.name)}</span><span class="n">{game.score[HOME]}</span></div>'
            f'<div class="meta">{esc(meta.get("date", ""))} · {esc(meta.get("site", ""))} {crowd} · source : '
            f'{src_html}</div>')


def game_body(game, prefix="", sides=SIDES):
    """Le rapport d'un match, sans en-tête de page. `prefix` rend les ancres uniques dans une page."""
    nav = [("equipes", "Équipes"), ("ecart", "Écart au score")]
    nav += [(f"t{side}", game.teams[side].name) for side in sides]
    nav += [("validation", "Validation")] + ([("glossaire", "Annexe")] if not prefix else [])
    links = "".join(f'<a href="#{prefix}{a}">{esc(b)}</a>' for a, b in nav)
    body = [f"<nav>{links}</nav>"]
    stats, mins = split_diffs(game)
    msg = ("✔ Box score recalculé identique au box score officiel" if not stats
           else f"{len(stats)} écart(s) de stats avec le box score officiel")
    if game.repairs:
        msg += f" · {len(game.repairs)} correction(s) de quintette"
    body.append(f'<p class="{"ok" if not stats else "warn"}" style="margin-top:14px">{msg} '
                f'(voir <a href="#{prefix}validation">Validation</a>).</p>')
    body.append(f'<h2 id="{prefix}equipes">Équipes</h2>{periods_table(game)}{team_section(game)}')
    body.append(f'<h2 id="{prefix}ecart">Écart au score</h2>{flow_chart(game, prefix)}')
    for side in sides:
        t, v = game.teams[side], game_view(game, side)
        body.append(f'<h2 id="{prefix}t{side}">{esc(t.name)} <span class="muted">'
                    f'({"visiteurs" if side == VIS else "locaux"})</span></h2>')
        body.append("<h3>Box score recalculé</h3>" + box_section(v))
        body.append("<h3>Rotations</h3>" + ROTATION_LEGEND + rotation_chart(game, side))
        body.append("<h3>Impact sur le terrain</h3>" + impact_section(v))
        body.append("<h3>Efficacité individuelle</h3>" + efficiency_section(v))
        body.append("<h3>Tirs et sources de points</h3>" + shots_section(v))
        body.append("<h3>Quintettes</h3>" + lineups_section(v))
        body.append("<h3>Passes décisives : qui sert qui</h3>" + assists_section(v))
    body.append(f'<h2 id="{prefix}validation">Validation</h2>' + validation_section(game))
    return "".join(body)


def page(title, header, body, script=""):
    return (f'<!doctype html><html lang="fr"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{esc(title)}</title><style>{CSS}{GUIDE_CSS}</style></head><body>"
            f'<header><div class="wrap">{header}</div></header><main>{body}</main>'
            f"<footer>Généré le {date.today().isoformat()} par Stats_RSEQ</footer>"
            f"<script>{SORT_JS}{script}</script></body></html>")


def render(game):
    v, h = game.teams[VIS], game.teams[HOME]
    header = "<h1>Box score recalculé · stats avancées</h1>" + game_header(game)
    body = game_body(game) + annex_section(
        "Un seul match, c'est peu : les stats « sur le terrain » d'un joueur qui a joué quelques minutes "
        "reposent sur une poignée de possessions.")
    return page(f"{v.name} {game.score[VIS]} – {h.name} {game.score[HOME]}", header, body)
