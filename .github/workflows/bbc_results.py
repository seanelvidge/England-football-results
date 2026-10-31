"""Import completed BBC league results, or independently check football-data.

The BBC embeds JSON in the scores/fixtures page. Parse that data without
executing JavaScript; fail if its structure changes instead of assuming that
there were no matches. Neither source may silently correct a stored result.
"""
import argparse
from datetime import date, datetime, timedelta
from io import StringIO
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import football_results as model


BBC_URL = "https://www.bbc.co.uk/sport/football/scores-fixtures"
LEAGUES = {"Premier League": 1, "Championship": 2, "League One": 3, "League Two": 4}
DIVISIONS = {1: "Premier League", 2: "EFL Championship", 3: "EFL League One", 4: "EFL League Two"}
COLUMNS = ["Date", "Season", "HomeTeam", "AwayTeam", "Score", "hGoal", "aGoal", "Division", "Tier", "Result"]
FIXTURE_KEY = ["Season", "HomeTeam", "AwayTeam"]
RESULTS_FILE = "EnglandLeagueResults.csv"
RANKED_FILE = "EnglandLeagueResults_wRanks.csv"
STATE_FILE = ".github/rankings.csv"
# Publish the state manifest last, matching the ranking writer's crash recovery.
ARTIFACTS = [RESULTS_FILE, RANKED_FILE, STATE_FILE, "football_model.json", "README.md", STATE_FILE + ".meta.json"]


def download_session():
    session = requests.Session()
    session.headers["User-Agent"] = "England-football-results/1.0"
    session.mount("https://", HTTPAdapter(max_retries=Retry(
        total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )))
    return session


def download_text(session, url):
    response = session.get(url, timeout=30)
    response.raise_for_status()
    # football-data CSVs may have a UTF-8 BOM and an incorrect HTTP charset.
    response.encoding = "utf-8-sig"
    return response.text


def goal_count(value):
    if not re.fullmatch(r"[0-9]+", str(value)):
        raise ValueError(f"Invalid goal count: {value!r}")
    return int(value)


def result_row(match_date, season, tier, home, away, home_goals, away_goals):
    if not isinstance(home, str) or not home.strip() or not isinstance(away, str) or not away.strip():
        raise ValueError("Missing team name")
    h, a = goal_count(home_goals), goal_count(away_goals)
    return dict(zip(COLUMNS, [
        match_date.isoformat(), f"{season}/{season + 1}", home.strip(), away.strip(),
        f"{h}-{a}", h, a, DIVISIONS[tier], tier, model.determine_match_result(h, a),
    ]))


def parse_bbc_results(html, match_date):
    """Return regular league matches explicitly marked as full time."""
    try:
        marker = re.search(r"window\.__INITIAL_DATA__\s*=\s*", html)
        if marker is None:
            raise ValueError("Missing window.__INITIAL_DATA__")
        state, _ = json.JSONDecoder().raw_decode(html[marker.end():])
        if isinstance(state, str):
            state = json.loads(state)
        blocks = [part["data"] for part in state["data"].values()
                  if part.get("name") == "sport-data-scores-fixtures"]
        if len(blocks) != 1:
            raise ValueError("Expected one scores/fixtures data block")
        data = blocks[0]
        if data["selectedStartDate"] != match_date.isoformat() or data["selectedEndDate"] != match_date.isoformat():
            raise ValueError("BBC returned a different date from the requested page")
        groups = data["eventGroups"]
        if not isinstance(groups, list):
            raise ValueError("eventGroups must be a list")
        rows = []
        for group in groups:
            tier = LEAGUES.get(group["displayLabel"])
            if tier is None:
                continue
            for secondary in group["secondaryGroups"]:
                # BBC includes promotion play-offs under the league heading;
                # these are not regular league fixtures in this database.
                label = secondary["displayLabel"] or ""
                if re.search(r"play[ -]?offs?", label, re.IGNORECASE):
                    continue
                if label:
                    raise ValueError(f"Unexpected league subgroup: {label!r}")
                for event in secondary["events"]:
                    if event["status"] != "PostEvent":
                        continue
                    if (event["periodLabel"]["value"] != "FT"
                            or event["statusComment"]["value"] != "FT"):
                        continue
                    if event["date"]["isoDate"] != match_date.isoformat():
                        raise ValueError("Match date disagrees with the requested page")
                    # Modern seasons can start in late July. The 2020 restart
                    # was exceptional: July 2020 still belongs to 2019/2020.
                    season = match_date.year if match_date.month >= 7 else match_date.year - 1
                    if match_date.year == 2020 and match_date.month == 7:
                        season = 2019
                    rows.append(result_row(
                        match_date, season, tier,
                        event["home"]["fullName"], event["away"]["fullName"],
                        event["home"]["score"], event["away"]["score"],
                    ))
        return model.normalize_team_names(pd.DataFrame(rows, columns=COLUMNS))
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError(f"Cannot parse BBC results for {match_date}: {exc}") from exc


