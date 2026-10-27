import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import zipfile
from pathlib import Path
from datetime import datetime
from io import StringIO
from typing import Dict, List, Optional, Set, Tuple, Iterable
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
import requests


ELO_PER_NAT_LOGIT = 400.0 / np.log(10.0)
MODEL_VERSION = "davidson-margin-v3"
BETA = 0.9
WEEKLY_RHO = 0.995
WEEKLY_PROCESS_VARIANCE = 0.0017
INITIAL_VARIANCE = 0.25
BASELINE_LEARNING_RATE = 0.001
MARGIN_SLOPE = 0.75
TIER_MEANS = {1: 1.5, 2: 0.3, 3: -0.3, 4: -0.6}
DISPLAY_BASE = 1000.0
DISPLAY_MULT = 2.0
DISPLAY_OFFSET = 0.0
RANKINGS_STATE_HEADER = ["RecordType", "Team", "Date", "Rank", "Var", "Tier", "HomeAdvantage", "LogDraw", "LogExcessMargin"]
EXCEL_EPOCH = datetime(1899, 12, 30)


def season_start_year(match_date: datetime) -> int:
    return match_date.year if match_date.month >= 8 else match_date.year - 1


def determine_match_result(home_goals: int, away_goals: int) -> str:
    if home_goals > away_goals:
        return "H"
    if home_goals < away_goals:
        return "A"
    return "D"


def parse_score(score: str) -> Tuple[int, int]:
    parts = [part.strip() for part in str(score).split("-", maxsplit=1)]
    if len(parts) != 2:
        raise ValueError(f"Could not parse score '{score}'")
    return int(parts[0]), int(parts[1])


def parse_years_active(years_active: str) -> Tuple[int, Optional[int]]:
    start_text, end_text = [part.strip() for part in years_active.replace("—", "–").split("–", maxsplit=1)]
    start_year = int(start_text)
    end_year = None if end_text.lower() == "present" else int(end_text) + 1
    return start_year, end_year


