#!/usr/bin/env python3
"""Site de la saison 2026-2027 et plus : calendrier officiel du RSEQ et feuilles de match XML.

Depuis 2026-2027, le RSEQ publie :
  - le calendrier et les résultats officiels par son API (celle qu'affiche rseq-stats.ca) ;
  - les feuilles de match en XML PrestoSports, lues par le site de statistiques
    (statistiques-bb-cold1-rseq.vercel.app) dans un seau de stockage public.

Ce script trouve la ligue, lit le calendrier, télécharge les XML des matchs joués dans
`--donnees` (gardés dans le dépôt), rejoue chaque match et écrit le site dans `--sortie`.

Avec --si-necessaire (l'automatisation de tous les soirs), il ne fait rien sauf :
  - le lundi (heure de Montréal) : récupère les matchs de la semaine écoulée ;
  - les autres jours, tant qu'un match de l'équipe joué avant ce lundi n'a pas encore
    sa feuille ou son résultat (le RSEQ met parfois quelques jours à les publier).

Usage :
  python3 rseq_diffusion.py "Édouard-Montpetit" [--ligue collegial/basketball-m-d1]
      [--sortie docs] [--donnees donnees] [--si-necessaire]
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import rseq_stats as rs
from rseq_saison import Season, league_benchmarks, render_season
from rseq_xml import analyse_xml

LEAGUE_PAGE = "https://www.rseq-stats.ca/{ligue}/"
API = "https://s1.rseq.ca/api/LeagueApi/GetLeagueDiffusion/?leagueId={id}"
STATS_APP = "https://statistiques-bb-cold1-rseq.vercel.app/"
MONTREAL = ZoneInfo("America/Montreal")
RETRY_DAYS = 21            # au-delà, une feuille toujours absente n'empêche plus de dormir
USER_AGENT = "Stats_RSEQ (https://github.com/benjai1080/Stats_RSEQ)"


def http_get(url, headers=None, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ---------------------------------------------------------------------------
# Calendrier officiel

def league_id(ligue):
    """La page de la ligue sur rseq-stats.ca intègre le calendrier de l'année en cours."""
    page = http_get(LEAGUE_PAGE.format(ligue=ligue)).decode("utf-8", "replace")
    m = re.search(r"LeagueId=([0-9a-f-]{36})", page)
    if not m:
        raise SystemExit(f"Identifiant de ligue introuvable sur {LEAGUE_PAGE.format(ligue=ligue)}")
    return m.group(1)


def schedule(league):
    """Matchs de la ligue : numéro, date, heure, équipes, lieu, résultat officiel, fichier XML."""
    data = json.loads(http_get(API.format(id=league)))
    games = []
    for kind, key in (("saison", "RegularSeasonGames"), ("séries", "PostSeasonGames")):
        for g in data.get(key) or []:
            if g.get("IsDeleted") or g.get("IsCancelledAfterTeamWithdraw"):
                continue
            day = (g.get("GameDate") or g.get("TentativeDate") or "")[:10]
            if day < "2000":                     # séries pas encore fixées : date 1900-01-01
                day = ""
            minutes = g.get("GameTime") or 0
            v, h = g.get("VisitingTeamScore"), g.get("HomeTeamScore")
            link = " ".join(str(g.get(k) or "") for k in ("BroadcastLiveStats", "GameResultFormattedHtml"))
            m = re.search(r"fichier=([0-9]{4}-[A-Z0-9]+\.xml)", link)
            games.append({
                "num": g.get("No", ""), "type": kind, "date": day,
                "heure": f"{minutes // 60}:{minutes % 60:02d}" if minutes else "",
                "visiteur": g.get("VisitingTeamName") or g.get("FakeVisitingTeamName") or "",
                "receveur": g.get("HomeTeamName") or g.get("FakeHomeTeamName") or "",
                "lieu": g.get("SportFacilityDescription") or "",
                "pointage": [v, h] if isinstance(v, int) and v >= 0 and isinstance(h, int) and h >= 0 else None,
                "prolongation": bool(g.get("IsOvertime")),
                "fichier": m.group(1) if m else None,
            })
    return {"saison": data.get("SchoolYearYears", ""), "ligue": league, "matchs": games}


