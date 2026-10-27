# English Football League Data

## Contents

- [Overview](#overview)
- [Dataset index](#dataset-index)
- [Detailed schemas](#detailed-schemas)
- [Club naming conventions](#club-naming-conventions)
- [Sources and tools](#sources-and-tools)
- [Licence and attribution](#licence-and-attribution)
- [Contact](#contact)

## Overview

This is a plain text database of all England football (soccer) league results from 1888 to 2026/10/26 (covering 212,740 matches).

The database is updated roughly every two days for the top four tiers in English football: Premier League, EFL Championship, EFL League One and EFL League Two.

The six CSV files cover match results, team-strength ratings and probabilities, division names, points deductions and additions, club logos and colours, and periods of league participation.

## Dataset index

Each file link opens the CSV in this repository. The schema links jump to its documentation below.

| Dataset file | Contents | Detailed schema |
| --- | --- | --- |
| [`EnglandLeagueResults.csv`](EnglandLeagueResults.csv) | Match results from 1888 to 2026/10/26 (212,740 matches). | [View schema](#england-league-results) |
| [`EnglandLeagueResults_wRanks.csv`](EnglandLeagueResults_wRanks.csv) | Match results with chronological team-strength ratings and pre-match probabilities. | [View schema](#england-league-results-with-team-strength-rankings) |
| [`EnglandLeagueNames.csv`](EnglandLeagueNames.csv) | Division names, their active seasons and their tiers. | [View schema](#england-league-names) |
| [`EnglishTeamPointDeductions.csv`](EnglishTeamPointDeductions.csv) | Points deductions and additions, effective dates and reasons. | [View schema](#english-team-point-deductions) |
| [`EnglishTeamLogos.csv`](EnglishTeamLogos.csv) | Club logos/crests and primary and secondary club colours. | [View schema](#english-team-logos) |
| [`EnglishTeamActivePeriods.csv`](EnglishTeamActivePeriods.csv) | Club participation periods in the top four tiers, with short team names. | [View schema](#english-team-active-years) |

## Detailed schemas

### England League Results

**File:** [`EnglandLeagueResults.csv`](EnglandLeagueResults.csv)

A comma (",") delimited CSV file of English football league results, with the following columns:

| Column | Details |
| ------ | ------- |
| Date | the day of the match (string; format "YYYY-MM-DD") |
| Season | the season the match took place in (string; format "YYYY/YYYY") |
| HomeTeam | the home team name (string) |
| AwayTeam | the away team name (string) |
| Score | the final score (string; format "X-Z") |
| hGoal | number of goals scored by the home team (integer; "X" from the "Score" column) |
| aGoal | number of goals scored by the away team (integer; "Z" from the "Score" column) |
| Division | name of the division the match was played in (string) |
| Tier | numerical representation of the tier which the match was from: 1, 2, 3 or 4, where "1" is the top tier (currently the Premier League) (integer) |
| Result | the result "H" (home win), "A" (away win), "D" (draw) (string) |

### England League Results with team strength rankings

**File:** [`EnglandLeagueResults_wRanks.csv`](EnglandLeagueResults_wRanks.csv)

This file contains the same data as `EnglandLeagueResults.csv`, with chronological team-strength ratings and probabilities issued before each result. The `*_before` ratings are the previous posterior ratings; the probability columns also include the elapsed-time forecast step.

The database is a comma (",") delimited csv file with the following columns:

| Column | Details |
| ------ | ------- |
| Date | the day of the match (string; format "YYYY-MM-DD") |
| Season | the season the match took place in (string; format "YYYY/YYYY") |
| HomeTeam | the home team name (string) |
| AwayTeam | the away team name (string) |
| Score | the final score (string; format "X-Z") |
| hGoal | number of goals scored by the home team (integer; "X" from the "Score" column) |
| aGoal | number of goals scored by the away team (integer; "Z" from the "Score" column) |
| Division | name of the division the match was played in (string) |
| Tier | numerical representation of the tier which the match was from: 1, 2, 3 or 4, where "1" is the top tier (currently the Premier League) (integer) |
| Result | the result "H" (home win), "A" (away win), "D" (draw) (string) |
| HomeRank_before | the ranking of the home team before the fixture was played (integer) |
| AwayRank_before | the ranking of the away team before the fixture was played (integer) |
| HomeRank_after | the ranking of the home team after the fixture was played (integer) |
| AwayRank_after | the ranking of the away team after the fixture was played (integer) |
| HomeWinProbability | probability of a home win issued before the match |
| DrawProbability | probability of a draw issued before the match |
| AwayWinProbability | probability of an away win issued before the match |

### England League Names

**File:** [`EnglandLeagueNames.csv`](EnglandLeagueNames.csv)

A comma (",") delimited csv file of the names of the English football divisions and the years they were active. It has the following columns:

| Column | Details |
| ------ | ------- |
| Name | the name of the division (string) |
| Years Active | the seasons [inclusive - exclusive) that the name was/is active (string) |
| Tier | numerical representation of the tier which the match was from: 1, 2, 3 or 4, where "1" is the top tier (integer) |

### English Team Point Deductions

**File:** [`EnglishTeamPointDeductions.csv`](EnglishTeamPointDeductions.csv)

A comma (",") delimited csv file of all point deductions (and in two cases, additions), with reasoning, applied to English football league teams.

It has the following columns:

| Column | Details |
| ------ | ------- |
| Season | season string, for example 2024/2025 |
| Date | effective date of the adjustment (YYYY-MM-DD); historical forecasts must exclude later adjustments |
| Team | the team who the deduction was applied to (string) |
| Pts_deducted | the number of points deducted (a negative value means a point addition) (integer) |
| Notes | the reasoning for the points deduction (string) |

### English Team Logos

**File:** [`EnglishTeamLogos.csv`](EnglishTeamLogos.csv)

A comma (",") delimited csv file of all (known) English football league team logos/crests. The primary and secondary club colours are also included, these are not necessarily the same colours as the logo/crest. Where this should be white, a slightly off white colour (#808080) is used.

It has the following columns:

| Column | Details |
| ------ | ------- |
| Team Name | the English football league team name (matching the names in EnglandLeagueResults.csv) |
| URL | the link to image (png or svg), usually on Wikipedia |
| PriColour | the primary club colour as a Hex colour code |
| SecColour | the secondary club colour as a Hex colour code |

### English Team Active Years

**File:** [`EnglishTeamActivePeriods.csv`](EnglishTeamActivePeriods.csv)

A comma (",") delimited csv file of the periods which each club, which appears at least once in the database, was active within the top four tiers of English football (Premier League and English Football League). Breaks in appearances in these divisions are separated by a semicolon (";").

It has the following columns:

| Column | Details |
| ------ | ------- |
| Team | the English football league team name (matching the names in EnglandLeagueResults.csv) |
| ShortName | the short form name of the team (if they have one). E.g. "West Ham United" becomes "West Ham", "Manchester City" becomes "Man City" |
| Years | semicolon delimited list of active years, e.g. of the form YYYY-YYYY; YYYY-YYYY; YYYY-present. YYYY represents the initial year of that season, e.g. a club appearing in the top 4 tiers in the 1991/1992 season, leaving in 1995/1996 and then coming back from 2004 to present day would be: 1991-1995; 2004-present |

## Club naming conventions

Team names can be confusing across such a long record. The notes below answer the most common questions I have received about the names used in the database:

* [Accrington F.C.](https://en.wikipedia.org/wiki/Accrington_F.C.) is a different team to [Accrington Stanley](https://en.wikipedia.org/wiki/Accrington_Stanley_F.C.). Accrington F.C. were one of the founder members of the Football League, but were dissolved in 1896.
* [Aldershot](https://en.wikipedia.org/wiki/Aldershot_F.C.) and [Aldershot Town](https://en.wikipedia.org/wiki/Aldershot_Town_F.C.) are listed as separate teams (Aldershot Town was formed in the spring of 1992 after the closure of Aldershot).
* Throughout the database we refer to [Arsenal](https://en.wikipedia.org/wiki/Arsenal_F.C.) not "Woolwich Arsenal" (from 1893-1914) nor "The Arsenal" (from April 1914 - November 1919).
* [Brighton & Hove Albion](https://en.wikipedia.org/wiki/Brighton_%26_Hove_Albion_F.C.), [New Brighton Tower](https://en.wikipedia.org/wiki/New_Brighton_Tower_F.C.) and [New Brighton](https://en.wikipedia.org/wiki/New_Brighton_A.F.C.) are all different clubs. New Brighton Tower were in existence from 1896-1901 and whilst Brighton & Hove Albion were formed in 1901, the "spiritual" successor to New Brighton Tower, was New Brighton (1921-1983 and 1993-2012; originally formed by the relocation of [South Liverpool](https://en.wikipedia.org/wiki/South_Liverpool_F.C._(1890s)))
* Burton [Swifts](https://en.wikipedia.org/wiki/Burton_Swifts_F.C.), [Wanderers](https://en.wikipedia.org/wiki/Burton_Wanderers_F.C.), [United](https://en.wikipedia.org/wiki/Burton_United_F.C.), [Town](https://en.wikipedia.org/wiki/Burton_Town_F.C.) and [Albion](https://en.wikipedia.org/wiki/Burton_Albion_F.C.) are all different teams. Burton Swifts joined with Wanderers to form Burton United in 1901, which in 1924 merged with Burton Town and in 1950 merged with the newly formed Burton Albion.
* The Gateshead in the database refers to [Gateshead A.F.C](https://en.wikipedia.org/wiki/Gateshead_A.F.C.) not [Gateshead F.C.](https://en.wikipedia.org/wiki/Gateshead_F.C.).
* Whilst [Leeds United](https://en.wikipedia.org/wiki/Leeds_United_F.C.) were formed following/replacing [Leeds City](https://en.wikipedia.org/wiki/Leeds_City_F.C.) (and played in the same ground). No players or management from Leeds City moved to Leeds United so we treat them as separate football clubs.
* [Middlesbrough Ironopolis](https://en.wikipedia.org/wiki/Middlesbrough_Ironopolis_F.C.) (1889-1894) is separate team from [Middlesbrough](https://en.wikipedia.org/wiki/Middlesbrough_F.C.) (1876-).
* [Rotherham County](https://en.wikipedia.org/wiki/Rotherham_County_F.C.) merged with [Rotherham Town](https://en.wikipedia.org/wiki/Rotherham_Town_F.C._(1899)) in 1925 to form [Rotherham United](https://en.wikipedia.org/wiki/Rotherham_United_F.C.).
* Throughout the database we refer to [Stevenage](https://en.wikipedia.org/wiki/Stevenage_F.C.) not Stevenage Borough ("Borough" was dropped in June 2010).
* [Wigan Athletic](https://en.wikipedia.org/wiki/Wigan_Athletic_F.C.) were formed (1932) a year after [Wigan Borough](https://en.wikipedia.org/wiki/Wigan_Borough_F.C.) were wound up (1931) and we treat them separately. Wigan Athletic was the sixth attempt to create a stable football club in Wigan following the dissolving of Wigan A.F.C., [County](https://en.wikipedia.org/wiki/Wigan_County_F.C.) (1897-1900), [United](https://en.wikipedia.org/wiki/Wigan_United_A.F.C.) (1896-1914), [Town](https://en.wikipedia.org/wiki/Wigan_Town_A.F.C.) (1905-1908) and [Borough](https://en.wikipedia.org/wiki/Wigan_Borough_F.C.) (1920-1931).

## Sources and tools

### Data sources

The 1888-2016 data is based on that from the [Rec.Sport.Soccer Statistics Foundation](https://www.rsssf.org/) and James P. Curley ([2016](http://dx.doi.org/10.5281/zenodo.13158)).

### Tools

A number of tools making use of the data, such as a [league table generator](https://seanelvidge.com/leaguetable) and [head-to-head statistics](https://seanelvidge.com/h2h) are available at [seanelvidge.com/tools](https://seanelvidge.com/tools/)

## Licence and attribution

Prof. Sean Elvidge licenses his rights in the database and its accompanying documentation under the [Creative Commons Attribution 4.0 International licence (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/). This permits copying, sharing and adapting the licensed material for any purpose, including commercial use, with attribution. See [LICENCE](LICENCE.md) for the full terms and scope.

Suggested attribution:

> English Football League Data, constructed and updated by Prof. Sean Elvidge. [Source repository](https://github.com/seanelvidge/England-football-results). The work is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); other source material may have separate terms.

When sharing the licensed material, retain the attribution and licence notice, link to the source and licence, and indicate any changes you have made. Existing source credits must also be retained where required.

Third-party source data and linked club logos in the database may have separate rights and usage terms.

## Contact

If you have any corrections, comments or additional information, please feel free to open an [issue](https://github.com/seanelvidge/England-football-results/issues) or a [pull request](https://github.com/seanelvidge/England-football-results/pulls), or email me at `seanelvidge[at]gmail.com`.

Please also let me know if you use this data. I am interested in hearing how it is being used!
