import argparse
import datetime as dt
import os
import pickle
from datetime import datetime
from io import StringIO
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd
import requests


ELO_PER_NAT_LOGIT = 400.0 / np.log(10.0)
NIS_EWMA_DEFAULT = 3.0
PHI0_DEFAULT = 1.0
DISPLAY_BASE = 1000.0
DISPLAY_MULT = 2.0
DISPLAY_OFFSET = 0.0


def add_current_season(root_dir: str, db_file_name: str, season: int) -> None:
    db_file = os.path.join(root_dir, db_file_name)
    df_db = pd.read_csv(db_file)
    df_db = df_db.set_index(pd.to_datetime(df_db.Date, format="%Y-%m-%d"))
    df_db = df_db.drop("Date", axis=1)

    df_db = append_latest_matches(season, df_db)
    df_db = df_db.reset_index().sort_values(by=["Date", "Division"]).set_index("Date")
    df_db = normalize_team_names(df_db)

    pre_1992 = df_db.index <= "1992"
    df_db.loc[pre_1992, ["HomeTeam", "AwayTeam"]] = (
        df_db.loc[pre_1992, ["HomeTeam", "AwayTeam"]].replace("Aldershot Town", "Aldershot")
    )

    df_db.to_csv(db_file, index=True)
    write_readme(root_dir, df_db.index[-1].strftime("%Y/%m/%d"), f"{len(df_db):,}")


def append_latest_matches(season: int, df_db: pd.DataFrame) -> pd.DataFrame:
    two_year = season - 2000
    for div in [0, 1, 2, 3]:
        url = f"https://www.football-data.co.uk/mmz4281/{two_year}{two_year + 1}/E{div}.csv"
        response = requests.get(url, timeout=30)
        response.raise_for_status()

        df_year = pd.read_csv(StringIO(response.text), delimiter=",", header=0)
        df_year = df_year.set_index(pd.to_datetime(df_year.Date, format="%d/%m/%Y"))
        df_year = df_year[["HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"]]
        df_year = df_year.rename(columns={"FTHG": "hGoal", "FTAG": "aGoal", "FTR": "Result"})
        df_year["Score"] = df_year["hGoal"].astype(str) + "-" + df_year["aGoal"].astype(str)
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
        df_filtered = df_year[~incoming_keys.isin(existing_keys)]
        df_db = pd.concat([df_db, df_filtered])

    return df_db.drop_duplicates()


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
    }
    return df.replace(names_to_change, regex=False)


def skill_to_elo(skill: float, beta: float = 0.9) -> np.ndarray:
    scale = ELO_PER_NAT_LOGIT * beta * DISPLAY_MULT
    return np.round(DISPLAY_BASE + scale * (skill - DISPLAY_OFFSET), 0)


def era_probs_from_year(year: int) -> Tuple[float, float, float]:
    home = (year - 1888) * (-0.141579) + 60.5636
    away = (year - 1888) * (0.075714) + 19.4769
    draw = (year - 1888) * (0.065851) + 19.9608
    probs = np.clip(np.array([home, draw, away], dtype=float), 0.001, None)
    probs /= probs.sum()
    return float(probs[0]), float(probs[2]), float(probs[1])


def delta_base_and_kappa(year: int) -> Tuple[float, float]:
    p_home, p_away, p_draw = era_probs_from_year(year)
    delta_base = 0.5 * np.log(p_home / p_away)
    kappa = (p_draw / (1.0 - p_draw)) * 2.0 * np.cosh(delta_base)
    return delta_base, kappa


def result_vector(result: str) -> np.ndarray:
    if result == "H":
        return np.array([1.0, 0.0, 0.0])
    if result == "D":
        return np.array([0.0, 1.0, 0.0])
    if result == "A":
        return np.array([0.0, 0.0, 1.0])
    raise ValueError(f"Unknown result {result}")


def predict_probs(skill_home: float, skill_away: float, year: int, beta: float = 1.0) -> np.ndarray:
    delta_base, kappa = delta_base_and_kappa(year)
    delta = beta * (skill_home - skill_away) + delta_base
    up = np.exp(delta)
    down = np.exp(-delta)
    denom = up + down + kappa
    return np.array([up / denom, kappa / denom, down / denom])


