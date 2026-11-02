# English Football League Data — SQLite

[`EnglandFootball.sqlite`](https://github.com/seanelvidge/England-football-results/releases/latest/download/EnglandFootball.sqlite) contains all seven CSV datasets in one SQLite database. It can be used directly without running a database server.

The CSV files in the [main repository](../README.md) are the source data. SQLite and Parquet are built and checked during the same nightly update, then published as release downloads. The database is not included in a Git clone.

## Download

Download the database from the [latest data release](https://github.com/seanelvidge/England-football-results/releases/latest) and save it in this folder. From the repository root:

```sh
curl --fail --location \
  https://github.com/seanelvidge/England-football-results/releases/latest/download/EnglandFootball.sqlite \
  --output sqlite/EnglandFootball.sqlite
```

The release's `data-manifest.json` records the exact CSV commit and SHA-256 checksums. When combining this database with CSV or Parquet data, use files from that same commit or release. To match an older checkout exactly, build the exports locally using the commands below.

## Tables

Table names match the CSV filenames without the `.csv` extension. Column names match the CSV headers exactly, including capitalisation and spaces.

| Table | Contents |
| --- | --- |
| `EnglandLeagueResults` | Match dates, teams, scores, divisions and results. |
| `EnglandLeagueResults_wRanks` | The same matches with team-strength ratings and pre-match probabilities. |
| `EnglandLeagueNames` | Division names, their active seasons and tiers. |
| `EnglishTeamPointDeductions` | Points deductions and additions, effective dates and notes. |
| `EnglishTeamLogos` | Club names, logo URLs and colours. |
| `EnglishTeamActivePeriods` | Club names, short names and periods of league participation. |
| `EnglishTeamNamePeriods` | Historic club names, start and end dates, and notes. |

Goals, tiers, rankings and points adjustments use SQLite `INTEGER`; probabilities use `REAL`. All other columns use `TEXT`, including dates (`YYYY-MM-DD`), seasons (`YYYY/YYYY`) and scores. Empty CSV fields become SQL `NULL`. Unicode names and notes are preserved.

Both match tables have indexes on `Date` and on `(Season, Tier, Date)`. No extra identifier column is added. Use `ORDER BY` when the order of your query results matters.

The additional `_csv_sources` table records each source filename, row count and SHA-256 checksum. It identifies the exact CSV files used to build this database.

## Examples

Run these examples from the repository root, after downloading or building the database.

### SQLite command line

Open the database with the [SQLite command-line tool](https://sqlite.org/cli.html):

```sh
sqlite3 -readonly sqlite/EnglandFootball.sqlite
```

List the tables and show ten recent Premier League results from 2025/2026:

```sql
.tables
.headers on
.mode column

SELECT Date, HomeTeam, AwayTeam, Score
FROM EnglandLeagueResults
WHERE Season = '2025/2026' AND Tier = 1
ORDER BY Date DESC, HomeTeam
LIMIT 10;
```

Join a club's results to its logo:

```sql
SELECT r.Date, r.HomeTeam, r.AwayTeam, r.Score, l.LogoURL
FROM EnglandLeagueResults AS r
LEFT JOIN EnglishTeamLogos AS l ON l.Team = r.HomeTeam
WHERE r.HomeTeam = 'Aston Villa' AND r.Season = '2025/2026'
ORDER BY r.Date;
```

Names containing spaces need double quotes. Blank end dates are queried with `IS NULL`:

```sql
SELECT Name, "Years Active", Tier FROM EnglandLeagueNames;
SELECT Team, Name FROM EnglishTeamNamePeriods WHERE EndDate IS NULL;
```

### Python

Python includes [sqlite3](https://docs.python.org/3/library/sqlite3.html), so this example needs no additional packages. Query parameters handle club names safely:

```python
from contextlib import closing
import sqlite3

with closing(sqlite3.connect(
    "file:sqlite/EnglandFootball.sqlite?mode=ro", uri=True
)) as connection:
    matches = connection.execute(
        """
        SELECT Date, HomeTeam, AwayTeam, Score, HomeWinProbability
        FROM EnglandLeagueResults_wRanks
        WHERE Season = ? AND (HomeTeam = ? OR AwayTeam = ?)
        ORDER BY Date
        """,
        ("2025/2026", "Aston Villa", "Aston Villa"),
    ).fetchall()

for match in matches[:10]:
    print(match)
```

## Updating and checking the files

The **Nightly BBC Football Results Update** generates SQLite and Parquet after updating the CSVs and rankings. Every exported row, column type and source checksum is checked before the CSV commit. The workflow uploads the exports to a draft release, downloads and checks them again, then publishes the complete release against that commit. A failed upload or check fails the action and leaves the draft unpublished; rerunning the workflow can retry it.

The overnight consistency workflow also downloads the latest published release and checks it against the current CSVs. Generated files and the rebuildable rankings cache are ignored by Git, so nightly binary versions do not accumulate in repository history.

To rebuild both export formats from the current CSVs without downloading results:

```sh
python -m pip install -r .github/workflows/requirements.txt
python .github/workflows/export_formats.py
```

To check the existing exports without changing them:

```sh
python .github/workflows/export_formats.py --check
```

If you have edited match results, first update the rankings and all formats together:

```sh
python .github/workflows/football_results.py --rankings-only
```

Edit the source CSVs when making corrections; rebuilding replaces the SQLite database. The older results importer also regenerates both exports when run normally. Optional `--db-file`, `--ranked-file` and `--rankings-state` paths are relative to `--root-dir`.

## Licence and attribution

The same [licence and source attribution](../LICENCE.md) apply as for the CSV datasets. See the main [README](../README.md#licence-and-attribution) for the suggested attribution and third-party source notes.