def parse_football_data(text, season, tier):
    """Read completed results only; partially populated scores are errors."""
    frame = pd.read_csv(StringIO(text), dtype=str).dropna(how="all").fillna("")
    required = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"}
    if not required.issubset(frame.columns):
        raise ValueError(f"football-data E{tier - 1}: missing columns {sorted(required - set(frame.columns))}")
    rows = []
    for entry in frame.to_dict("records"):
        if not any(entry[column] for column in ["FTHG", "FTAG", "FTR"]):
            continue
        match_date = datetime.strptime(entry["Date"], "%d/%m/%Y").date()
        row = result_row(match_date, season, tier, entry["HomeTeam"], entry["AwayTeam"], entry["FTHG"], entry["FTAG"])
        if entry["FTR"] != row["Result"]:
            raise ValueError(f"football-data {row['Date']} {row['HomeTeam']} v {row['AwayTeam']}: FTR disagrees with goals")
        rows.append(row)
    return model.normalize_team_names(pd.DataFrame(rows, columns=COLUMNS))


def reconcile_results(existing, incoming, source, allow_new):
    """Compare by season and clubs so a changed date/score cannot be appended."""
    relevant = existing[existing.Season.isin(incoming.Season)]
    relevant = model.normalize_team_names(relevant)
    incoming = model.normalize_team_names(incoming).drop_duplicates()
    stored = {}
    for row in relevant.to_dict("records"):
        key = tuple(row[column] for column in FIXTURE_KEY)
        if key in stored:
            raise ValueError(f"Duplicate database fixture: {key}")
        stored[key] = row
    additions, problems = [], []
    for row in incoming.to_dict("records"):
        key = tuple(row[column] for column in FIXTURE_KEY)
        description = f"{row['Date']} {row['Division']}: {row['HomeTeam']} v {row['AwayTeam']}"
        previous = stored.get(key)
        if previous is None:
            if allow_new:
                additions.append(row)
                stored[key] = row
            else:
                problems.append(f"{description}: missing from database (source score {row['Score']})")
            continue
        differences = [f"{column}: database={previous[column]!r}, source={row[column]!r}"
                       for column in COLUMNS if previous[column] != row[column]]
        if differences:
            problems.append(f"{description}: " + "; ".join(differences))
    if problems:
        raise ValueError(f"{source} consistency check failed ({len(problems)} discrepancies):\n" + "\n".join(problems))
    if not additions:
        return existing.copy(), 0
    updated = pd.concat([existing, pd.DataFrame(additions, columns=COLUMNS)], ignore_index=True)
    updated = updated.sort_values(["Date", "Division"], kind="stable").reset_index(drop=True)
    return updated, len(additions)


def bbc_date_range(existing, start_date, end_date):
    if start_date is None:
        # Overlap catches late finishes; a longer outage is caught up from the
        # last stored result, rather than silently leaving a gap.
        last_result = date.fromisoformat(existing.Date.max())
        start_date = min(last_result, end_date - timedelta(days=6))
    if start_date > end_date:
        raise ValueError("Start date must be on or before end date")
    return [start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)]