def jacobian(skill_home: float, skill_away: float, year: int, beta: float = 1.0) -> np.ndarray:
    delta_base, kappa = delta_base_and_kappa(year)
    delta = beta * (skill_home - skill_away) + delta_base
    up = np.exp(delta)
    down = np.exp(-delta)
    denom = up + down + kappa
    denom_sq = denom**2

    dp_home = (up * (2.0 * down + kappa)) / denom_sq
    dp_away = (-down * (2.0 * up + kappa)) / denom_sq
    dp_draw = (-kappa * (up - down)) / denom_sq

    return np.array(
        [
            [beta * dp_home, -beta * dp_home],
            [beta * dp_draw, -beta * dp_draw],
            [beta * dp_away, -beta * dp_away],
        ]
    )


def safe_probs(probs: np.ndarray, floor: float = 1e-3) -> np.ndarray:
    probs = np.clip(probs, floor, 1.0 - floor)
    probs /= probs.sum()
    return probs


def clip_innovation(innovation: np.ndarray, p_max: float, c_lo: float = 0.70, c_hi: float = 0.35, t: float = 0.90) -> Tuple[np.ndarray, float]:
    cap = c_lo if p_max <= t else c_lo - (c_lo - c_hi) * (p_max - t) / (1.0 - t)
    norm = np.linalg.norm(innovation)
    clipped = float(norm > cap)
    if norm <= cap:
        return innovation, clipped
    return innovation * (cap / norm), clipped


def q_match_adaptive(days_since_prev: int, p_max: float, base: float = 0.003, per_day: float = 0.0003, cap: float = 0.01, t_hi: float = 0.88, min_frac: float = 0.1) -> float:
    q_val = base + per_day * max(0, days_since_prev)
    if p_max <= t_hi:
        frac = 1.0
    else:
        frac = 1.0 - 0.97 * (p_max - t_hi) / (1.0 - t_hi)
        frac = max(frac, min_frac)
    return min(q_val * frac, cap)


def certainty_phi_multiplier(p_max: float, t_hi: float = 0.88, a_hi: float = 10.0, lo: float = 1.0, hi: float = 5.0) -> float:
    value = 1.0 + a_hi * max(0.0, float(p_max) - t_hi)
    return float(np.clip(value, lo, hi))


def damp_covariance(cov: np.ndarray, p_max: float, lo: float = 0.985, hi: float = 0.97, t: float = 0.88) -> np.ndarray:
    if p_max <= t:
        damping = lo
    else:
        damping = lo - (lo - hi) * (p_max - t) / (1.0 - t)
    return damping * cov + (1 - damping) * np.diag(np.minimum(np.diag(cov), 1.0))


def damp_pminus(p_minus: np.ndarray, p_max: float, lo: float = 0.992, hi: float = 0.965, t: float = 0.86) -> np.ndarray:
    if p_max <= t:
        damping = lo
    else:
        damping = lo - (lo - hi) * (p_max - t) / (1.0 - t)
    return damping * p_minus + (1 - damping) * np.diag(np.minimum(np.diag(p_minus), 1.0))


def gain_shrink(p_max: float, t: float = 0.86, g_min: float = 0.65) -> float:
    if p_max <= t:
        return 1.0
    return 1.0 - (1.0 - g_min) * (p_max - t) / (1.0 - t)


