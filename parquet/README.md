# English Football League Data — Parquet

This folder contains one Apache Parquet file for each of the seven CSV datasets. Parquet stores data by column, allowing tools to read selected columns and filter rows without loading the whole dataset into a dataframe.

The CSV files in the [main repository](../README.md) are the source data. The SQLite and Parquet copies are regenerated in the same update as the results and rankings, and committed together.

## Files

| File | Contents |
| --- | --- |
| [`EnglandLeagueResults.parquet`](EnglandLeagueResults.parquet) | Match dates, teams, scores, divisions and results. |
| [`EnglandLeagueResults_wRanks.parquet`](EnglandLeagueResults_wRanks.parquet) | The same matches with team-strength ratings and pre-match probabilities. |
| [`EnglandLeagueNames.parquet`](EnglandLeagueNames.parquet) | Division names, their active seasons and tiers. |
| [`EnglishTeamPointDeductions.parquet`](EnglishTeamPointDeductions.parquet) | Points deductions and additions, effective dates and notes. |
| [`EnglishTeamLogos.parquet`](EnglishTeamLogos.parquet) | Club names, logo URLs and colours. |
| [`EnglishTeamActivePeriods.parquet`](EnglishTeamActivePeriods.parquet) | Club names, short names and periods of league participation. |
| [`EnglishTeamNamePeriods.parquet`](EnglishTeamNamePeriods.parquet) | Historic club names, start and end dates, and notes. |

Column names and row order match the CSVs. Goals, tiers, rankings and points adjustments use 64-bit integers; probabilities use 64-bit floating-point numbers. Other columns are UTF-8 strings, including dates (`YYYY-MM-DD`), seasons (`YYYY/YYYY`) and scores. Empty CSV fields become null values. No dataframe index column is added.

Files use Parquet format version 2.6 and Zstandard compression. The file metadata includes `source_csv`, `source_sha256` and `export_version`, identifying the source CSV and exporter format.

## Examples

Run these examples from the repository root, after cloning or downloading the repository.

### Python and pandas

Install the packages:

```sh
python -m pip install 'numpy>=2.0' pandas pyarrow
```

Read selected columns and filter to one season and division:

```python
import pandas as pd

matches = pd.read_parquet(
    "parquet/EnglandLeagueResults_wRanks.parquet",
    engine="pyarrow",
    columns=["Date", "HomeTeam", "AwayTeam", "Score", "HomeWinProbability"],
    filters=[("Season", "==", "2025/2026"), ("Tier", "==", 1)],
)

print(matches.sort_values("Date", ascending=False).head(10))
```

Dates remain strings when loaded. Convert them if you need pandas date calculations:

```python
matches["Date"] = pd.to_datetime(matches["Date"])
```

### SQL with DuckDB

[DuckDB](https://duckdb.org/docs/stable/data/parquet/overview.html) can query Parquet files directly:

```sh
python -m pip install duckdb
```

```python
import duckdb

duckdb.sql("""
    SELECT Season, COUNT(*) AS Matches,
           SUM(hGoal + aGoal) AS Goals
    FROM read_parquet('parquet/EnglandLeagueResults.parquet')
    WHERE Tier = 1
    GROUP BY Season
    ORDER BY Season DESC
    LIMIT 10
""").show()
```

Each file has its own schema; select the file you need rather than combining all seven files as one table.

### Read in batches with PyArrow

For processing the full results file with a bounded batch size:

```python
import pyarrow.parquet as pq

source = pq.ParquetFile("parquet/EnglandLeagueResults.parquet")
total_goals = 0
for batch in source.iter_batches(batch_size=10000, columns=["hGoal", "aGoal"]):
    values = batch.to_pydict()
    total_goals += sum(values["hGoal"]) + sum(values["aGoal"])

print(total_goals)
```

## Updating and checking the files

The nightly **BBC Football Results Update** generates SQLite and Parquet after updating the CSVs and rankings. Every exported row, column type and source checksum is checked before the files are published. A conversion or validation error fails the workflow before its commit step.

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

Edit the source CSVs when making corrections; rebuilding replaces the Parquet files. The older results importer also regenerates both exports when run normally.

## Licence and attribution

The same [licence and source attribution](../LICENCE.md) apply as for the CSV datasets. See the main [README](../README.md#licence-and-attribution) for the suggested attribution and third-party source notes.