def load_division_lookup(root_dir: str) -> List[Dict[str, Optional[int]]]:
    lookup_path = os.path.join(root_dir, "EnglandLeagueNames.csv")
    divisions: List[Dict[str, Optional[int]]] = []
    with open(lookup_path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            start_year, end_year = parse_years_active(row["Years Active"])
            divisions.append(
                {
                    "name": row["Name"],
                    "tier": int(row["Tier"]),
                    "start_year": start_year,
                    "end_year": end_year,
                }
            )
    return divisions


def division_name_for_match(divisions: List[Dict[str, Optional[int]]], tier: int, match_date: datetime) -> str:
    season_year = season_start_year(match_date)
    for division in divisions:
        if division["tier"] != tier:
            continue
        end_year = division["end_year"]
        if season_year >= division["start_year"] and (end_year is None or season_year < end_year):
            return str(division["name"])
    raise ValueError(f"Could not determine division name for tier {tier} in season starting {season_year}")


def _xlsx_cell_value(cell: ET.Element, shared_strings: List[str], namespace: Dict[str, str]) -> str:
    value = cell.find("a:v", namespace)
    if value is None or value.text is None:
        return ""
    if cell.attrib.get("t") == "s":
        return shared_strings[int(value.text)]
    return value.text


def read_scores_sheet_rows(xlsx_path: str) -> List[Dict[str, str]]:
    namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

    with zipfile.ZipFile(xlsx_path) as workbook:
        shared_strings_root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
        shared_strings = []
        for item in shared_strings_root.findall("a:si", namespace):
            text_parts = [text_node.text or "" for text_node in item.iterfind(".//a:t", namespace)]
            shared_strings.append("".join(text_parts))

        sheet_root = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
        rows = sheet_root.find("a:sheetData", namespace)
        if rows is None:
            return []

        parsed_rows: List[Dict[str, str]] = []
        headers: Dict[str, str] = {}

        for row_index, row in enumerate(rows.findall("a:row", namespace)):
            values: Dict[str, str] = {}
            for cell in row.findall("a:c", namespace):
                cell_ref = cell.attrib["r"]
                column = "".join(character for character in cell_ref if character.isalpha())
                values[column] = _xlsx_cell_value(cell, shared_strings, namespace)

            if row_index == 0:
                headers = values
                continue

            parsed_row: Dict[str, str] = {}
            for column, header in headers.items():
                parsed_row[header] = values.get(column, "")
            parsed_rows.append(parsed_row)

    return parsed_rows


def load_tmp_results_matches(
    root_dir: str,
    existing_df: pd.DataFrame,
    tiers: Optional[Set[int]] = None,
) -> pd.DataFrame:
    xlsx_path = os.path.join(root_dir, ".github", "tmp_results.xlsx")
    if not os.path.exists(xlsx_path):
        return pd.DataFrame(columns=existing_df.columns)

    divisions = load_division_lookup(root_dir)
    existing_keys = {
        (match_date.strftime("%Y-%m-%d"), row.HomeTeam, row.AwayTeam, str(row.Score))
        for match_date, row in normalize_team_names(existing_df).iterrows()
    }
    rows_to_add: List[Dict[str, object]] = []

    for row in read_scores_sheet_rows(xlsx_path):
        score_text = row.get("Score") or row.get("Result")
        if (
            not row.get("Date")
            or not row.get("Home Team")
            or not row.get("Away Team")
            or not row.get("Tier")
            or not score_text
        ):
            continue

        tier = int(float(row["Tier"]))

        # If specific tiers were requested, ignore all others.
        if tiers is not None and tier not in tiers:
            continue

        match_date = EXCEL_EPOCH + dt.timedelta(days=float(row["Date"]))
        normalized_names = normalize_team_names(
            pd.DataFrame(
                [{
                    "HomeTeam": row["Home Team"],
                    "AwayTeam": row["Away Team"],
                }]
            )
        )

        home_team = str(normalized_names.iloc[0]["HomeTeam"])
        away_team = str(normalized_names.iloc[0]["AwayTeam"])
        home_goals, away_goals = parse_score(score_text)

        formatted_date = match_date.strftime("%Y-%m-%d")
        season_year = season_start_year(match_date)

        row_key = (
            formatted_date,
            home_team,
            away_team,
            f"{home_goals}-{away_goals}",
        )

        if row_key in existing_keys:
            continue

        rows_to_add.append(
            {
                "Date": formatted_date,
                "Season": f"{season_year}/{season_year + 1}",
                "HomeTeam": home_team,
                "AwayTeam": away_team,
                "Score": f"{home_goals}-{away_goals}",
                "hGoal": home_goals,
                "aGoal": away_goals,
                "Division": division_name_for_match(
                    divisions, tier, match_date
                ),
                "Tier": tier,
                "Result": determine_match_result(
                    home_goals, away_goals
                ),
            }
        )
        existing_keys.add(row_key)

    if not rows_to_add:
        return pd.DataFrame(columns=existing_df.columns)

    fallback_df = pd.DataFrame(rows_to_add)
    fallback_df = fallback_df.set_index(
        pd.to_datetime(fallback_df["Date"], format="%Y-%m-%d")
    )
    fallback_df = fallback_df.drop("Date", axis=1)

    return fallback_df[existing_df.columns]


def add_current_season(
    root_dir: str,
    db_file_name: str,
    season: int,
) -> None:
    db_file = os.path.join(root_dir, db_file_name)

    df_db = pd.read_csv(db_file)
    df_db = df_db.set_index(
        pd.to_datetime(df_db.Date, format="%Y-%m-%d")
    )
    df_db = df_db.drop("Date", axis=1)

    df_db, new_primary_rows, failed_tiers = append_latest_matches(
        season,
        df_db,
    )

    # Use the temporary results for:
    # 1. any divisions whose primary download failed, or
    # 2. all divisions if the primary source returned no new rows at all.
    if failed_tiers:
        fallback_rows = load_tmp_results_matches(
            root_dir,
            df_db,
            tiers=failed_tiers,
        )
    elif new_primary_rows == 0:
        fallback_rows = load_tmp_results_matches(
            root_dir,
            df_db,
        )
    else:
        fallback_rows = pd.DataFrame(columns=df_db.columns)

    if not fallback_rows.empty:
        df_db = pd.concat([df_db, fallback_rows])

    df_db = normalize_team_names(df_db)

    pre_1992 = df_db.index <= "1992"
    df_db.loc[pre_1992, ["HomeTeam", "AwayTeam"]] = (
        df_db.loc[
            pre_1992,
            ["HomeTeam", "AwayTeam"],
        ].replace("Aldershot Town", "Aldershot")
    )

    # Aliases can become identical only after normalization. Include Date in
    # deduplication so distinct matches with the same teams and score survive.
    df_db = (
        df_db.reset_index()
        .drop_duplicates()
        .sort_values(by=["Date", "Division"])
        .set_index("Date")
    )

    df_db.to_csv(db_file, index=True)

    write_readme(
        root_dir,
        df_db.index[-1].strftime("%Y/%m/%d"),
        f"{len(df_db):,}",
    )


def append_latest_matches(
    season: int,
    df_db: pd.DataFrame,
) -> Tuple[pd.DataFrame, int, Set[int]]:
    # Compare incoming and stored fixtures using the same canonical names.
    df_db = normalize_team_names(df_db)
    total_new_rows = 0
    failed_tiers: Set[int] = set()

    two_year = season - 2000

    for div in [0, 1, 2, 3]:
        url = (
            f"https://www.football-data.co.uk/mmz4281/"
            f"{two_year}{two_year + 1}/E{div}.csv"
        )

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            df_year = pd.read_csv(
                StringIO(response.text),
                delimiter=",",
                header=0,
            )

            df_year = df_year.set_index(
                pd.to_datetime(df_year.Date, format="%d/%m/%Y")
            )

            df_year = df_year[
                ["HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]
            ]

            df_year = df_year.rename(
                columns={
                    "FTHG": "hGoal",
                    "FTAG": "aGoal",
                    "FTR": "Result",
                }
            )

            df_year["Score"] = (
                df_year["hGoal"].astype(str)
                + "-"
                + df_year["aGoal"].astype(str)
            )
            df_year["Season"] = f"{season}/{season + 1}"
            df_year["Tier"] = div + 1

            df_year["Division"] = {
                0: "Premier League",
                1: "EFL Championship",
                2: "EFL League One",
                3: "EFL League Two",
            }[div]

            df_year = df_year[df_db.columns]
            df_year = normalize_team_names(df_year)

            key_cols = ["Season", "HomeTeam", "AwayTeam"]

            existing_keys = df_db[key_cols].apply(tuple, axis=1)
            incoming_keys = df_year[key_cols].apply(tuple, axis=1)

            df_filtered = df_year[
                ~incoming_keys.isin(existing_keys)
            ].reset_index().drop_duplicates().set_index("Date")

            total_new_rows += len(df_filtered)
            if not df_filtered.empty:
                df_db = pd.concat([df_db, df_filtered])

        except requests.RequestException as exc:
            tier = div + 1
            failed_tiers.add(tier)

            print(
                f"Could not download Tier {tier} "
                f"({url}): {exc}. "
                "Will use temporary results if available."
            )

    return df_db.reset_index().drop_duplicates().set_index("Date"), total_new_rows, failed_tiers


def normalize_team_names(df: pd.DataFrame) -> pd.DataFrame:
    names_to_change = {
        "Accrington": "Accrington Stanley",
        "Aldershot": "Aldershot Town",
        "Bournemouth": "AFC Bournemouth",
        "Birmingham": "Birmingham City",
        "Blackburn": "Blackburn Rovers",
        "Bolton": "Bolton Wanderers",
        "Bradford": "Bradford City",
        "Brighton": "Brighton & Hove Albion",
        "Bristol Rvs": "Bristol Rovers",
        "Burton": "Burton Albion",
        "Cambridge": "Cambridge United",
        "Cardiff": "Cardiff City",
        "Carlisle": "Carlisle United",
        "Charlton": "Charlton Athletic",
        "Cheltenham": "Cheltenham Town",
        "Colchester": "Colchester United",
        "Coventry": "Coventry City",
        "Crewe": "Crewe Alexandra",
        "Derby": "Derby County",
        "Doncaster": "Doncaster Rovers",
        "Exeter": "Exeter City",
        "Forest Green": "Forest Green Rovers",
        "Grimsby": "Grimsby Town",
        "Harrogate": "Harrogate Town",
        "Harrogate Town A.F.C.": "Harrogate Town",
        "Hartlepool": "Hartlepool United",
        "Huddersfield": "Huddersfield Town",
        "Hull": "Hull City",
        "Ipswich": "Ipswich Town",
        "Leeds": "Leeds United",
        "Leicester": "Leicester City",
        "Lincoln": "Lincoln City",
        "Luton": "Luton Town",
        "Man City": "Manchester City",
        "Man United": "Manchester United",
        "Mansfield": "Mansfield Town",
        "Newcastle": "Newcastle United",
        "Northampton": "Northampton Town",
        "Norwich": "Norwich City",
        "Nott'm Forest": "Nottingham Forest",
        "Oldham": "Oldham Athletic",
        "Oxford": "Oxford United",
        "Peterboro": "Peterborough United",
        "Plymouth": "Plymouth Argyle",
        "Preston": "Preston North End",
        "QPR": "Queens Park Rangers",
        "Rotherham": "Rotherham United",
        "Salford": "Salford City",
        "Sheffield Weds": "Sheffield Wednesday",
        "Sheffield Wed": "Sheffield Wednesday",
        "Shrewsbury": "Shrewsbury Town",
        "Stockport": "Stockport County",
        "Stoke": "Stoke City",
        "Sutton": "Sutton United",
        "Swansea": "Swansea City",
        "Swindon": "Swindon Town",
        "Tottenham": "Tottenham Hotspur",
        "Tranmere": "Tranmere Rovers",
        "West Brom": "West Bromwich Albion",
        "West Ham": "West Ham United",
        "Wigan": "Wigan Athletic",
        "Wolves": "Wolverhampton Wanderers",
        "Wycombe": "Wycombe Wanderers",
        "York": "York City",
    }
    df = df.copy()
    for column in ["HomeTeam", "AwayTeam"]:
        if column in df:
            df[column] = df[column].replace(names_to_change, regex=False)
    return df


def skill_to_elo(skill: float, beta: float = 0.9) -> np.ndarray:
    scale = ELO_PER_NAT_LOGIT * beta * DISPLAY_MULT
    return np.round(DISPLAY_BASE + scale * (skill - DISPLAY_OFFSET), 0)


def initial_baselines() -> Dict[int, List[float]]:
    # Weak starting values; subsequent estimates use completed earlier dates only.
    return {tier: [0.5, math.log(0.7), math.log(0.8)] for tier in TIER_MEANS}


def predict_probs(skill_home: float, skill_away: float, home_advantage: float, log_draw: float, beta: float = BETA) -> np.ndarray:
    """Stable Davidson probabilities in home/draw/away order."""
    delta = beta * (skill_home - skill_away) + home_advantage
    logits = np.array([delta, log_draw, -delta])
    weights = np.exp(logits - logits.max())
    return weights / weights.sum()


def forecast_team(skill: float, variance: float, previous_tier: int, tier: int, days: int) -> Tuple[float, float]:
    """Exact calendar-time OU transition, with a promotion/relegation variance reset."""
    if days < 0:
        raise ValueError("Cannot forecast a team backwards in time")
    persistence = WEEKLY_RHO ** (days / 7.0)
    if previous_tier != tier:
        variance *= 1.5
    process = WEEKLY_PROCESS_VARIANCE * (1.0 - persistence**2) / (1.0 - WEEKLY_RHO**2)
    return persistence * skill + (1.0 - persistence) * TIER_MEANS[tier], persistence**2 * variance + process


def categorical_update(skill_home: float, var_home: float, skill_away: float, var_away: float,
                       result: str, home_advantage: float, log_draw: float) -> Tuple[float, float, float, float, np.ndarray]:
    """One Gaussian assumed-density / categorical EKF update in scalar form.

    With a=(1,0,-1), z=a'y and m=pH-pA, the score is beta*(z-m)
    and Fisher information is beta^2*(pH+pA-m^2). This is algebraically
    the two-independent-residual EKF without a ridge, clipped innovations,
    artificial observation dispersion, or confidence-dependent gain shrinkage.
    Cross-team posterior covariance is discarded (a documented approximation).
    """
    probs = predict_probs(skill_home, skill_away, home_advantage, log_draw)
    z = {"H": 1.0, "D": 0.0, "A": -1.0}[result]
    mean = probs[0] - probs[2]
    information = BETA**2 * (probs[0] + probs[2] - mean**2)
    denominator = 1.0 + (var_home + var_away) * information
    score = BETA * (z - mean)
    return (
        float(skill_home + var_home * score / denominator),
        float(var_home - var_home**2 * information / denominator),
        float(skill_away - var_away * score / denominator),
        float(var_away - var_away**2 * information / denominator),
        probs,
    )


def margin_terms(delta: float, result: str, goal_margin: int, log_excess: float) -> Tuple[float, float, float]:
    """Score in delta, observed information, and score in log excess margin.

    For a win with direction z, k=abs(goal_margin)-1 is geometric on 0,1,...
    with mean exp(log_excess + MARGIN_SLOPE*z*delta). This is conditional on
    the result, so it adds information without counting the win twice.
    Draws contain no extra margin information in this one-strength model.
    """
    if result == "D":
        return 0.0, 0.0, 0.0
    z = 1.0 if result == "H" else -1.0
    excess = abs(goal_margin) - 1
    eta = log_excess + MARGIN_SLOPE * z * delta
    # t=lambda/(1+lambda), calculated without overflowing exp(eta).
    t = 1.0 / (1.0 + math.exp(-eta)) if eta >= 0 else math.exp(eta) / (1.0 + math.exp(eta))
    score = excess - (excess + 1) * t
    information = (excess + 1) * t * (1.0 - t)
    return MARGIN_SLOPE * z * score, MARGIN_SLOPE**2 * information, score


def scoreline_update(skill_home: float, var_home: float, skill_away: float, var_away: float,
                     home_goals: int, away_goals: int, home_advantage: float, log_draw: float,
                     log_excess: float) -> Tuple[float, float, float, float, np.ndarray, float, float]:
    """One Gaussian update for Davidson(result) times geometric(winning margin).

    The returned probabilities are issued before observing this match's score.
    The last two values update home advantage and the margin intercept after
    the whole date is processed. Cross-team covariance remains approximated
    by zero, as in the results-only filter.
    """
    result = determine_match_result(home_goals, away_goals)
    probs = predict_probs(skill_home, skill_away, home_advantage, log_draw)
    z = {"H": 1.0, "D": 0.0, "A": -1.0}[result]
    mean = probs[0] - probs[2]
    delta = BETA * (skill_home - skill_away) + home_advantage
    margin_score, margin_info, intercept_score = margin_terms(delta, result, home_goals-away_goals, log_excess)
    score_delta = z - mean + margin_score
    information = BETA**2 * (probs[0] + probs[2] - mean**2 + margin_info)
    denominator = 1.0 + (var_home + var_away) * information
    score = BETA * score_delta
    return (
        float(skill_home + var_home * score / denominator),
        float(var_home - var_home**2 * information / denominator),
        float(skill_away - var_away * score / denominator),
        float(var_away - var_away**2 * information / denominator),
        probs, score_delta, intercept_score,
    )


class Team:
    def __init__(self, name: str, rank: Optional[float] = None, initDate: str = "1888-09-08", var: float = INITIAL_VARIANCE, tier: int = 1):
        self.name = name
        self.rank = [TIER_MEANS[tier] if rank is None else float(rank)]
        self.var = [float(var)]
        self.date = [initDate]
        self.tier = [int(tier)]

    def update(self, new_rank: float, new_var: float, date: str, tier: int) -> None:
        self.rank.append(new_rank)
        self.var.append(new_var)
        self.date.append(date)
        self.tier.append(tier)


def process_match_rows(rows: Iterable[pd.Series], team_list: List[Team], baselines: Dict[int, List[float]]) -> List[Dict]:
    processed_rows: List[Dict] = []
    teams = {team.name: team for team in team_list}
    pending = {tier: [0.0, 0.0, 0.0] for tier in TIER_MEANS}
    current_day = None

    def flush_baselines():
        for tier in TIER_MEANS:
            for j in range(3):
                baselines[tier][j] += pending[tier][j]
                pending[tier][j] = 0.0

    for row in rows:
        if current_day != row.Date:
            flush_baselines()
            current_day = row.Date
        for name in [row.HomeTeam, row.AwayTeam]:
            if name not in teams:
                teams[name] = Team(name, initDate=row.Date, tier=row.Tier)
                team_list.append(teams[name])
        home, away = teams[row.HomeTeam], teams[row.AwayTeam]
        date = dt.date.fromisoformat(row.Date)
        sh, vh = forecast_team(home.rank[-1], home.var[-1], home.tier[-1], row.Tier, (date-dt.date.fromisoformat(home.date[-1])).days)
        sa, va = forecast_team(away.rank[-1], away.var[-1], away.tier[-1], row.Tier, (date-dt.date.fromisoformat(away.date[-1])).days)
        hb, lk, lm = baselines[row.Tier]
        new_sh, new_vh, new_sa, new_va, probs, home_score, margin_score = scoreline_update(sh, vh, sa, va, row.hGoal, row.aGoal, hb, lk, lm)
        pending[row.Tier][0] += BASELINE_LEARNING_RATE * home_score
        pending[row.Tier][1] += BASELINE_LEARNING_RATE * ((row.Result == "D") - probs[1])
        pending[row.Tier][2] += BASELINE_LEARNING_RATE * margin_score
        match_row = row._asdict() if hasattr(row, "_asdict") else dict(row)
        match_row.update({
            "HomeRank_before": skill_to_elo(home.rank[-1]), "AwayRank_before": skill_to_elo(away.rank[-1]),
            "HomeRank_after": skill_to_elo(new_sh), "AwayRank_after": skill_to_elo(new_sa),
            "HomeWinProbability": probs[0], "DrawProbability": probs[1], "AwayWinProbability": probs[2],
        })
        home.update(new_sh, new_vh, row.Date, row.Tier)
        away.update(new_sa, new_va, row.Date, row.Tier)
        processed_rows.append(match_row)
    flush_baselines()
    return processed_rows


def load_rankings_state(path: str) -> Tuple[List[Team], Dict[int, List[float]]]:
    teams: Dict[str, Team] = {}
    baselines = {}
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != RANKINGS_STATE_HEADER:
            raise ValueError("State schema does not match the current model")
        for row in reader:
            tier = int(row["Tier"])
            if row["RecordType"] == "META":
                baselines[tier] = [float(row["HomeAdvantage"]), float(row["LogDraw"]), float(row["LogExcessMargin"])]
            elif row["RecordType"] == "TEAM":
                name, rank, variance, date = row["Team"], float(row["Rank"]), float(row["Var"]), row["Date"]
                if not math.isfinite(rank) or not math.isfinite(variance) or variance < 0:
                    raise ValueError("Invalid team state")
                if name not in teams:
                    teams[name] = Team(name, rank=rank, var=variance, initDate=date, tier=tier)
                else:
                    teams[name].update(rank, variance, date, tier)
            else:
                raise ValueError("Invalid state record type")
    if set(baselines) != set(TIER_MEANS) or not np.isfinite(list(baselines.values())).all():
        raise ValueError("Missing or invalid baseline state")
    return list(teams.values()), baselines


def save_rankings_state(path: str, teams: List[Team], baselines: Dict[int, List[float]]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RANKINGS_STATE_HEADER, lineterminator="\n")
        writer.writeheader()
        for tier, (hb, lk, lm) in sorted(baselines.items()):
            writer.writerow({"RecordType": "META", "Tier": tier, "HomeAdvantage": f"{hb:.17g}", "LogDraw": f"{lk:.17g}", "LogExcessMargin": f"{lm:.17g}"})
        for team in teams:
            for date, rank, variance, tier in zip(team.date, team.rank, team.var, team.tier):
                writer.writerow({"RecordType": "TEAM", "Team": team.name, "Date": date, "Rank": f"{rank:.17g}", "Var": f"{variance:.17g}", "Tier": tier})


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def update_rankings(root_dir: str, db_file_name: str, ranked_file: str, rankings_state: str, rebuild: bool = False) -> None:
    db_path, ranked_path, state_path = [os.path.join(root_dir, name) for name in [db_file_name, ranked_file, rankings_state]]
    manifest_path = state_path + ".meta.json"
    snapshot_path = os.path.join(root_dir, "football_model.json")
    source_hash = file_sha256(__file__)
    df_db = pd.read_csv(db_path).sort_values("Date", kind="stable").reset_index(drop=True)
    if df_db.empty:
        raise ValueError("Results database is empty")
    if df_db.duplicated(["Date", "HomeTeam", "AwayTeam"]).any():
        raise ValueError("Duplicate fixtures in results database")
    appearances = pd.concat([
        df_db[["Date", "HomeTeam"]].rename(columns={"HomeTeam": "Team"}),
        df_db[["Date", "AwayTeam"]].rename(columns={"AwayTeam": "Team"}),
    ])
    if appearances.duplicated(["Date", "Team"]).any():
        raise ValueError("A team appears more than once on the same date; resolve the source fixtures before rating them")
    expected_result = np.where(df_db.hGoal > df_db.aGoal, "H", np.where(df_db.hGoal < df_db.aGoal, "A", "D"))
    goals = df_db[["hGoal", "aGoal"]].to_numpy()
    if not np.isfinite(goals).all() or (goals < 0).any() or (goals != np.floor(goals)).any():
        raise ValueError("Goals must be nonnegative integers")
    if not np.array_equal(df_db.Result, expected_result) or not df_db.Tier.isin(TIER_MEANS).all():
        raise ValueError("Invalid results or tiers")
    existing = pd.read_csv(ranked_path) if os.path.exists(ranked_path) else pd.DataFrame()
    try:
        with open(manifest_path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        state_valid = (
            manifest.get("source_sha256") == source_hash
            and manifest.get("ranked_sha256") == file_sha256(ranked_path)
            and manifest.get("state_sha256") == file_sha256(state_path)
            and manifest.get("snapshot_sha256") == file_sha256(snapshot_path)
            and manifest.get("matches") == len(existing)
        )
    except (OSError, ValueError):
        state_valid = False
    # Only append to an unchanged chronological prefix. Same-date additions also
    # require replay: home/draw parameters are updated after a complete date.
    prefix_valid = (
        not existing.empty and len(existing) <= len(df_db)
        and set(df_db.columns).issubset(existing.columns)
        and existing[df_db.columns].equals(df_db.iloc[:len(existing)])
        and (len(existing) == len(df_db) or df_db.iloc[len(existing)].Date > existing.iloc[-1].Date)
    )
    teams, baselines = [], initial_baselines()
    if not rebuild and state_valid and prefix_valid:
        if len(existing) == len(df_db):
            print("Rankings and model state are current.")
            return
        try:
            teams, baselines = load_rankings_state(state_path)
        except (OSError, ValueError, KeyError):
            teams, baselines = [], initial_baselines()
    if not teams:
        print("Rebuilding rankings from the complete chronological results database.")
        existing = pd.DataFrame()
    processed = process_match_rows(df_db.iloc[len(existing):].itertuples(index=False), teams, baselines)
    combined = pd.concat([existing, pd.DataFrame(processed)], ignore_index=True)
    rank_cols = ["HomeRank_before", "AwayRank_before", "HomeRank_after", "AwayRank_after"]
    combined[rank_cols] = combined[rank_cols].astype(int)
    # Canonical precision gives byte-identical full and incremental outputs.
    for col in ["HomeWinProbability", "DrawProbability", "AwayWinProbability"]:
        combined[col] = combined[col].round(12)
    snapshot = {
        "model_version": MODEL_VERSION, "as_of": str(df_db.Date.max()), "matches": len(df_db),
        "beta": BETA, "weekly_rho": WEEKLY_RHO, "weekly_process_variance": WEEKLY_PROCESS_VARIANCE,
        "initial_variance": INITIAL_VARIANCE, "baseline_learning_rate": BASELINE_LEARNING_RATE,
        "margin_slope": MARGIN_SLOPE, "margin_distribution": "geometric_excess_conditional_on_result",
        "tier_means": TIER_MEANS,
        "tiers": {tier: {"home_advantage": values[0], "log_draw": values[1], "log_excess_margin": values[2]} for tier, values in baselines.items()},
        "teams": {team.name: {"skill": team.rank[-1], "variance": team.var[-1], "date": team.date[-1], "tier": team.tier[-1]} for team in teams},
    }
    # Write the manifest last: a crash between replacements invalidates the saved
    # hashes and automatically forces a full replay on the next invocation.
    for destination in [ranked_path, state_path, snapshot_path]:
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(ranked_path + ".tmp", index=False)
    snapshot["ranked_sha256"] = file_sha256(ranked_path + ".tmp")
    snapshot["source_sha256"] = source_hash
    save_rankings_state(state_path + ".tmp", teams, baselines)
    with open(snapshot_path + ".tmp", "w", encoding="utf-8") as handle:
        json.dump(snapshot, handle, indent=2, allow_nan=False)
        handle.write("\n")
    for destination in [ranked_path, state_path, snapshot_path]:
        os.replace(destination + ".tmp", destination)
    manifest = {
        "model_version": MODEL_VERSION, "source_sha256": source_hash,
        "results_sha256": file_sha256(db_path), "ranked_sha256": file_sha256(ranked_path),
        "state_sha256": file_sha256(state_path), "snapshot_sha256": file_sha256(snapshot_path),
        "matches": len(df_db), "last_result_date": str(df_db.Date.max()),
    }
    with open(manifest_path + ".tmp", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    os.replace(manifest_path + ".tmp", manifest_path)
    print(f"Saved {len(combined):,} chronological matches using {MODEL_VERSION}.")


def write_readme(root_dir: str, update_date: str, num_matches: str) -> None:
    readme = (
        '# English Football League Data\n'
        '\n'
        '## Contents\n'
        '\n'
        '- [Overview](#overview)\n'
        '- [Dataset index](#dataset-index)\n'
        '- [Detailed schemas](#detailed-schemas)\n'
        '- [Club naming conventions](#club-naming-conventions)\n'
        '- [Sources and tools](#sources-and-tools)\n'
        '- [Licence and attribution](#licence-and-attribution)\n'
        '- [Contact](#contact)\n'
        '\n'
        '## Overview\n'
        '\n'
        f'This is a plain text database of all England football (soccer) league results from 1888 to {update_date} (covering {num_matches} matches).\n'
        '\n'
        'The database is updated roughly every two days for the top four tiers in English football: Premier League, EFL Championship, EFL League One and EFL League Two.\n'
        '\n'
        'The six CSV files cover match results, team-strength ratings and probabilities, division names, points deductions and additions, club logos and colours, and periods of league participation.\n'
        '\n'
        '## Dataset index\n'
        '\n'
        'Each file link opens the CSV in this repository. The schema links jump to its documentation below.\n'
        '\n'
        '| Dataset file | Contents | Detailed schema |\n'
        '| --- | --- | --- |\n'
        f'| [`EnglandLeagueResults.csv`](EnglandLeagueResults.csv) | Match results from 1888 to {update_date} ({num_matches} matches). | [View schema](#england-league-results) |\n'
        '| [`EnglandLeagueResults_wRanks.csv`](EnglandLeagueResults_wRanks.csv) | Match results with chronological team-strength ratings and pre-match probabilities. | [View schema](#england-league-results-with-team-strength-rankings) |\n'
        '| [`EnglandLeagueNames.csv`](EnglandLeagueNames.csv) | Division names, their active seasons and their tiers. | [View schema](#england-league-names) |\n'
        '| [`EnglishTeamPointDeductions.csv`](EnglishTeamPointDeductions.csv) | Points deductions and additions, effective dates and reasons. | [View schema](#english-team-point-deductions) |\n'
        '| [`EnglishTeamLogos.csv`](EnglishTeamLogos.csv) | Club logos/crests and primary and secondary club colours. | [View schema](#english-team-logos) |\n'
        '| [`EnglishTeamActivePeriods.csv`](EnglishTeamActivePeriods.csv) | Club participation periods in the top four tiers, with short team names. | [View schema](#english-team-active-years) |\n'
        '\n'
        '## Detailed schemas\n'
        '\n'
        '### England League Results\n'
        '\n'
        '**File:** [`EnglandLeagueResults.csv`](EnglandLeagueResults.csv)\n'
        '\n'
        'A comma (",") delimited CSV file of English football league results, with the following columns:\n'
        '\n'
        '| Column | Details |\n'
        '| ------ | ------- |\n'
        '| Date | the day of the match (string; format "YYYY-MM-DD") |\n'
        '| Season | the season the match took place in (string; format "YYYY/YYYY") |\n'
        '| HomeTeam | the home team name (string) |\n'
        '| AwayTeam | the away team name (string) |\n'
        '| Score | the final score (string; format "X-Z") |\n'
        '| hGoal | number of goals scored by the home team (integer; "X" from the "Score" column) |\n'
        '| aGoal | number of goals scored by the away team (integer; "Z" from the "Score" column) |\n'
        '| Division | name of the division the match was played in (string) |\n'
        '| Tier | numerical representation of the tier which the match was from: 1, 2, 3 or 4, where "1" is the top tier (currently the Premier League) (integer) |\n'
        '| Result | the result "H" (home win), "A" (away win), "D" (draw) (string) |\n'
        '\n'
        '### England League Results with team strength rankings\n'
        '\n'
        '**File:** [`EnglandLeagueResults_wRanks.csv`](EnglandLeagueResults_wRanks.csv)\n'
        '\n'
        'This file contains the same data as `EnglandLeagueResults.csv`, with chronological team-strength ratings and probabilities issued before each result. The `*_before` ratings are the previous posterior ratings; the probability columns also include the elapsed-time forecast step.\n'
        '\n'
        'The database is a comma (",") delimited csv file with the following columns:\n'
        '\n'
        '| Column | Details |\n'
        '| ------ | ------- |\n'
        '| Date | the day of the match (string; format "YYYY-MM-DD") |\n'
        '| Season | the season the match took place in (string; format "YYYY/YYYY") |\n'
        '| HomeTeam | the home team name (string) |\n'
        '| AwayTeam | the away team name (string) |\n'
        '| Score | the final score (string; format "X-Z") |\n'
        '| hGoal | number of goals scored by the home team (integer; "X" from the "Score" column) |\n'
        '| aGoal | number of goals scored by the away team (integer; "Z" from the "Score" column) |\n'
        '| Division | name of the division the match was played in (string) |\n'
        '| Tier | numerical representation of the tier which the match was from: 1, 2, 3 or 4, where "1" is the top tier (currently the Premier League) (integer) |\n'
        '| Result | the result "H" (home win), "A" (away win), "D" (draw) (string) |\n'
        '| HomeRank_before | the ranking of the home team before the fixture was played (integer) |\n'
        '| AwayRank_before | the ranking of the away team before the fixture was played (integer) |\n'
        '| HomeRank_after | the ranking of the home team after the fixture was played (integer) |\n'
        '| AwayRank_after | the ranking of the away team after the fixture was played (integer) |\n'
        '| HomeWinProbability | probability of a home win issued before the match |\n'
        '| DrawProbability | probability of a draw issued before the match |\n'
        '| AwayWinProbability | probability of an away win issued before the match |\n'
        '\n'
        '### England League Names\n'
        '\n'
        '**File:** [`EnglandLeagueNames.csv`](EnglandLeagueNames.csv)\n'
        '\n'
        'A comma (",") delimited csv file of the names of the English football divisions and the years they were active. It has the following columns:\n'
        '\n'
        '| Column | Details |\n'
        '| ------ | ------- |\n'
        '| Name | the name of the division (string) |\n'
        '| Years Active | the seasons [inclusive - exclusive) that the name was/is active (string) |\n'
        '| Tier | numerical representation of the tier which the match was from: 1, 2, 3 or 4, where "1" is the top tier (integer) |\n'
        '\n'
        '### English Team Point Deductions\n'
        '\n'
        '**File:** [`EnglishTeamPointDeductions.csv`](EnglishTeamPointDeductions.csv)\n'
        '\n'
        'A comma (",") delimited csv file of all point deductions (and in two cases, additions), with reasoning, applied to English football league teams.\n'
        '\n'
        'It has the following columns:\n'
        '\n'
        '| Column | Details |\n'
        '| ------ | ------- |\n'
        '| Season | season string, for example 2024/2025 |\n'
        '| Date | effective date of the adjustment (YYYY-MM-DD); historical forecasts must exclude later adjustments |\n'
        '| Team | the team who the deduction was applied to (string) |\n'
        '| Pts_deducted | the number of points deducted (a negative value means a point addition) (integer) |\n'
        '| Notes | the reasoning for the points deduction (string) |\n'
        '\n'
        '### English Team Logos\n'
        '\n'
        '**File:** [`EnglishTeamLogos.csv`](EnglishTeamLogos.csv)\n'
        '\n'
        'A comma (",") delimited csv file of all (known) English football league team logos/crests. The primary and secondary club colours are also included, these are not necessarily the same colours as the logo/crest. Where this should be white, a slightly off white colour (#808080) is used.\n'
        '\n'
        'It has the following columns:\n'
        '\n'
        '| Column | Details |\n'
        '| ------ | ------- |\n'
        '| Team Name | the English football league team name (matching the names in EnglandLeagueResults.csv) |\n'
        '| URL | the link to image (png or svg), usually on Wikipedia |\n'
        '| PriColour | the primary club colour as a Hex colour code |\n'
        '| SecColour | the secondary club colour as a Hex colour code |\n'
        '\n'
        '### English Team Active Years\n'
        '\n'
        '**File:** [`EnglishTeamActivePeriods.csv`](EnglishTeamActivePeriods.csv)\n'
        '\n'
        'A comma (",") delimited csv file of the periods which each club, which appears at least once in the database, was active within the top four tiers of English football (Premier League and English Football League). Breaks in appearances in these divisions are separated by a semicolon (";").\n'
        '\n'
        'It has the following columns:\n'
        '\n'
        '| Column | Details |\n'
        '| ------ | ------- |\n'
        '| Team | the English football league team name (matching the names in EnglandLeagueResults.csv) |\n'
        '| ShortName | the short form name of the team (if they have one). E.g. "West Ham United" becomes "West Ham", "Manchester City" becomes "Man City" |\n'
        '| Years | semicolon delimited list of active years, e.g. of the form YYYY-YYYY; YYYY-YYYY; YYYY-present. YYYY represents the initial year of that season, e.g. a club appearing in the top 4 tiers in the 1991/1992 season, leaving in 1995/1996 and then coming back from 2004 to present day would be: 1991-1995; 2004-present |\n'
        '\n'
        '## Club naming conventions\n'
        '\n'
        'Team names can be confusing across such a long record. The notes below answer the most common questions I have received about the names used in the database:\n'
        '\n'
        '* [Accrington F.C.](https://en.wikipedia.org/wiki/Accrington_F.C.) is a different team to [Accrington Stanley](https://en.wikipedia.org/wiki/Accrington_Stanley_F.C.). Accrington F.C. were one of the founder members of the Football League, but were dissolved in 1896.\n'
        '* [Aldershot](https://en.wikipedia.org/wiki/Aldershot_F.C.) and [Aldershot Town](https://en.wikipedia.org/wiki/Aldershot_Town_F.C.) are listed as separate teams (Aldershot Town was formed in the spring of 1992 after the closure of Aldershot).\n'
        '* Throughout the database we refer to [Arsenal](https://en.wikipedia.org/wiki/Arsenal_F.C.) not "Woolwich Arsenal" (from 1893-1914) nor "The Arsenal" (from April 1914 - November 1919).\n'
        '* [Brighton & Hove Albion](https://en.wikipedia.org/wiki/Brighton_%26_Hove_Albion_F.C.), [New Brighton Tower](https://en.wikipedia.org/wiki/New_Brighton_Tower_F.C.) and [New Brighton](https://en.wikipedia.org/wiki/New_Brighton_A.F.C.) are all different clubs. New Brighton Tower were in existence from 1896-1901 and whilst Brighton & Hove Albion were formed in 1901, the "spiritual" successor to New Brighton Tower, was New Brighton (1921-1983 and 1993-2012; originally formed by the relocation of [South Liverpool](https://en.wikipedia.org/wiki/South_Liverpool_F.C._(1890s)))\n'
        '* Burton [Swifts](https://en.wikipedia.org/wiki/Burton_Swifts_F.C.), [Wanderers](https://en.wikipedia.org/wiki/Burton_Wanderers_F.C.), [United](https://en.wikipedia.org/wiki/Burton_United_F.C.), [Town](https://en.wikipedia.org/wiki/Burton_Town_F.C.) and [Albion](https://en.wikipedia.org/wiki/Burton_Albion_F.C.) are all different teams. Burton Swifts joined with Wanderers to form Burton United in 1901, which in 1924 merged with Burton Town and in 1950 merged with the newly formed Burton Albion.\n'
        '* The Gateshead in the database refers to [Gateshead A.F.C](https://en.wikipedia.org/wiki/Gateshead_A.F.C.) not [Gateshead F.C.](https://en.wikipedia.org/wiki/Gateshead_F.C.).\n'
        '* Whilst [Leeds United](https://en.wikipedia.org/wiki/Leeds_United_F.C.) were formed following/replacing [Leeds City](https://en.wikipedia.org/wiki/Leeds_City_F.C.) (and played in the same ground). No players or management from Leeds City moved to Leeds United so we treat them as separate football clubs.\n'
        '* [Middlesbrough Ironopolis](https://en.wikipedia.org/wiki/Middlesbrough_Ironopolis_F.C.) (1889-1894) is separate team from [Middlesbrough](https://en.wikipedia.org/wiki/Middlesbrough_F.C.) (1876-).\n'
        '* [Rotherham County](https://en.wikipedia.org/wiki/Rotherham_County_F.C.) merged with [Rotherham Town](https://en.wikipedia.org/wiki/Rotherham_Town_F.C._(1899)) in 1925 to form [Rotherham United](https://en.wikipedia.org/wiki/Rotherham_United_F.C.).\n'
        '* Throughout the database we refer to [Stevenage](https://en.wikipedia.org/wiki/Stevenage_F.C.) not Stevenage Borough ("Borough" was dropped in June 2010).\n'
        '* [Wigan Athletic](https://en.wikipedia.org/wiki/Wigan_Athletic_F.C.) were formed (1932) a year after [Wigan Borough](https://en.wikipedia.org/wiki/Wigan_Borough_F.C.) were wound up (1931) and we treat them separately. Wigan Athletic was the sixth attempt to create a stable football club in Wigan following the dissolving of Wigan A.F.C., [County](https://en.wikipedia.org/wiki/Wigan_County_F.C.) (1897-1900), [United](https://en.wikipedia.org/wiki/Wigan_United_A.F.C.) (1896-1914), [Town](https://en.wikipedia.org/wiki/Wigan_Town_A.F.C.) (1905-1908) and [Borough](https://en.wikipedia.org/wiki/Wigan_Borough_F.C.) (1920-1931).\n'
        '\n'
        '## Sources and tools\n'
        '\n'
        '### Data sources\n'
        '\n'
        'The 1888-2016 data is based on that from the [Rec.Sport.Soccer Statistics Foundation](https://www.rsssf.org/) and James P. Curley ([2016](http://dx.doi.org/10.5281/zenodo.13158)).\n'
        '\n'
        '### Tools\n'
        '\n'
        'A number of tools making use of the data, such as a [league table generator](https://seanelvidge.com/leaguetable) and [head-to-head statistics](https://seanelvidge.com/h2h) are available at [seanelvidge.com/tools](https://seanelvidge.com/tools/)\n'
        '\n'
        '## Licence and attribution\n'
        '\n'
        'Prof. Sean Elvidge licenses his rights in the database and its accompanying documentation under the [Creative Commons Attribution 4.0 International licence (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/). This permits copying, sharing and adapting the licensed material for any purpose, including commercial use, with attribution. See [LICENCE](LICENCE) for the full terms and the scope of this grant.\n'
        '\n'
        'Suggested attribution:\n'
        '\n'
        '> English Football League Data, constructed and updated by Prof. Sean Elvidge. [Source repository](https://github.com/seanelvidge/England-football-results). Sean Elvidge\'s contributions are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); source material may have separate terms.\n'
        '\n'
        'When sharing the licensed material, retain the attribution and licence notice, link to the source and licence, and indicate any changes you have made. Existing source credits must also be retained where required.\n'
        '\n'
        'Third-party source data and linked club logos may have separate rights and usage terms. The [source notices in LICENCE](LICENCE.md) identify known licensing limitations; unrestricted commercial reuse of the complete dataset has not been established.\n'
        '\n'
        '## Contact\n'
        '\n'
        'If you have any corrections, comments or additional information, please feel free to open an [issue](https://github.com/seanelvidge/England-football-results/issues) or a [pull request](https://github.com/seanelvidge/England-football-results/pulls), or email me at `seanelvidge[at]gmail.com`.\n'
        '\n'
        'Please also let me know if you use this data. I am interested in hearing how it is being used. This is a request, not a condition of the licence.\n'
    )

    with open(os.path.join(root_dir, "README.md"), "w", encoding="utf-8") as handle:
        handle.write(readme)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update England football results and rankings.")
    parser.add_argument("--root-dir", default=os.environ.get("FOOTBALL_RESULTS_ROOT_DIR", "."))
    parser.add_argument("--db-file", default="EnglandLeagueResults.csv")
    parser.add_argument("--ranked-file", default="EnglandLeagueResults_wRanks.csv")
    parser.add_argument("--rankings-state", default=".github/rankings.csv")
    parser.add_argument("--rankings-pickle", dest="rankings_state", help=argparse.SUPPRESS)
    parser.add_argument("--rankings-only", action="store_true", help="Use local results without downloading matches.")
    parser.add_argument("--rebuild-rankings", action="store_true", help="Replay the entire history, ignoring saved ratings.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    today = dt.date.today()
    season = today.year if today.month >= 8 else today.year - 1

    if not args.rankings_only:
        add_current_season(args.root_dir, args.db_file, season)
    update_rankings(args.root_dir, args.db_file, args.ranked_file, args.rankings_state, rebuild=args.rebuild_rankings)
