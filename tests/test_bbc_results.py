"""Source parsing, cross-check failures, and transactional BBC updates."""
import contextlib
from copy import deepcopy
from datetime import date
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".github/workflows"))
import bbc_results as updater


DAY = date(2026, 10, 31)
LIVE_HTML = (ROOT / "tests/fixtures/bbc_scores_2026-10-31.html").read_text()
payload, _ = json.JSONDecoder().raw_decode(LIVE_HTML.split("window.__INITIAL_DATA__=", 1)[1])
LIVE_STATE = json.loads(payload)


def scores_data(state):
    return next(iter(state["data"].values()))["data"]


def html_page(state, double_encoded=True):
    value = json.dumps(state)
    return "<script>window.__INITIAL_DATA__=" + (json.dumps(value) if double_encoded else value) + ";</script>"


def first_event(state):
    return scores_data(state)["eventGroups"][0]["secondaryGroups"][0]["events"][0]


def stored_results():
    return pd.DataFrame([updater.result_row(date(2026, 10, 24), 2026, 1, "Arsenal", "Everton", 1, 0)])


class BBCParserTests(unittest.TestCase):
    def test_live_snapshot_selects_four_leagues_and_only_full_time(self):
        result = updater.parse_bbc_results(LIVE_HTML, DAY)
        self.assertEqual(result.columns.tolist(), updater.COLUMNS)
        self.assertEqual(result.Tier.tolist(), [1, 2, 3, 4])
        self.assertEqual(result.HomeTeam.tolist(), ["Chelsea", "Lincoln City", "Bradford City", "Grimsby Town"])
        self.assertEqual(result.Score.tolist(), ["2-0", "1-3", "0-3", "5-2"])
        self.assertEqual(result.Result.tolist(), ["H", "A", "A", "H"])
        self.assertEqual(set(result.Date), {"2026-10-31"})
        self.assertEqual(set(result.Season), {"2026/2027"})

    def test_json_object_and_encoded_string_are_both_read_without_execution(self):
        expected = updater.parse_bbc_results(LIVE_HTML, DAY)
        actual = updater.parse_bbc_results(html_page(LIVE_STATE, double_encoded=False), DAY)
        pd.testing.assert_frame_equal(actual, expected)

    def test_zero_zero_and_bbc_aliases(self):
        state = deepcopy(LIVE_STATE)
        event = first_event(state)
        event["home"].update(fullName="MK Dons", score="0")
        event["away"].update(fullName="Bournemouth", score="0")
        result = updater.parse_bbc_results(html_page(state), DAY).iloc[0]
        self.assertEqual((result.HomeTeam, result.AwayTeam), ("Milton Keynes Dons", "AFC Bournemouth"))
        self.assertEqual((result.hGoal, result.aGoal, result.Score, result.Result), (0, 0, "0-0", "D"))

    def test_postponed_abandoned_and_unfinished_matches_are_not_imported(self):
        for status, period, comment in [
            ("PreEvent", "", ""), ("MidEvent", "90'+4", "90'+4"),
            ("PostEvent", "Abandoned", "Abandoned"),
            ("PostEvent", "FT", "Postponed"),
        ]:
            with self.subTest(status=status, period=period, comment=comment):
                state = deepcopy(LIVE_STATE)
                event = first_event(state)
                event["status"] = status
                event["periodLabel"]["value"] = period
                event["statusComment"]["value"] = comment
                result = updater.parse_bbc_results(html_page(state), DAY)
                self.assertNotIn("Chelsea", result.HomeTeam.tolist())

    def test_playoffs_under_a_league_heading_are_excluded(self):
        state = deepcopy(LIVE_STATE)
        for group in scores_data(state)["eventGroups"]:
            if group["displayLabel"] == "Championship":
                group["secondaryGroups"][0]["displayLabel"] = "Promotion Play-offs - Final"
        self.assertNotIn(2, updater.parse_bbc_results(html_page(state), DAY).Tier.tolist())

    def test_valid_day_without_matches_or_without_target_leagues_is_empty(self):
        for groups in [[], [g for g in scores_data(LIVE_STATE)["eventGroups"] if g["displayLabel"] not in updater.LEAGUES]]:
            state = deepcopy(LIVE_STATE)
            scores_data(state)["eventGroups"] = groups
            self.assertTrue(updater.parse_bbc_results(html_page(state), DAY).empty)

    def test_wrong_page_date_and_wrong_event_date_are_rejected(self):
        state = deepcopy(LIVE_STATE)
        first_event(state)["date"]["isoDate"] = "2026-10-30"
        for html, day in [(LIVE_HTML, date(2026, 10, 30)), (html_page(state), DAY)]:
            with self.subTest(day=day), self.assertRaisesRegex(ValueError, "date"):
                updater.parse_bbc_results(html, day)

    def test_missing_and_broken_data_fail_instead_of_claiming_no_matches(self):
        state = deepcopy(LIVE_STATE)
        del scores_data(state)["eventGroups"]
        for html in ["<html>Service unavailable</html>", "window.__INITIAL_DATA__=invalid", html_page({"data": {}}), html_page(state)]:
            with self.subTest(html=html[:50]), self.assertRaisesRegex(ValueError, "Cannot parse BBC"):
                updater.parse_bbc_results(html, DAY)

    def test_invalid_full_time_score_or_missing_team_fails(self):
        for field, value in [("score", None), ("score", "-1"), ("score", "1.5"), ("fullName", "")]:
            state = deepcopy(LIVE_STATE)
            first_event(state)["home"][field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "Cannot parse BBC"):
                updater.parse_bbc_results(html_page(state), DAY)

    def test_late_july_season_start_and_2020_restart(self):
        for day, expected in [(date(2022, 7, 30), "2022/2023"), (date(2020, 7, 26), "2019/2020"), (date(2026, 1, 1), "2025/2026")]:
            state = deepcopy(LIVE_STATE)
            data = scores_data(state)
            data["selectedStartDate"] = data["selectedEndDate"] = day.isoformat()
            for group in data["eventGroups"]:
                for secondary in group["secondaryGroups"]:
                    for event in secondary["events"]:
                        event["date"]["isoDate"] = day.isoformat()
            with self.subTest(day=day):
                self.assertEqual(set(updater.parse_bbc_results(html_page(state), day).Season), {expected})


