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

The database is updated and checked each night. Only the latest data release is retained.