def save_bbc_update(root, updated, added):
    # Build and validate the rankings before replacing any repository file.
    with tempfile.TemporaryDirectory(prefix=".bbc-results-", dir=root) as temp:
        stage = Path(temp)
        for name in ARTIFACTS:
            if (root / name).exists():
                (stage / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / name, stage / name)
        if added:
            updated.to_csv(stage / RESULTS_FILE, index=False)
        model.update_rankings(str(stage), RESULTS_FILE, RANKED_FILE, STATE_FILE)
        model.write_readme(str(stage), updated.Date.max().replace("-", "/"), f"{len(updated):,}")
        for name in ARTIFACTS:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            os.replace(stage / name, root / name)


def update_bbc_results(root, start_date=None, end_date=None, dry_run=False):
    root = Path(root)
    end_date = end_date or datetime.now(ZoneInfo("Europe/London")).date()
    existing = pd.read_csv(root / RESULTS_FILE)
    dates = bbc_date_range(existing, start_date, end_date)
    frames = []
    with download_session() as session:
        for day in dates:
            matches = parse_bbc_results(download_text(session, f"{BBC_URL}/{day}"), day)
            frames.append(matches)
            print(f"BBC {day}: {len(matches)} completed league matches")
    incoming = pd.concat(frames, ignore_index=True)
    updated, added = reconcile_results(existing, incoming, "BBC", allow_new=True)
    print(f"BBC: {added} new matches; {len(updated):,} total{' (dry run)' if dry_run else ''}")
    if not dry_run:
        save_bbc_update(root, updated, added)
    return updated, added


def check_football_data(root, season=None):
    existing = pd.read_csv(Path(root) / RESULTS_FILE)
    # Continue checking the latest recorded season over the summer, until BBC
    # results establish the new season (whose CSVs may not yet be published).
    season = season if season is not None else int(existing.Season.max().split("/")[0])
    season_code = f"{season % 100:02d}{(season + 1) % 100:02d}"
    frames = []
    with download_session() as session:
        for tier in range(1, 5):
            url = f"https://www.football-data.co.uk/mmz4281/{season_code}/E{tier - 1}.csv"
            matches = parse_football_data(download_text(session, url), season, tier)
            frames.append(matches)
            print(f"football-data {season}/{season + 1} {DIVISIONS[tier]}: {len(matches)} results")
    incoming = pd.concat(frames, ignore_index=True)
    # A lagging feed is normal: compare every published result, without
    # requiring the feed to contain all of the newer BBC results.
    reconcile_results(existing, incoming, "football-data.co.uk", allow_new=False)
    print(f"football-data.co.uk: all {len(incoming)} published results agree with the database")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-dir", default=".")
    parser.add_argument("--start-date", type=date.fromisoformat, help="First BBC date, YYYY-MM-DD (default: catch up with at least a week's overlap).")
    parser.add_argument("--end-date", type=date.fromisoformat, help="Last BBC date, YYYY-MM-DD (default: today in the UK).")
    parser.add_argument("--dry-run", action="store_true", help="Check BBC results without writing any files.")
    parser.add_argument("--check-football-data", action="store_true", help="Read-only verification against football-data.co.uk, instead of a BBC update.")
    parser.add_argument("--season", type=int, help="Season starting year for verification (default: latest season in the database).")
    args = parser.parse_args()
    if args.check_football_data:
        if args.start_date or args.end_date or args.dry_run:
            parser.error("BBC date/dry-run options cannot be used with --check-football-data")
        check_football_data(args.root_dir, args.season)
    else:
        if args.season is not None:
            parser.error("--season requires --check-football-data")
        update_bbc_results(args.root_dir, args.start_date, args.end_date, args.dry_run)


if __name__ == "__main__":
    main()