# ---------------------------------------------------------------------------
# Feuilles XML

def storage_config():
    """Adresse du seau et clé publique « anon », lues dans le code du site de statistiques.

    Le site les publie lui-même (la clé n'est pas un secret : elle ne permet que la lecture) ;
    les relire à chaque fois évite de les recopier ici et suit leurs changements.
    """
    js = http_get(STATS_APP + "commun.js").decode("utf-8", "replace")
    cfg = {}
    for name in ("SUPABASE_URL", "SEAU", "SUPABASE_ANON"):
        m = re.search(name + r"\s*=\s*'([^']+)'", js)
        if not m:
            raise SystemExit(f"{name} introuvable dans {STATS_APP}commun.js : le site a changé.")
        cfg[name] = m.group(1)
    return cfg


def fetch_xml(fichier, folder, cfg):
    """Télécharge une feuille si elle n'est pas déjà là. Retourne le chemin, ou None si absente."""
    path = Path(folder) / fichier
    if path.exists():
        return path
    url = f"{cfg['SUPABASE_URL']}/storage/v1/object/{cfg['SEAU']}/{fichier}"
    key = cfg["SUPABASE_ANON"]
    try:
        data = http_get(url, {"apikey": key, "Authorization": "Bearer " + key})
    except urllib.error.HTTPError as err:
        if err.code in (400, 404):          # le seau répond 400 « not_found » pour un fichier absent
            return None
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    time.sleep(0.2)
    return path


# ---------------------------------------------------------------------------
# Quand travailler

def today_montreal(now=None):
    return (now or datetime.now(MONTREAL)).astimezone(MONTREAL).date()


def is_team(name, team):
    return rs.norm(team) in rs.norm(name)


def pending(cal, team, folder, today):
    """Matchs de l'équipe joués avant le lundi de cette semaine, sans résultat ou sans feuille."""
    monday = today - timedelta(days=today.weekday())
    out = []
    for m in cal["matchs"]:
        if not (is_team(m["visiteur"], team) or is_team(m["receveur"], team)) or not m["date"]:
            continue
        played = date.fromisoformat(m["date"])
        if played >= monday or (today - played).days > RETRY_DAYS:
            continue
        if not m["pointage"] or not m["fichier"] or not (Path(folder) / m["fichier"]).exists():
            out.append(m)
    return out


def should_run(cal, team, folder, today):
    """Lundi : toujours. Sinon : seulement s'il manque encore un match de l'équipe."""
    waiting = pending(cal, team, folder, today)
    return today.weekday() == 0 or bool(waiting), waiting


# ---------------------------------------------------------------------------
# Construction

def replay(cal, folder):
    """Rejoue chaque match joué dont la feuille est là. Retourne [(code, game, côté)] pour les deux côtés."""
    games = []
    for m in cal["matchs"]:
        if not m["fichier"] or not (Path(folder) / m["fichier"]).exists():
            continue
        names = {rs.VIS: m["visiteur"], rs.HOME: m["receveur"]}
        try:
            game = analyse_xml(str(Path(folder) / m["fichier"]), names,
                               url=f"{STATS_APP}match.html?div=m&fichier={m['fichier']}")
        except (SystemExit, Exception) as err:          # une feuille illisible ne bloque pas la saison
            print(f"  {m['num']} : feuille illisible ({err})", file=sys.stderr)
            continue
        if m["pointage"]:
            game.official_score = {rs.VIS: m["pointage"][0], rs.HOME: m["pointage"][1]}
        game.meta.setdefault("date", m["date"])
        game.meta["date"] = m["date"] or game.meta.get("date", "")
        if m["lieu"]:
            game.meta["site"] = m["lieu"]
        code = m["num"].lower()
        games.extend((code, game, side) for side in rs.SIDES)
    return games