class FootballDataCheckTests(unittest.TestCase):
    HEADER = "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"

    def test_csv_aliases_and_unplayed_rows(self):
        text = self.HEADER + "24/10/2026,MK Dons,York,0,0,D\n31/10/2026,York,MK Dons,,,\n"
        parsed = updater.parse_football_data(text, 2026, 3)
        self.assertEqual(len(parsed), 1)
        row = parsed.iloc[0]
        self.assertEqual((row.HomeTeam, row.AwayTeam, row.Division), ("Milton Keynes Dons", "York City", "EFL League One"))
        self.assertEqual((row.Score, row.Result), ("0-0", "D"))

    def test_bad_csv_partial_scores_and_wrong_result_fail(self):
        for text in ["<html>Down</html>", self.HEADER + "24/10/2026,A,B,1,,H\n", self.HEADER + "24/10/2026,A,B,1,0,A\n"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                updater.parse_football_data(text, 2026, 1)

    def test_lagging_feed_is_allowed_but_missing_database_match_is_not(self):
        existing = stored_results()
        newer = updater.parse_bbc_results(LIVE_HTML, DAY)
        database = pd.concat([existing, newer], ignore_index=True)
        result, count = updater.reconcile_results(database, existing, "football-data", allow_new=False)
        pd.testing.assert_frame_equal(result, database)
        self.assertEqual(count, 0)
        with self.assertRaisesRegex(ValueError, "Chelsea v Manchester United: missing from database"):
            updater.reconcile_results(existing, newer, "football-data", allow_new=False)

    def test_each_stored_result_field_is_compared_and_error_names_fixture(self):
        existing = stored_results()
        for field, wrong in [("Date", "2026-10-23"), ("Score", "2-0"), ("hGoal", 2), ("aGoal", 1), ("Result", "D"), ("Tier", 2), ("Division", "EFL Championship")]:
            incoming = existing.copy()
            incoming.loc[0, field] = wrong
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, f"Arsenal v Everton:.*{field}: database="):
                updater.reconcile_results(existing, incoming, "football-data.co.uk", allow_new=False)

    def test_check_fetches_all_four_feeds_and_never_writes(self):
        def download(session, url):
            self.assertIn("/2627/E", url)
            return self.HEADER + ("24/10/2026,Arsenal,Everton,1,0,H\n" if url.endswith("E0.csv") else "")

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / updater.RESULTS_FILE
            stored_results().to_csv(path, index=False)
            original = path.read_bytes()
            with patch.object(updater, "download_text", side_effect=download) as get:
                updater.check_football_data(temp)
                self.assertEqual(get.call_count, 4)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(temp).iterdir()), [path])

    def test_download_failure_propagates_instead_of_using_spreadsheet_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            stored_results().to_csv(Path(temp) / updater.RESULTS_FILE, index=False)
            with patch.object(updater, "download_text", side_effect=requests.HTTPError("503")), self.assertRaises(requests.HTTPError):
                updater.check_football_data(temp)

    def test_http_errors_are_checked_before_reading_body(self):
        session = Mock()
        session.get.return_value.raise_for_status.side_effect = requests.HTTPError("404")
        with self.assertRaises(requests.HTTPError):
            updater.download_text(session, "https://example.com/results")


class BBCUpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        stored_results().to_csv(self.root / updater.RESULTS_FILE, index=False)
        self.output = io.StringIO()
        self.quiet = contextlib.redirect_stdout(self.output)
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)

    def contents(self):
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def update(self, html=LIVE_HTML, dry_run=False):
        with patch.object(updater, "download_text", return_value=html):
            return updater.update_bbc_results(self.root, DAY, DAY, dry_run=dry_run)

    def test_full_update_refreshes_rankings_and_is_byte_identical_on_repeat(self):
        result, added = self.update()
        self.assertEqual(added, 4)
        ranked = pd.read_csv(self.root / updater.RANKED_FILE)
        pd.testing.assert_frame_equal(ranked[updater.COLUMNS], result)
        manifest = json.loads((self.root / (updater.STATE_FILE + ".meta.json")).read_text())
        self.assertEqual(manifest["matches"], 5)
        self.assertEqual(manifest["results_sha256"], updater.model.file_sha256(self.root / updater.RESULTS_FILE))
        self.assertEqual(manifest["ranked_sha256"], updater.model.file_sha256(self.root / updater.RANKED_FILE))
        before = self.contents()
        _, added = self.update()
        self.assertEqual(added, 0)
        self.assertEqual(self.contents(), before)

    def test_dry_run_writes_nothing(self):
        before = self.contents()
        _, added = self.update(dry_run=True)
        self.assertEqual(added, 4)
        self.assertEqual(self.contents(), before)

    def test_bbc_score_correction_fails_without_touching_any_artifact(self):
        self.update()
        before = self.contents()
        state = deepcopy(LIVE_STATE)
        first_event(state)["home"]["score"] = "3"
        with self.assertRaisesRegex(ValueError, "BBC consistency check failed"):
            self.update(html_page(state))
        self.assertEqual(self.contents(), before)

    def test_ranking_failure_does_not_publish_partial_results(self):
        before = self.contents()
        with patch.object(updater.model, "update_rankings", side_effect=ValueError("Invalid database")), self.assertRaisesRegex(ValueError, "Invalid database"):
            self.update()
        self.assertEqual(self.contents(), before)
        self.assertFalse(list(self.root.glob(".bbc-results-*")))

    def test_later_download_failure_does_not_save_earlier_results(self):
        before = self.contents()
        with patch.object(updater, "download_text", side_effect=[LIVE_HTML, requests.HTTPError("503")]), self.assertRaises(requests.HTTPError):
            updater.update_bbc_results(self.root, DAY, date(2026, 11, 1))
        self.assertEqual(self.contents(), before)

    def test_repeated_feed_rows_and_aliases_are_idempotent(self):
        incoming = stored_results()
        incoming["HomeTeam"] = "MK Dons"
        existing = incoming.copy()
        existing["HomeTeam"] = "Milton Keynes Dons"
        result, count = updater.reconcile_results(existing, pd.concat([incoming, incoming]), "BBC", allow_new=True)
        self.assertEqual(count, 0)
        pd.testing.assert_frame_equal(result, existing)

    def test_conflicting_incoming_duplicates_fail(self):
        original = updater.parse_bbc_results(LIVE_HTML, DAY)
        changed = original.iloc[:1].copy()
        changed["Score"] = "3-0"
        with self.assertRaisesRegex(ValueError, "consistency check failed"):
            updater.reconcile_results(stored_results(), pd.concat([original, changed]), "BBC", allow_new=True)

    def test_date_overlap_and_long_outage_catchup(self):
        existing = stored_results()
        existing["Date"] = "2026-10-30"
        days = updater.bbc_date_range(existing, None, DAY)
        self.assertEqual((days[0], days[-1], len(days)), (date(2026, 10, 25), DAY, 7))
        existing["Date"] = "2026-10-01"
        days = updater.bbc_date_range(existing, None, DAY)
        self.assertEqual((days[0], days[-1], len(days)), (date(2026, 10, 1), DAY, 31))
        with self.assertRaisesRegex(ValueError, "Start date"):
            updater.bbc_date_range(existing, date(2026, 11, 1), DAY)

    def test_verification_failure_reaches_cli_exit(self):
        with patch.object(sys, "argv", ["bbc_results.py", "--root-dir", str(self.root), "--check-football-data"]), patch.object(updater, "download_text", return_value=FootballDataCheckTests.HEADER + "24/10/2026,Arsenal,Everton,3,0,H\n"):
            with self.assertRaisesRegex(ValueError, "football-data.co.uk consistency check failed"):
                updater.main()


if __name__ == "__main__":
    unittest.main()
