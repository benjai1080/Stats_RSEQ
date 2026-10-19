"""Tests du rejeu RSEQ : python3 -m unittest"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import rseq_stats as rs  # noqa: E402
from rseq_rapport import render  # noqa: E402

EXAMPLE = HERE / "exemples" / "m001.htm"

ROSTER = """<a name="GAME.BOX"> </a><pre>
VISITORS: Visiteurs
## Player                 FG FGA FG FGA FT FTA OF DE TOT PF  TP  A TO BLK S MIN
-------------------------------------------------------------------------------
01 Vis Un.............. *  0  0   0  0   0  0   0  0  0   0   0  0  0  0  0  10
02 Vis Deux............ *  0  0   0  0   0  0   0  0  0   0   0  0  0  0  0  10
03 Vis Trois........... *  0  0   0  0   0  0   0  0  0   0   0  0  0  0  0  10
04 Vis Quatre.......... *  0  0   0  0   0  0   0  0  0   0   0  0  0  0  0  10
05 Vis Cinq............ *  0  0   0  0   0  0   0  0  0   0   0  0  0  0  0  10
06 Vis Six.............    0  0   0  0   0  0   0  0  0   0   0  0  0  0  0  0+
HOME TEAM: Locaux
## Player                 FG FGA FG FGA FT FTA OF DE TOT PF  TP  A TO BLK S MIN
-------------------------------------------------------------------------------
11 Loc Un.............. *  0  0   0  0   0  0   0  0  0   0   0  0  0  0  0  10
12 Loc Deux............ *  0  0   0  0   0  0   0  0  0   0   0  0  0  0  0  10
13 Loc Trois........... *  0  0   0  0   0  0   0  0  0   0   0  0  0  0  0  10
14 Loc Quatre.......... *  0  0   0  0   0  0   0  0  0   0   0  0  0  0  0  10
15 Loc Cinq............ *  0  0   0  0   0  0   0  0  0   0   0  0  0  0  0  10
</pre>"""


def row(home="", time="", score="", vis=""):
    """Ligne de play-by-play aux colonnes du format StatCrew."""
    mid = f"{score:>5s}  {'V 1' if score else '':3s}" if score else ""
    return f"{home:48s}{time}  {mid:12s}{vis}".rstrip()


def game_from_rows(rows):
    pbp = ("<a name=\"GAME.PLY\"> </a><pre>\n1st PERIOD Play-by-Play (Page 1)\n"
           "HOME TEAM: Locaux                               TIME   SCORE  MAR  VISITORS: Visiteurs\n"
           + "-" * 96 + "\n" + "\n".join(rows) + "\n</pre>")
    sections = rs.page_sections(ROSTER + pbp)
    teams, meta = rs.parse_box(sections["GAME.BOX"])
    events, n = rs.parse_pbp(sections["GAME.PLY"])
    return rs.Game(teams, meta, events, n).run()


class ExampleGame(unittest.TestCase):
    """Montmorency – Édouard-Montpetit, 2025-10-17 (rseq-stats.ca, m001)."""

    @classmethod
    def setUpClass(cls):
        cls.game = rs.analyse(str(EXAMPLE))

    def test_box_identique_au_box_officiel(self):
        self.assertEqual(rs.compare_box(self.game), [])

    def test_score_final(self):
        self.assertEqual(self.game.score, {rs.VIS: 92, rs.HOME: 67})
        self.assertEqual(self.game.score_mismatches, [])

    def test_somme_des_plus_minus(self):
        margin = self.game.score[rs.VIS] - self.game.score[rs.HOME]
        for side, sign in ((rs.VIS, 1), (rs.HOME, -1)):
            total = sum(p.plus_minus for p in self.game.teams[side].players.values())
            self.assertEqual(total, sign * 5 * margin)

    def test_minutes_totales(self):
        for side in rs.SIDES:
            seconds = sum(p.seconds for p in self.game.teams[side].players.values())
            self.assertAlmostEqual(seconds, 5 * 40 * 60)
            lineup_seconds = sum(lu.seconds for lu in self.game.lineups[side].values())
            self.assertAlmostEqual(lineup_seconds, 40 * 60)

    def test_possessions_equilibrees(self):
        v = self.game.teams[rs.VIS].box["POSS"]
        h = self.game.teams[rs.HOME].box["POSS"]
        self.assertLessEqual(abs(v - h), self.game.n_periods)
        est = rs.team_advanced(self.game, rs.VIS)["POSS_EST"]
        self.assertLess(abs(v - est), 5)

    def test_on_plus_off_egal_equipe(self):
        team, opp = self.game.teams[rs.VIS], self.game.teams[rs.HOME]
        for p in team.players.values():
            a = rs.player_advanced(p, team, opp)
            self.assertEqual(a["+/-"] + a["OFF_+/-"], team.box["PTS"] - opp.box["PTS"])

    def test_rapport_et_json(self):
        page = render(self.game)
        self.assertIn("Montmorency", page)
        self.assertIn("identique au box score officiel", page)
        data = rs.to_json(self.game)
        self.assertEqual(len(data["teams"][rs.VIS]["players"]), 10)


class Sequences(unittest.TestCase):
    def test_tir_avant_rebond_sur_la_meme_ligne(self):
        g = game_from_rows([
            row("REBOUND (DEF) by Loc Un", "09:40", vis="MISSED JUMPER by Vis Un"),
            row("GOOD! LAYUP by Loc Deux", "09:30", "2-0"),
        ])
        self.assertEqual([e.kind for e in g.events[:2]], ["SHOT", "REB"])
        self.assertEqual(g.teams[rs.VIS].box["POSS"], 2)   # tir raté, puis ballon après le panier
        self.assertEqual(g.teams[rs.HOME].box["POSS"], 1)
        self.assertFalse([e for e in g.events if e.anomaly])

    def test_and_one_une_seule_possession(self):
        g = game_from_rows([
            row(time="09:18", score="0-2", vis="GOOD! LAYUP by Vis Un"),
            row("FOUL by Loc Un", "09:17", "0-3", "GOOD! FT SHOT by Vis Un"),
            row("MISSED JUMPER by Loc Deux", "09:00", vis="REBOUND (DEF) by Vis Deux"),
        ])
        self.assertEqual(g.teams[rs.VIS].box["POSS"], 2)
        self.assertEqual(g.teams[rs.HOME].box["POSS"], 1)

    def test_plus_minus_suit_les_changements(self):
        g = game_from_rows([
            row(time="09:00", score="0-2", vis="GOOD! JUMPER by Vis Un"),
            row(time="08:50", vis="SUB IN : Vis Six"),
            row(time="08:50", vis="SUB OUT: Vis Un"),
            row("GOOD! 3 PTR by Loc Un", "08:30", "3-2"),
        ])
        vis = g.teams[rs.VIS]
        self.assertEqual(vis.find("Vis Un").plus_minus, 2)
        self.assertEqual(vis.find("Vis Six").plus_minus, -3)
        self.assertEqual(vis.find("Vis Deux").plus_minus, -1)
        self.assertAlmostEqual(vis.find("Vis Un").seconds, 70)

    def test_entree_notee_apres_l_action(self):
        g = game_from_rows([
            row(time="05:00", vis="REBOUND (DEF) by Vis Six"),
            row(time="05:00", vis="SUB IN : Vis Six"),
            row(time="05:00", vis="SUB OUT: Vis Cinq"),
        ])
        self.assertEqual(len(g.corrections), 1)
        self.assertFalse([w for w in g.warnings if "sans être sur le terrain" in w])

    def test_minutes_zero_plus(self):
        g = game_from_rows([row("GOOD! JUMPER by Loc Un", "09:00", "2-0")])
        self.assertEqual(g.teams[rs.VIS].find("Vis Six").official["MIN"], 0)


if __name__ == "__main__":
    unittest.main()