def ekf_update_one_match(
    skill_home: float,
    var_home: float,
    tier_home: float,
    skill_away: float,
    var_away: float,
    tier_away: float,
    year: int,
    result: str,
    tier: int,
    beta: float = 0.9,
    eps: float = 1e-9,
    days_since_prev_home: int = 7,
    days_since_prev_away: int = 7,
    nis_ewma: float = NIS_EWMA_DEFAULT,
    nis_target: float = 3.0,
    phi0: float = PHI0_DEFAULT,
    alpha_nis: float = 0.02,
    k_phi: float = 0.25,
    phi0_min: float = 0.3,
    phi0_max: float = 3.0,
) -> Tuple[float, float, float, float, float, float]:
    tier_means = {1: 1.5, 2: 0.3, 3: -0.3, 4: -0.6}
    prior_state = np.array([skill_home, skill_away], dtype=float)

    var_home = var_home if tier_home == tier else var_home * 1.5
    var_away = var_away if tier_away == tier else var_away * 1.5
    prior_cov = np.array([[var_home, 0.0], [0.0, var_away]], dtype=float)

    rho = 0.997
    transition = np.eye(2) * rho
    state_minus = np.array(
        [
            rho * prior_state[0] + (1 - rho) * tier_means[tier],
            rho * prior_state[1] + (1 - rho) * tier_means[tier],
        ]
    )

    probs = safe_probs(predict_probs(state_minus[0], state_minus[1], year, beta=beta))
    h_mat = jacobian(state_minus[0], state_minus[1], year, beta=beta)
    certainty = float(probs.max())

    q_home = q_match_adaptive(days_since_prev_home, certainty, base=0.002, per_day=0.0002, cap=0.008, t_hi=0.86, min_frac=0.03)
    q_away = q_match_adaptive(days_since_prev_away, certainty, base=0.002, per_day=0.0002, cap=0.008, t_hi=0.86, min_frac=0.03)
    process_cov = np.diag([q_home, q_away])

    p_minus = transition @ prior_cov @ transition.T + process_cov
    p_minus = damp_pminus(p_minus, certainty, t=0.86)

    phi_eff = phi0 * certainty_phi_multiplier(certainty, t_hi=0.86, a_hi=10.0, lo=1.0, hi=3.0)
    obs_cov = (np.diag(probs) - np.outer(probs, probs)) * phi_eff + np.eye(3) * eps

    innovation = result_vector(result) - probs
    innovation, _ = clip_innovation(innovation, certainty, c_lo=1.4, c_hi=0.8, t=0.92)

    system_cov = h_mat @ p_minus @ h_mat.T + obs_cov + np.eye(3) * eps
    kalman_gain = p_minus @ h_mat.T @ np.linalg.pinv(system_cov)
    kalman_gain *= gain_shrink(certainty, t=0.86, g_min=0.65)

    state_after = state_minus + kalman_gain @ innovation
    identity = np.eye(2)
    cov_after = (identity - kalman_gain @ h_mat) @ p_minus @ (identity - kalman_gain @ h_mat).T + kalman_gain @ obs_cov @ kalman_gain.T
    cov_after = 0.5 * (cov_after + cov_after.T) + np.eye(2) * eps
    cov_after = damp_covariance(cov_after, certainty)

    nis = float(innovation.T @ np.linalg.pinv(system_cov) @ innovation)
    nis_ewma = (1 - alpha_nis) * nis_ewma + alpha_nis * nis
    phi0 *= np.exp(k_phi * (nis_ewma - nis_target) / nis_target)
    phi0 = float(np.clip(phi0, phi0_min, phi0_max))

    return float(state_after[0]), float(cov_after[0, 0]), float(state_after[1]), float(cov_after[1, 1]), float(nis_ewma), float(phi0)


class Team:
    def __init__(self, name: str, rank: float = 0, initDate: str = "1888-09-09", var: float = 0.5, tier: int = 1):
        self.name = name
        self.rank = np.array(rank, ndmin=1, dtype=float)
        self.var = np.array(var, ndmin=1, dtype=float)
        self.date = [initDate]
        self.tier = np.array(tier, ndmin=1, dtype=float)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Team) and self.name == other.name

    def update(self, new_rank: float, new_var: float, date: str, tier: int) -> None:
        self.rank = np.append(self.rank, new_rank)
        self.var = np.append(self.var, new_var)
        self.date.append(date)
        self.tier = np.append(self.tier, tier)


def get_team(team_list: List[Team], team_name: str, init_date: str, tier: int) -> Team:
    try:
        return team_list[team_list.index(Team(team_name))]
    except ValueError:
        team = Team(team_name, rank=0, var=0.0, initDate=init_date, tier=tier)
        team_list.append(team)
        return team


