"""Tests du rejeu RSEQ : python3 -m unittest"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import rseq_diffusion as diffusion  # noqa: E402
import rseq_saison as saison  # noqa: E402
import rseq_xml  # noqa: E402
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
        diffs = rs.compare_box(self.game)
        self.assertEqual([d for d in diffs if d[2] != "MIN"], [])
        # Minutes : la feuille oublie des changements, que le rejeu corrige (écart de 2 min au plus).
        self.assertTrue(all(abs(d[3] - d[4]) <= 2 for d in diffs if d[2] == "MIN"), diffs)

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


class FeuillesAbimees(unittest.TestCase):
    """Formats rencontrés dans d'autres salles de la saison 2025-26."""

    def test_textes_corrompus(self):
        self.assertEqual(rs.clean_text("MISSEDDFTDby)Ali Diouf"), "MISSED FT by Ali Diouf")
        self.assertEqual(rs.clean_text("MISSEDDLAYUP)byyKeysean Dumont"), "MISSED LAYUP by Keysean Dumont")
        self.assertEqual(rs.clean_text("MISSEDD3(PTR)by Felix Legare"), "MISSED 3 PTR by Felix Legare")
        self.assertEqual(rs.clean_text("GOOD! JUMPER by Ali Diouf [Pnt]"), "GOOD! JUMPER by Ali Diouf [Pnt]")

    def test_lancer_franc_court_et_rebonds_sans_nom(self):
        g = game_from_rows([
            row("FOUL by Loc Un", "09:00", vis="MISSED FT by Vis Un"),
            row(time="09:00", vis="REBOUND (DEF)"),
            row(time="09:00", score="0-1", vis="GOOD! FT by Vis Un"),
            row("MISSED JUMPER by Loc Deux", "08:40", vis="REBOUND (DEF)"),
            row("TIMEOUT FULL", "08:30"),
        ])
        vis = g.teams[rs.VIS]
        self.assertEqual((vis.find("Vis Un").box["FTA"], vis.find("Vis Un").box["FTM"]), (2, 1))
        self.assertEqual(vis.team_box["DEADBALL"], 1)      # entre les deux lancers
        self.assertEqual(vis.team_box["DREB"], 1)          # rebond d'équipe après le tir raté
        self.assertEqual(g.timeouts[rs.HOME], 1)
        self.assertFalse([w for w in g.warnings if "non reconnue" in w])

    def test_quintette_repare(self):
        g = game_from_rows([
            row(time="09:00", score="0-2", vis="GOOD! JUMPER by Vis Six"),   # entré sans changement noté
            row(time="08:00", vis="SUB IN : Vis Un"),                        # entrée d'un joueur déjà là
            row("GOOD! JUMPER by Loc Un", "07:00", "2-2"),
        ])
        vis = g.teams[rs.VIS]
        self.assertAlmostEqual(vis.find("Vis Six").seconds, 540)    # ajouté au moment de son action
        # Vis Un sort à ce moment : son entrée est notée plus tard, il était donc sur le banc.
        self.assertEqual(vis.find("Vis Un").stints[0][:2], [0, 60])
        total = sum(p.seconds for p in vis.players.values())
        self.assertAlmostEqual(total, 5 * 600)
        self.assertTrue(g.repairs)


class Saison(unittest.TestCase):
    def test_noms_proches(self):
        self.assertTrue(saison.close("bucovesan", "bukovesan"))
        self.assertFalse(saison.close("smyth", "smith"))       # trop court pour une faute de frappe

    def test_cumul_d_un_match(self):
        game = rs.analyse(str(EXAMPLE))
        s = saison.Season("Edouard-Montpetit", [("m001", game, rs.HOME)])
        self.assertEqual(s.record(), (0, 1))
        self.assertEqual(s.team.box["PTS"], 67)
        self.assertEqual(s.opp.box["PTS"], 92)
        diouf = s.team.players["ali diouf"]
        self.assertEqual(s.official["ali diouf"]["PTS"], 22)
        self.assertEqual(diouf.plus_minus, game.teams[rs.HOME].find("Ali Diouf").plus_minus)
        page = saison.render_season(s, "2025-26")
        self.assertIn('<select id="vue">', page)
        self.assertIn('data-vue="m001"', page)
        self.assertIn("Annexe : comprendre et interpréter les stats", page)
        self.assertIn('id="filtre-mj"', page)
        self.assertIn('<tr data-mj="1">', page)        # un seul match : toutes les lignes filtrables


