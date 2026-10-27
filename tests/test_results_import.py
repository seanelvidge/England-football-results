"""Import regressions for aliases and fixtures stored with Date as the index."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from test_rating_math import model


class ResultsImportTests(unittest.TestCase):
    def fixture(self, date="2026-08-15", home="York City", away="Bristol Rovers"):
        frame = pd.DataFrame([dict(
            Date=date, Season="2026/2027", HomeTeam=home, AwayTeam=away,
            Score="3-2", hGoal=3, aGoal=2, Division="EFL League Two", Tier=4,
            Result="H",
        )])
        return frame.set_index(pd.to_datetime(frame.pop("Date")))

    def download(self, url, **kwargs):
        rows = "Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        if url.endswith("E3.csv"):
            rows += "15/08/2026,York,Bristol Rvs,3,2,H\n"
            rows += "22/08/2026,Rotherham,York,1,1,D\n"
            # The same incoming fixture should not be added twice either.
            rows += "22/08/2026,Rotherham,York,1,1,D\n"
        return Mock(text=rows)

    def test_primary_normalizes_new_and_existing_fixtures_and_is_idempotent(self):
        for name in ["York", "York City"]:
            with self.subTest(stored_name=name), patch.object(model.requests, "get", side_effect=self.download):
                updated, count, failed = model.append_latest_matches(2026, self.fixture(home=name))
                self.assertEqual(count, 1)
                self.assertFalse(failed)
                self.assertEqual(len(updated), 2)
                self.assertEqual(updated.HomeTeam.tolist(), ["York City", "Rotherham United"])
                self.assertEqual(updated.AwayTeam.tolist(), ["Bristol Rovers", "York City"])
                repeated, count, _ = model.append_latest_matches(2026, updated)
                self.assertEqual(count, 0)
                pd.testing.assert_frame_equal(updated, repeated)

    def test_same_result_on_different_dates_is_preserved(self):
        fixtures = pd.concat([self.fixture(), self.fixture(date="2026-08-16")])
        empty = Mock(text="Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n")
        with patch.object(model.requests, "get", return_value=empty):
            updated, _, _ = model.append_latest_matches(2026, fixtures)
        pd.testing.assert_frame_equal(updated, fixtures)

    def test_fallback_compares_canonical_names_on_both_sides(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".github").mkdir()
            (Path(tmp) / ".github/tmp_results.xlsx").touch()
            for stored in ["York", "York City"]:
                for incoming in ["York", "York City"]:
                    row = {"Date": str((pd.Timestamp("2026-08-15") - model.EXCEL_EPOCH).days),
                           "Home Team": incoming, "Away Team": "Bristol Rvs", "Tier": "4", "Score": "3-2"}
                    with self.subTest(stored=stored, incoming=incoming), \
                         patch.object(model, "read_scores_sheet_rows", return_value=[row]), \
                         patch.object(model, "load_division_lookup", return_value=[]):
                        added = model.load_tmp_results_matches(tmp, self.fixture(home=stored))
                        self.assertTrue(added.empty)

    def test_final_write_collapses_aliases_but_retains_different_results(self):
        # Exercise the final write independently of deduplication in either feed.
        fixtures = pd.concat([self.fixture(), self.fixture(home="York"),
                              self.fixture(date="2026-08-16")])
        conflicting = self.fixture()
        conflicting.loc[:, ["Score", "hGoal"]] = ["4-2", 4]
        fixtures = pd.concat([fixtures, conflicting])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.csv"
            self.fixture().to_csv(path)
            with patch.object(model, "append_latest_matches", return_value=(fixtures, 1, set())):
                model.add_current_season(tmp, "results.csv", 2026)
            actual = pd.read_csv(path)
            self.assertEqual(len(actual), 3)
            self.assertEqual(set(actual.HomeTeam), {"York City"})
            self.assertEqual(actual.Score.tolist(), ["3-2", "4-2", "3-2"])
            # Conflicting scores must still be rejected by the ranking validator.
            with self.assertRaisesRegex(ValueError, "Duplicate fixtures"):
                model.update_rankings(tmp, "results.csv", "ranked.csv", "state.csv")


if __name__ == "__main__":
    unittest.main()