def process_match_rows(rows: Iterable[pd.Series], team_list: List[Team], nis_ewma: float, phi0: float) -> Tuple[List[Dict], float, float]:
    processed_rows: List[Dict] = []

    for row in rows:
        home_team = get_team(team_list, row.HomeTeam, row.Date, row.Tier)
        away_team = get_team(team_list, row.AwayTeam, row.Date, row.Tier)

        current_date = datetime.strptime(row.Date, "%Y-%m-%d")
        last_home = datetime.strptime(home_team.date[-1], "%Y-%m-%d")
        last_away = datetime.strptime(away_team.date[-1], "%Y-%m-%d")

        out_home_skill, out_home_var, out_away_skill, out_away_var, nis_ewma, phi0 = ekf_update_one_match(
            home_team.rank[-1],
            home_team.var[-1],
            home_team.tier[-1],
            away_team.rank[-1],
            away_team.var[-1],
            away_team.tier[-1],
            int(row.Date.split("-")[0]),
            row.Result,
            row.Tier,
            days_since_prev_home=(current_date - last_home).days,
            days_since_prev_away=(current_date - last_away).days,
            nis_ewma=nis_ewma,
            phi0=phi0,
        )

        home_rank_before = skill_to_elo(home_team.rank[-1])
        away_rank_before = skill_to_elo(away_team.rank[-1])

        home_team.update(out_home_skill, out_home_var, row.Date, row.Tier)
        away_team.update(out_away_skill, out_away_var, row.Date, row.Tier)

        match_row = row._asdict() if hasattr(row, "_asdict") else dict(row)
        match_row["HomeRank_before"] = home_rank_before
        match_row["AwayRank_before"] = away_rank_before
        match_row["HomeRank_after"] = skill_to_elo(home_team.rank[-1])
        match_row["AwayRank_after"] = skill_to_elo(away_team.rank[-1])
        processed_rows.append(match_row)

    return processed_rows, nis_ewma, phi0


def load_rankings_state(rankings_pickle: str) -> Tuple[List[Team], float, float]:
    if os.path.exists(rankings_pickle):
        try:
            with open(rankings_pickle, "rb") as handle:
                state = pickle.load(handle)
        except (pickle.UnpicklingError, EOFError, AttributeError, ValueError) as exc:
            print(f"Could not load rankings state from {rankings_pickle}: {exc}. Rebuilding rankings from scratch.")
            return [], NIS_EWMA_DEFAULT, PHI0_DEFAULT
        if isinstance(state, dict):
            return state.get("teams", []), state.get("nis_ewma", NIS_EWMA_DEFAULT), state.get("phi0", PHI0_DEFAULT)
        return state, NIS_EWMA_DEFAULT, PHI0_DEFAULT
    return [], NIS_EWMA_DEFAULT, PHI0_DEFAULT


def save_rankings_state(rankings_pickle: str, team_list: List[Team], nis_ewma: float, phi0: float) -> None:
    with open(rankings_pickle, "wb") as handle:
        pickle.dump({"teams": team_list, "nis_ewma": nis_ewma, "phi0": phi0}, handle, protocol=pickle.HIGHEST_PROTOCOL)


def update_rankings(root_dir: str, db_file_name: str, ranked_file: str, rankings_pickle: str) -> None:
    db_path = os.path.join(root_dir, db_file_name)
    ranked_path = os.path.join(root_dir, ranked_file)
    rankings_pickle_path = os.path.join(root_dir, rankings_pickle)

    df_db = pd.read_csv(db_path)
    existing_ranked = pd.read_csv(ranked_path) if os.path.exists(ranked_path) else pd.DataFrame()
    key_cols = ["Date", "HomeTeam", "AwayTeam", "Score"]

    if not existing_ranked.empty:
        existing_keys = set(existing_ranked[key_cols].apply(tuple, axis=1))
    else:
        existing_keys = set()

    new_rows = df_db[~df_db[key_cols].apply(tuple, axis=1).isin(existing_keys)]
    if new_rows.empty:
        return

    team_list, nis_ewma, phi0 = load_rankings_state(rankings_pickle_path)
    rows_to_process = df_db.itertuples(index=False) if not team_list else new_rows.itertuples(index=False)
    if not team_list:
        existing_ranked = pd.DataFrame()

    processed_rows, nis_ewma, phi0 = process_match_rows(rows_to_process, team_list, nis_ewma, phi0)
    ranked_updates = pd.DataFrame(processed_rows)
    ranked_combined = pd.concat([existing_ranked, ranked_updates], ignore_index=True)
    rank_cols = ["HomeRank_before", "AwayRank_before", "HomeRank_after", "AwayRank_after"]
    ranked_combined[rank_cols] = ranked_combined[rank_cols].astype(int)

    ranked_combined.to_csv(ranked_path, index=False)
    save_rankings_state(rankings_pickle_path, team_list, nis_ewma, phi0)


