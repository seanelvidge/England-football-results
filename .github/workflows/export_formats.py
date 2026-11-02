"""Build and verify SQLite and Parquet copies of the seven public CSV datasets."""
import argparse
from contextlib import closing, contextmanager
import csv
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

import pyarrow as pa
import pyarrow.csv as arrow_csv
import pyarrow.parquet as parquet


DATASETS = (
    "EnglandLeagueNames", "EnglandLeagueResults", "EnglandLeagueResults_wRanks",
    "EnglishTeamActivePeriods", "EnglishTeamLogos", "EnglishTeamNamePeriods",
    "EnglishTeamPointDeductions",
)
SQLITE_FILE = "sqlite/EnglandFootball.sqlite"
EXPORT_FILES = [SQLITE_FILE, *[f"parquet/{name}.parquet" for name in DATASETS]]
INTEGER_COLUMNS = {
    "Tier", "hGoal", "aGoal", "Pts_deducted", "HomeRank_before",
    "AwayRank_before", "HomeRank_after", "AwayRank_after",
}
REAL_COLUMNS = {"HomeWinProbability", "DrawProbability", "AwayWinProbability"}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def csv_sources(overrides=None):
    sources = {name: f"{name}.csv" for name in DATASETS}
    sources.update(overrides or {})
    for path in sources.values():
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("CSV paths must be relative to the repository root")
    return sources


def load_tables(root, overrides=None):
    tables = {}
    for name, filename in csv_sources(overrides).items():
        path = Path(root) / filename
        with path.open(encoding="utf-8-sig", newline="") as handle:
            columns = next(csv.reader(handle))
        if not columns or any(not column for column in columns) or len(columns) != len(set(columns)):
            raise ValueError(f"Invalid CSV header: {filename}")
        types = {column: pa.int64() if column in INTEGER_COLUMNS else
                 pa.float64() if column in REAL_COLUMNS else pa.string() for column in columns}
        # Explicit types keep dates/seasons as text and prevent names such as
        # "NA" being mistaken for null. Only empty CSV fields become null.
        table = arrow_csv.read_csv(path, parse_options=arrow_csv.ParseOptions(newlines_in_values=True), convert_options=arrow_csv.ConvertOptions(
            column_types=types, null_values=[""], strings_can_be_null=True,
        ))
        tables[name] = table.replace_schema_metadata({
            b"source_csv": filename.encode(), b"source_sha256": sha256(path).encode(),
            b"export_version": b"1",
        })
    results = tables["EnglandLeagueResults"]
    ranked = tables["EnglandLeagueResults_wRanks"]
    if not set(results.column_names).issubset(ranked.column_names) or not ranked.select(results.column_names).equals(results):
        raise ValueError("Ranked results do not match EnglandLeagueResults.csv; update rankings before exporting")
    return tables


def quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


def sqlite_type(field):
    if pa.types.is_integer(field.type):
        return "INTEGER"
    if pa.types.is_floating(field.type):
        return "REAL"
    return "TEXT"


def row_batches(table):
    for batch in table.to_batches(max_chunksize=8192):
        yield list(zip(*(column.to_pylist() for column in batch.columns)))


def write_sqlite(path, tables):
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("PRAGMA user_version = 1")
        connection.execute('CREATE TABLE "_csv_sources" (table_name TEXT PRIMARY KEY, csv_file TEXT NOT NULL, row_count INTEGER NOT NULL, sha256 TEXT NOT NULL)')
        for name, table in tables.items():
            columns = ", ".join(f"{quote_identifier(field.name)} {sqlite_type(field)}" for field in table.schema)
            connection.execute(f"CREATE TABLE {quote_identifier(name)} ({columns})")
            insert = f"INSERT INTO {quote_identifier(name)} VALUES ({', '.join('?' for _ in table.schema)})"
            for rows in row_batches(table):
                connection.executemany(insert, rows)
            if name in {"EnglandLeagueResults", "EnglandLeagueResults_wRanks"}:
                connection.execute(f'CREATE INDEX {quote_identifier(name + "_season_tier_date")} ON {quote_identifier(name)} ("Season", "Tier", "Date")')
                connection.execute(f'CREATE INDEX {quote_identifier(name + "_date")} ON {quote_identifier(name)} ("Date")')
            metadata = table.schema.metadata
            connection.execute('INSERT INTO "_csv_sources" VALUES (?, ?, ?, ?)', (
                name, metadata[b"source_csv"].decode(), table.num_rows, metadata[b"source_sha256"].decode(),
            ))