def build(team, ligue, out_dir, folder, archive_link=None, now=None):
    cal = schedule(league_id(ligue))
    folder = Path(folder) / cal["saison"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "calendrier.json").write_text(json.dumps(cal, ensure_ascii=False, indent=1), encoding="utf-8")
    today = today_montreal(now)
    cfg = storage_config()
    missing = []
    for m in cal["matchs"]:
        if m["fichier"] and m["date"] and date.fromisoformat(m["date"]) <= today:
            if fetch_xml(m["fichier"], folder, cfg) is None:
                missing.append(m)
    all_games = replay(cal, folder)
    games = [g for g in all_games if is_team(g[1].teams[g[2]].name, team)]
    skipped = [(m["num"], f"{m['visiteur']} à {m['receveur']} ({m['date']})", "feuille pas encore publiée")
               for m in missing if is_team(m["visiteur"], team) or is_team(m["receveur"], team)]
    upcoming = [{"date": m["date"], "heure": m["heure"], "lieu": m["lieu"],
                 "domicile": is_team(m["receveur"], team),
                 "adversaire": m["visiteur"] if is_team(m["receveur"], team) else m["receveur"]}
                for m in cal["matchs"]
                if (is_team(m["visiteur"], team) or is_team(m["receveur"], team))
                and m["date"] and date.fromisoformat(m["date"]) > today]
    if not games:
        raise SystemExit(f"Aucune feuille de match pour « {team} » en {cal['saison']}.")
    season = Season(team, games, skipped)
    bench = league_benchmarks(all_games, f"RSEQ {ligue.split('/')[-1]} {cal['saison']}")
    links = (f'<div class="meta" style="margin-top:8px">Mis à jour le {today.isoformat()} · '
             f'<a href="{archive_link}">saison précédente</a></div>' if archive_link else
             f'<div class="meta" style="margin-top:8px">Mis à jour le {today.isoformat()}</div>')
    intro = ("Source : calendrier et résultats officiels du RSEQ ; feuilles de match XML du site de "
             "statistiques du RSEQ (substitutions comprises). Mise à jour automatique le lundi soir.")
    html = render_season(season, cal["saison"], bench, quintettes=False, upcoming=upcoming,
                         extra_header=links, intro=intro)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return season, missing


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("equipe", help="nom de l'équipe tel qu'au calendrier du RSEQ (ex. Édouard-Montpetit)")
    ap.add_argument("--ligue", default="collegial/basketball-m-d1")
    ap.add_argument("--sortie", default="docs", help="dossier du site (GitHub Pages)")
    ap.add_argument("--donnees", default="donnees", help="dossier des feuilles XML téléchargées")
    ap.add_argument("--archive", default="2025-2026/", help="lien vers la saison précédente ('' pour aucun)")
    ap.add_argument("--si-necessaire", action="store_true",
                    help="ne rien faire sauf le lundi, ou s'il manque encore un match de l'équipe")
    args = ap.parse_args(argv)
    today = today_montreal()
    if args.si_necessaire:
        cal = schedule(league_id(args.ligue))
        run, waiting = should_run(cal, args.equipe, Path(args.donnees) / cal["saison"], today)
        if not run:
            print(f"{today} : rien à faire (pas lundi, aucun match en attente).")
            return 0
        print(f"{today} : {'lundi' if today.weekday() == 0 else 'reprise'} ; en attente : "
              + (", ".join(m["num"] for m in waiting) or "aucun"))
    season, missing = build(args.equipe, args.ligue, args.sortie, args.donnees, args.archive or None)
    w, l = season.record()
    print(f"{season.name} : {len(season.games)} match(s), {w} V – {l} D · site : {args.sortie}/index.html")
    for g in season.games:
        print(f"  {g.code} {g.label()}" + ("  (score de la feuille ≠ officiel)" if g.score_differs else ""))
    for m in missing:
        if is_team(m["visiteur"], args.equipe) or is_team(m["receveur"], args.equipe):
            print(f"  {m['num']} {m['visiteur']} à {m['receveur']} ({m['date']}) : feuille pas encore publiée")
    return 0


if __name__ == "__main__":
    sys.exit(main())