def write_readme(root_dir: str, update_date: str, num_matches: str) -> None:
    readme = [
        (
            "# England League Results (EnglandLeagueResults.csv)\n"
            f"This is a plain text database of all England football (soccer) league results from 1888 to {update_date} (covering {num_matches} matches).\n"
            "\n"
            "The database is updated roughly every two days for the top four tiers in English football: Premier League, EFL Championship, EFL League One and EFL League Two.\n"
            "\n"
            'The database is a comma (",") delimited csv file with the following columns:\n'
            "\n"
            "| Column | Details |\n"
            "| ------ | ------- |\n"
            '| Date | the day of the match (string; format "YYYY-MM-DD") |\n'
            '| Season | the season the match took place in (string; format "YYYY/YYYY") |\n'
            "| HomeTeam | the home team name (string) |\n"
            "| AwayTeam | the away team name (string) |\n"
            '| Score | the final score (string; format "X-Z") |\n'
            '| hGoal | number of goals scored by the home team (integer; "X" from the "Score" column) |\n'
            '| aGoal | number of goals scored by the away team (integer; "Z" from the "Score" column) |\n'
            "| Division | name of the division the match was played in (string) |\n"
            '| Tier | numerical representation of the tier which the match was from: 1, 2, 3 or 4, where "1" is the top tier (currently the Premier League) (integer) |\n'
            '| Result | the result "H" (home win), "A" (away win), "D" (draw) (string) |\n'
            "\n"
            "\n"
            "Such a long database of results leads to some confusion around team names, the answer to the most common set of questions I have received in terms of team names:\n"
            "\n"
            "* [Accrington F.C.](https://en.wikipedia.org/wiki/Accrington_F.C.) is a different team to [Accrington Stanley](https://en.wikipedia.org/wiki/Accrington_Stanley_F.C.). Acrrington F.C. were one of the founder members of the Football League, but were dissolved in 1896.\n"
            "* [Aldershot](https://en.wikipedia.org/wiki/Aldershot_F.C.) and [Aldershot Town](https://en.wikipedia.org/wiki/Aldershot_Town_F.C.) are listed as separate teams (Aldershot Town was formed in the spring of 1992 after the closure of Aldershot).\n"
            '* Throughout the database we refer to [Arsenal](https://en.wikipedia.org/wiki/Arsenal_F.C.) not "Woolwich Arsenal" (from 1893-1914) nor "The Arsenal" (from April 1914 - November 1919).\n'
            "* [Brighton & Hove Albion](https://en.wikipedia.org/wiki/Brighton_%26_Hove_Albion_F.C.), [New Brighton Tower](https://en.wikipedia.org/wiki/New_Brighton_Tower_F.C.) and [New Brighton](https://en.wikipedia.org/wiki/New_Brighton_A.F.C.) are all different clubs. New Brighton Tower were in existence from 1896-1901 and whilst Brighton & Hove Albion were formed in 1901, the \"spiritual\" successor to New Brighton Tower, was New Brighton (1921-1983 and 1993-2012; originally formed by the relocation of [South Liverpool](https://en.wikipedia.org/wiki/South_Liverpool_F.C._(1890s)))\n"
            "* Burton [Swifts](https://en.wikipedia.org/wiki/Burton_Swifts_F.C.), [Wanderers](https://en.wikipedia.org/wiki/Burton_Wanderers_F.C.), [United](https://en.wikipedia.org/wiki/Burton_United_F.C.), [Town](https://en.wikipedia.org/wiki/Burton_Town_F.C.) and [Albion](https://en.wikipedia.org/wiki/Burton_Albion_F.C.) are all different teams. Burton Swifts joined with Wanderers to form Burton United in 1901, which in 1924 merged with Burton Town and in 1950 merged with the newly formed Burton Albion.\n"
            "* The Gateshead in the database refers to [Gateshead A.F.C](https://en.wikipedia.org/wiki/Gateshead_A.F.C.) not [Gateshead F.C.](https://en.wikipedia.org/wiki/Gateshead_F.C.).\n"
            "* Whilst [Leeds Unitd](https://en.wikipedia.org/wiki/Leeds_United_F.C.) were formed following/replacing [Leeds City](https://en.wikipedia.org/wiki/Leeds_City_F.C.) (and played in the same ground). No players or management from Leeds City moved to Leeds United so we treat them as separate football clubs.\n"
            "* [Middlesbrough Ironopolis](https://en.wikipedia.org/wiki/Middlesbrough_Ironopolis_F.C.) (1889-1894) is separate team from [Middlesbrough](https://en.wikipedia.org/wiki/Middlesbrough_F.C.) (1876-).\n"
            "* [Rotherham County](https://en.wikipedia.org/wiki/Rotherham_County_F.C.) merged with [Rotherham Town](https://en.wikipedia.org/wiki/Rotherham_Town_F.C._(1899)) in 1925 to form [Rotherham United](https://en.wikipedia.org/wiki/Rotherham_United_F.C.).\n"
            '* Throughout the database we refer to [Stevenage](https://en.wikipedia.org/wiki/Stevenage_F.C.) not Stevenage Borough ("Borough" was dropped in June 2010).\n'
            "* [Wigan Athletic](https://en.wikipedia.org/wiki/Wigan_Athletic_F.C.) were formed (1932) a year after [Wigan Borough](https://en.wikipedia.org/wiki/Wigan_Borough_F.C.) were wound up (1931) and we treat them separately. Wigan Athletic was the sixth attempt to create a stable football club in Wigan following the dissolving of Wigan A.F.C., [County](https://en.wikipedia.org/wiki/Wigan_County_F.C.) (1897-1900), [United](https://en.wikipedia.org/wiki/Wigan_United_A.F.C.) (1896-1914), [Town](https://en.wikipedia.org/wiki/Wigan_Town_A.F.C.) (1905-1908) and [Borough](https://en.wikipedia.org/wiki/Wigan_Borough_F.C.) (1920-1931).\n"
            "\n"
            "The 1888-2016 data is based on that from the [Rec.Sport.Soccer Statistics Foundation](https://www.rsssf.org/) and James P. Curley ([2016](http://dx.doi.org/10.5281/zenodo.13158)).\n"
            "\n"
            "A number of tools making use of the data, such as a [league table generator](https://seanelvidge.com/leaguetable) and [head-to-head statistics](https://seanelvidge.com/h2h) are available at [seanelvidge.com/tools](https://seanelvidge.com/tools/)\n"
            "\n"
            "\n"
            "# England League Results with team strength rankings (EnglandLeagueResults_wRank.csv)\n"
            "This file contains the same data as `EnglandLeagueResults.csv` but with a measure of the teams strength via a ranking scheme.\n"
            "\n"
            'The database is a comma (",") delimited csv file with the following columns:\n'
            "\n"
            "| Column | Details |\n"
            "| ------ | ------- |\n"
            '| Date | the day of the match (string; format "YYYY-MM-DD") |\n'
            '| Season | the season the match took place in (string; format "YYYY/YYYY") |\n'
            "| HomeTeam | the home team name (string) |\n"
            "| AwayTeam | the away team name (string) |\n"
            '| Score | the final score (string; format "X-Z") |\n'
            '| hGoal | number of goals scored by the home team (integer; "X" from the "Score" column) |\n'
            '| aGoal | number of goals scored by the away team (integer; "Z" from the "Score" column) |\n'
            "| Division | name of the division the match was played in (string) |\n"
            '| Tier | numerical representation of the tier which the match was from: 1, 2, 3 or 4, where "1" is the top tier (currently the Premier League) (integer) |\n'
            '| Result | the result "H" (home win), "A" (away win), "D" (draw) (string) |\n'
            "| HomeRank_before | the ranking of the home team before the fixture was played (integer) |\n"
            "| AwayRank_before | the ranking of the away team before the fixture was played (integer) |\n"
            "| HomeRank_after | the ranking of the home team after the fixture was played (integer) |\n"
            "| AwayRank_after | the ranking of the away team after the fixture was played (integer) |\n"
        )
    ]

    with open(os.path.join(root_dir, "README.md"), "w") as handle:
        for line in readme:
            handle.writelines(line)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update England football results and rankings.")
    parser.add_argument("--root-dir", default=os.environ.get("FOOTBALL_RESULTS_ROOT_DIR", "."))
    parser.add_argument("--db-file", default="EnglandLeagueResults.csv")
    parser.add_argument("--ranked-file", default="EnglandLeagueResults_wRanks.csv")
    parser.add_argument("--rankings-pickle", default=".github/rankings.p")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    today = dt.date.today()
    season = today.year if today.month >= 8 else today.year - 1

    add_current_season(args.root_dir, args.db_file, season)
    update_rankings(args.root_dir, args.db_file, args.ranked_file, args.rankings_pickle)