XML_M03 = HERE / "donnees" / "2026-2027" / "2026-M03.xml"


class FeuilleXml(unittest.TestCase):
    """Format 2026-2027 : XML PrestoSports (Édouard-Montpetit à Vanier, 2026-10-17, prolongation)."""

    @classmethod
    def setUpClass(cls):
        cls.game = rseq_xml.analyse_xml(str(XML_M03), {rs.VIS: "Édouard-Montpetit", rs.HOME: "Vanier"})

    def test_box_identique_a_celui_du_xml(self):
        self.assertEqual([d for d in rs.compare_box(self.game) if d[2] != "MIN"], [])

    def test_score_et_periodes(self):
        self.assertEqual(self.game.score, {rs.VIS: 77, rs.HOME: 84})
        self.assertEqual(self.game.period_pts[rs.VIS], [15, 12, 26, 17, 7])
        self.assertEqual(self.game.n_periods, 5)

    def test_minutes_avec_prolongation(self):
        for side in rs.SIDES:
            seconds = sum(p.seconds for p in self.game.teams[side].players.values())
            self.assertAlmostEqual(seconds, 5 * 45 * 60)

    def test_textes_des_actions(self):
        import xml.etree.ElementTree as ET
        play = ET.fromstring('<play action="MISS" type="3PTR"/>')
        self.assertEqual(rseq_xml.play_text(play, "M Tchamsi"), "MISSED 3 PTR by M Tchamsi")
        play = ET.fromstring('<play action="REBOUND" type="DEADB"/>')
        self.assertEqual(rseq_xml.play_text(play, "(TEAM)"), "REBOUND (OFF) by (DEADBALL)")
        play = ET.fromstring('<play action="SUB" type="OUT"/>')
        self.assertEqual(rseq_xml.play_text(play, "J Lucas"), "SUB OUT: J Lucas")


class Automatisation(unittest.TestCase):
    """Quand l'automatisation du soir doit travailler."""

    def setUp(self):
        self.cal = {"matchs": [
            {"num": "M03", "date": "2026-10-17", "visiteur": "Édouard-Montpetit", "receveur": "Vanier",
             "pointage": [79, 84], "fichier": "2026-M03.xml"},
            {"num": "M07", "date": "2026-10-23", "visiteur": "Ahuntsic", "receveur": "Édouard-Montpetit",
             "pointage": None, "fichier": "2026-M07.xml"},
        ]}
        self.folder = XML_M03.parent           # contient 2026-M03.xml, pas 2026-M07.xml

    def run_on(self, day):
        from datetime import date
        return diffusion.should_run(self.cal, "Édouard-Montpetit", self.folder, date.fromisoformat(day))

    def test_lundi_toujours(self):
        self.assertTrue(self.run_on("2026-10-19")[0])

    def test_mardi_rien_si_tout_est_la(self):
        self.assertEqual(self.run_on("2026-10-20"), (False, []))

    def test_match_de_vendredi_attendu_lundi_puis_repris(self):
        # M07 (vendredi 23) : pas attendu avant le lundi 26 ; ensuite repris tous les jours.
        self.assertEqual(self.run_on("2026-10-24"), (False, []))
        run, waiting = self.run_on("2026-10-27")
        self.assertTrue(run)
        self.assertEqual([m["num"] for m in waiting], ["M07"])

    def test_abandon_apres_trois_semaines(self):
        self.assertEqual(self.run_on("2026-11-17"), (False, []))


if __name__ == "__main__":
    unittest.main()