def verify_exports(root, tables=None, overrides=None):
    """Check every row, column, type and CSV fingerprint in both formats."""
    root = Path(root)
    tables = tables if tables is not None else load_tables(root, overrides)
    uri = (root / SQLITE_FILE).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("SQLite integrity check failed")
        actual_tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if actual_tables != set(tables) | {"_csv_sources"}:
            raise ValueError("SQLite table list differs from the CSV datasets")
        for name, table in tables.items():
            info = connection.execute(f"PRAGMA table_info({quote_identifier(name)})").fetchall()
            if [(row[1], row[2]) for row in info] != [(field.name, sqlite_type(field)) for field in table.schema]:
                raise ValueError(f"SQLite schema differs from {name}.csv")
            metadata = table.schema.metadata
            recorded = connection.execute('SELECT csv_file, row_count, sha256 FROM "_csv_sources" WHERE table_name = ?', (name,)).fetchone()
            expected = (metadata[b"source_csv"].decode(), table.num_rows, metadata[b"source_sha256"].decode())
            if recorded != expected:
                raise ValueError(f"SQLite source fingerprint differs from {name}.csv")
            cursor = connection.execute(f"SELECT * FROM {quote_identifier(name)} ORDER BY rowid")
            for rows in row_batches(table):
                if cursor.fetchmany(len(rows)) != rows:
                    raise ValueError(f"SQLite values differ from {name}.csv")
            if cursor.fetchone() is not None:
                raise ValueError(f"SQLite has extra rows for {name}.csv")
            restored = parquet.read_table(root / f"parquet/{name}.parquet")
            if not restored.equals(table, check_metadata=True):
                raise ValueError(f"Parquet values, schema or source fingerprint differ from {name}.csv")


def publish_files(stage, root, files):
    # The workflow commits CSVs and publishes a release after this step succeeds.
    # Each file replacement is atomic; all conversion/validation happens first.
    for name in files:
        destination = Path(root) / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(Path(stage) / name, destination)


def export_formats(root, overrides=None):
    root = Path(root)
    tables = load_tables(root, overrides)
    (root / ".github").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".exports-", dir=root / ".github") as temporary:
        stage = Path(temporary)
        (stage / "sqlite").mkdir()
        (stage / "parquet").mkdir()
        write_sqlite(stage / SQLITE_FILE, tables)
        for name, table in tables.items():
            parquet.write_table(table, stage / f"parquet/{name}.parquet", version="2.6",
                                compression="zstd", compression_level=3, row_group_size=65536)
        verify_exports(stage, tables)
        publish_files(stage, root, EXPORT_FILES)
    print(f"Exported and verified {len(tables)} CSV datasets as SQLite and Parquet.")


@contextmanager
def staged_update(root, artifacts, overrides=None):
    """Publish updated CSVs, rankings and exports only after a successful build."""
    root = Path(root)
    sources = csv_sources(overrides)
    for name in artifacts:
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Artifact paths must be relative to the repository root")
    (root / ".github").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".update-", dir=root / ".github") as temporary:
        stage = Path(temporary)
        # Copy all reference CSVs as well as the mutable artifacts. The legacy
        # importer also needs its optional spreadsheet fallback in the stage.
        inputs = dict.fromkeys([*sources.values(), *artifacts, ".github/tmp_results.xlsx"])
        for name in inputs:
            if name not in EXPORT_FILES and (root / name).exists():
                (stage / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / name, stage / name)
        yield stage
        export_formats(stage, overrides)
        publish_files(stage, root, artifacts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root-dir", default=".")
    parser.add_argument("--check", action="store_true", help="Verify existing exports against every CSV without writing files.")
    args = parser.parse_args()
    if args.check:
        verify_exports(args.root_dir)
        print("SQLite and Parquet match all seven CSV datasets.")
    else:
        export_formats(args.root_dir)


if __name__ == "__main__":
    main()
