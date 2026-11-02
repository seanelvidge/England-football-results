"""Persistence regressions: changed code and late results must trigger a replay."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from test_rating_math import model


class RankingRebuildTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.rows = pd.DataFrame([
            dict(Date="2020-01-01", Season="2019/2020", HomeTeam="A", AwayTeam="B", Score="1-0", hGoal=1, aGoal=0, Division="Test", Tier=1, Result="H"),
            dict(Date="2020-01-08", Season="2019/2020", HomeTeam="B", AwayTeam="A", Score="1-1", hGoal=1, aGoal=1, Division="Test", Tier=1, Result="D"),
            dict(Date="2020-01-15", Season="2019/2020", HomeTeam="A", AwayTeam="B", Score="0-2", hGoal=0, aGoal=2, Division="Test", Tier=1, Result="A"),
        ])

    def run_update(self, rows, force=False):
        rows.to_csv(self.root / "results.csv", index=False)
        with contextlib.redirect_stdout(io.StringIO()):
            model.update_rankings(str(self.root), "results.csv", "ranked.csv", "state.csv", rebuild=force)
        return (self.root / "ranked.csv").read_bytes(), (self.root / "state.csv").read_bytes()

    def test_incremental_is_identical_to_full_replay_and_noop(self):
        self.run_update(self.rows.iloc[:2])
        increment = self.run_update(self.rows)
        self.assertEqual(increment, self.run_update(self.rows, force=True))
        self.assertEqual(increment, self.run_update(self.rows))

    def test_late_added_result_replays_history(self):
        self.run_update(self.rows.iloc[[0, 2]])
        actual = self.run_update(self.rows.iloc[[0, 2, 1]])
        expected = self.run_update(self.rows, force=True)
        self.assertEqual(actual, expected)

    def test_correction_and_deletion_replay_history(self):
        self.run_update(self.rows)
        changed = self.rows.copy()
        changed.loc[0, ["Score", "hGoal", "aGoal", "Result"]] = ["0-1", 0, 1, "A"]
        self.assertEqual(self.run_update(changed), self.run_update(changed, force=True))
        reduced = changed.iloc[[0, 2]]
        self.assertEqual(self.run_update(reduced), self.run_update(reduced, force=True))

    def test_missing_corrupt_or_stale_state_rebuilds_without_new_matches(self):
        expected = self.run_update(self.rows)
        for corruption in ["missing", "hash", "model"]:
            if corruption == "missing":
                (self.root / "state.csv").unlink()
            elif corruption == "hash":
                (self.root / "ranked.csv").write_text((self.root / "ranked.csv").read_text().replace("1000", "9999"))
            else:
                path = self.root / "state.csv.meta.json"
                manifest = json.loads(path.read_text())
                manifest["source_sha256"] = "old-model"
                path.write_text(json.dumps(manifest))
            self.assertEqual(self.run_update(self.rows), expected)

    def test_duplicate_fixture_is_rejected_without_changing_artifacts(self):
        expected = self.run_update(self.rows)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.run_update(pd.concat([self.rows, self.rows.iloc[:1]]))
        self.assertEqual((self.root / "ranked.csv").read_bytes(), expected[0])

    def test_import_aliases_do_not_split_existing_clubs(self):
        rows = pd.DataFrame([dict(HomeTeam="Sheffield Wed", AwayTeam="York", Notes="York")])
        fixed = model.normalize_team_names(rows)
        self.assertEqual(fixed.iloc[0].HomeTeam, "Sheffield Wednesday")
        self.assertEqual(fixed.iloc[0].AwayTeam, "York City")
        self.assertEqual(fixed.iloc[0].Notes, "York")

    def test_multiple_fixtures_for_one_team_on_one_date_are_rejected(self):
        extra = self.rows.iloc[:1].copy()
        extra["AwayTeam"] = "C"
        with self.assertRaisesRegex(ValueError, "same date"):
            self.run_update(pd.concat([self.rows, extra]))

    def test_margin_only_correction_triggers_replay(self):
        before = self.run_update(self.rows)
        changed = self.rows.copy()
        changed.loc[0, ["Score", "hGoal"]] = ["4-0", 4]
        corrected = self.run_update(changed)
        self.assertNotEqual(before, corrected)
        self.assertEqual(corrected, self.run_update(changed, force=True))

    def test_goals_must_be_nonnegative_integers(self):
        for goals in [-1, .5, float('nan')]:
            changed = self.rows.copy()
            changed['hGoal'] = changed.hGoal.astype(float)
            changed.loc[0, 'hGoal'] = goals
            with self.assertRaisesRegex(ValueError, "nonnegative integers"):
                self.run_update(changed)


if __name__ == "__main__":
    unittest.main()
