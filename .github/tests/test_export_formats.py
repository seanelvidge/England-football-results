"""Cross-format equivalence, corruption detection and update failure isolation."""
from contextlib import closing, redirect_stdout
import csv
import hashlib
import io
from itertools import islice
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".github/workflows"))
import export_formats as exports
import football_results as model


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for name in exports.DATASETS:
            with (ROOT / f"{name}.csv").open(encoding="utf-8-sig", newline="") as source:
                reader = csv.reader(source)
                rows = list(islice(reader, 4))
            with (self.root / f"{name}.csv").open("w", newline="", encoding="utf-8") as target:
                csv.writer(target).writerows(rows)
        self.quiet = redirect_stdout(io.StringIO())
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)

    def contents(self):
        return {str(path.relative_to(self.root)): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()}

    def edit(self, name, transform):
        path = self.root / f"{name}.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            columns, rows = reader.fieldnames, list(reader)
        transform(rows)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)

    def test_all_datasets_preserve_types_nulls_unicode_and_notes(self):
        note = 'Comma, quoted "name"; café\nsecond line'
        self.edit("EnglishTeamNamePeriods", lambda rows: rows[0].update(
            Team="Café United", StartDate="", EndDate="", Notes=note))
        self.edit("EnglishTeamPointDeductions", lambda rows: rows[0].update(Pts_deducted="-2"))
        self.edit("EnglishTeamActivePeriods", lambda rows: rows[0].update(ShortName="NA"))
        exports.export_formats(self.root)
        exports.verify_exports(self.root)
        with closing(sqlite3.connect(self.root / exports.SQLITE_FILE)) as connection:
            record = connection.execute('SELECT Team, StartDate, EndDate, Notes FROM EnglishTeamNamePeriods ORDER BY rowid LIMIT 1').fetchone()
            self.assertEqual(record, ("Café United", None, None, note))
            self.assertEqual(connection.execute('SELECT Pts_deducted, typeof(Pts_deducted) FROM EnglishTeamPointDeductions ORDER BY rowid LIMIT 1').fetchone(), (-2, "integer"))
            self.assertEqual(connection.execute('SELECT ShortName FROM EnglishTeamActivePeriods ORDER BY rowid LIMIT 1').fetchone(), ("NA",))
            self.assertEqual(connection.execute('SELECT typeof(Date), typeof(hGoal), typeof(HomeWinProbability) FROM EnglandLeagueResults_wRanks LIMIT 1').fetchone(), ("text", "integer", "real"))
        for name in exports.DATASETS:
            table = pq.read_table(self.root / f"parquet/{name}.parquet")
            self.assertEqual(table.num_rows, 3)
            self.assertNotIn("__index_level_0__", table.column_names)
            self.assertEqual(table.schema.metadata[b"source_sha256"].decode(), hashlib.sha256((self.root / f"{name}.csv").read_bytes()).hexdigest())
        names = pq.read_table(self.root / "parquet/EnglishTeamNamePeriods.parquet")
        self.assertEqual(names["Notes"][0].as_py(), note)
        self.assertIsNone(names["StartDate"][0].as_py())
        self.assertEqual(names.schema.field("StartDate").type, pa.string())

    def test_repeated_exports_are_byte_identical(self):
        exports.export_formats(self.root)
        before = self.contents()
        exports.export_formats(self.root)
        self.assertEqual(before, self.contents())

    def test_reference_only_edit_refreshes_sqlite_and_affected_parquet(self):
        exports.export_formats(self.root)
        old = {name: (self.root / name).read_bytes() for name in exports.EXPORT_FILES}
        self.edit("EnglishTeamLogos", lambda rows: rows[0].update(LogoURL="https://example.com/new.svg"))
        exports.export_formats(self.root)
        exports.verify_exports(self.root)
        changed = {name for name in old if old[name] != (self.root / name).read_bytes()}
        self.assertEqual(changed, {exports.SQLITE_FILE, "parquet/EnglishTeamLogos.parquet"})

    def test_deleted_rows_and_empty_reference_table_are_exported(self):
        exports.export_formats(self.root)
        self.edit("EnglishTeamLogos", lambda rows: rows.pop())
        self.edit("EnglishTeamNamePeriods", lambda rows: rows.clear())
        exports.export_formats(self.root)
        exports.verify_exports(self.root)
        self.assertEqual(pq.read_table(self.root / "parquet/EnglishTeamLogos.parquet").num_rows, 2)
        self.assertEqual(pq.read_table(self.root / "parquet/EnglishTeamNamePeriods.parquet").num_rows, 0)

    def test_failed_parquet_write_preserves_existing_exports(self):
        exports.export_formats(self.root)
        before = self.contents()
        with patch.object(exports.parquet, "write_table", side_effect=OSError("Disk full")), self.assertRaisesRegex(OSError, "Disk full"):
            exports.export_formats(self.root)
        self.assertEqual(before, self.contents())

    def test_missing_csv_and_invalid_numeric_value_preserve_exports(self):
        exports.export_formats(self.root)
        missing = self.root / "EnglishTeamLogos.csv"
        missing.unlink()
        before = self.contents()
        with self.assertRaises(FileNotFoundError):
            exports.export_formats(self.root)
        self.assertEqual(before, self.contents())
        self.edit("EnglandLeagueResults", lambda rows: rows[0].update(hGoal="bad"))
        before = self.contents()
        with self.assertRaises(pa.ArrowInvalid):
            exports.export_formats(self.root)
        self.assertEqual(before, self.contents())

    def test_stale_rankings_are_rejected_before_any_exports_are_replaced(self):
        exports.export_formats(self.root)
        self.edit("EnglandLeagueResults_wRanks", lambda rows: rows[0].update(Score="9-9"))
        before = self.contents()
        with self.assertRaisesRegex(ValueError, "Ranked results do not match"):
            exports.export_formats(self.root)
        self.assertEqual(before, self.contents())

    def test_check_detects_sqlite_data_corruption_even_with_matching_source_hash(self):
        exports.export_formats(self.root)
        with closing(sqlite3.connect(self.root / exports.SQLITE_FILE)) as connection, connection:
            connection.execute("UPDATE EnglandLeagueResults SET Score = '9-9' WHERE rowid = 1")
        with self.assertRaisesRegex(ValueError, "SQLite values differ"):
            exports.verify_exports(self.root)

    def test_check_detects_parquet_data_corruption(self):
        exports.export_formats(self.root)
        path = self.root / "parquet/EnglishTeamPointDeductions.parquet"
        table = pq.read_table(path)
        index = table.schema.get_field_index("Pts_deducted")
        table = table.set_column(index, table.schema.field(index), pa.array([99, 99, 99], type=pa.int64()))
        pq.write_table(table, path)
        with self.assertRaisesRegex(ValueError, "Parquet values"):
            exports.verify_exports(self.root)

    def test_missing_export_fails_check_without_creating_a_replacement(self):
        exports.export_formats(self.root)
        (self.root / exports.SQLITE_FILE).unlink()
        before = self.contents()
        with self.assertRaises(sqlite3.OperationalError):
            exports.verify_exports(self.root)
        self.assertEqual(before, self.contents())

    def test_rankings_only_command_updates_all_formats(self):
        original_csv = (self.root / "EnglandLeagueResults.csv").read_bytes()
        with patch.object(sys, "argv", ["football_results.py", "--root-dir", str(self.root), "--rankings-only"]):
            model.main()
        exports.verify_exports(self.root)
        self.assertEqual((self.root / "EnglandLeagueResults.csv").read_bytes(), original_csv)
        self.assertTrue((self.root / ".github/football_model.json").is_file())

    def test_legacy_results_command_adds_matches_in_all_formats(self):
        rows = pd.read_csv(self.root / "EnglandLeagueResults.csv")
        new_match = rows.iloc[:1].copy()
        new_match.loc[:, ["Date", "Season", "Division"]] = ["2026-10-31", "2026/2027", "Premier League"]
        updated = pd.concat([rows, new_match], ignore_index=True)
        updated = updated.set_index(pd.to_datetime(updated.pop("Date")))
        with patch.object(sys, "argv", ["football_results.py", "--root-dir", str(self.root)]), patch.object(model, "append_latest_matches", return_value=(updated, 1, set())):
            model.main()
        exports.verify_exports(self.root)
        with closing(sqlite3.connect(self.root / exports.SQLITE_FILE)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM EnglandLeagueResults").fetchone(), (4,))
        self.assertEqual(pq.read_table(self.root / "parquet/EnglandLeagueResults_wRanks.parquet").num_rows, 4)

    def test_custom_relative_csv_paths_are_supported(self):
        (self.root / "custom").mkdir()
        overrides = {"EnglandLeagueResults": "custom/results.csv", "EnglandLeagueResults_wRanks": "custom/ranked.csv"}
        for name, destination in overrides.items():
            (self.root / f"{name}.csv").rename(self.root / destination)
        with patch.object(sys, "argv", ["football_results.py", "--root-dir", str(self.root), "--rankings-only",
                                        "--db-file", "custom/results.csv", "--ranked-file", "custom/ranked.csv",
                                        "--rankings-state", "custom/state.csv"]):
            model.main()
        exports.verify_exports(self.root, overrides=overrides)
        self.assertTrue((self.root / "custom/state.csv.meta.json").is_file())


if __name__ == "__main__":
    unittest.main()
