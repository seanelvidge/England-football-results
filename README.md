# England League Results (EnglandLeagueResults.csv)
This is a plain text database of all England football (soccer) league results from 1888 to 2025/12/30 (covering 211,207 matches).

The database is updated roughly every two days for the top four tiers in English football: Premier League, EFL Championship, EFL League One and EFL League Two.

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


Such a long database of results leads to some confusion around team names, the answer to the most common set of questions I have received in terms of team names:

* [Accrington F.C.](https://en.wikipedia.org/wiki/Accrington_F.C.) is a different team to [Accrington Stanley](https://en.wikipedia.org/wiki/Accrington_Stanley_F.C.). Acrrington F.C. were one of the founder members of the Football League, but were dissolved in 1896.
* [Aldershot](https://en.wikipedia.org/wiki/Aldershot_F.C.) and [Aldershot Town](https://en.wikipedia.org/wiki/Aldershot_Town_F.C.) are listed as separate teams (Aldershot Town was formed in the spring of 1992 after the closure of Aldershot).
* Throughout the database we refer to [Arsenal](https://en.wikipedia.org/wiki/Arsenal_F.C.) not "Woolwich Arsenal" (from 1893-1914) nor "The Arsenal" (from April 1914 - November 1919).
* [Brighton & Hove Albion](https://en.wikipedia.org/wiki/Brighton_%26_Hove_Albion_F.C.), [New Brighton Tower](https://en.wikipedia.org/wiki/New_Brighton_Tower_F.C.) and [New Brighton](https://en.wikipedia.org/wiki/New_Brighton_A.F.C.) are all different clubs. New Brighton Tower were in existence from 1896-1901 and whilst Brighton & Hove Albion were formed in 1901, the "spiritual" successor to New Brighton Tower, was New Brighton (1921-1983 and 1993-2012; originally formed by the relocation of [South Liverpool](https://en.wikipedia.org/wiki/South_Liverpool_F.C._(1890s)))
* Burton [Swifts](https://en.wikipedia.org/wiki/Burton_Swifts_F.C.), [Wanderers](https://en.wikipedia.org/wiki/Burton_Wanderers_F.C.), [United](https://en.wikipedia.org/wiki/Burton_United_F.C.), [Town](https://en.wikipedia.org/wiki/Burton_Town_F.C.) and [Albion](https://en.wikipedia.org/wiki/Burton_Albion_F.C.) are all different teams. Burton Swifts joined with Wanderers to form Burton United in 1901, which in 1924 merged with Burton Town and in 1950 merged with the newly formed Burton Albion.
* The Gateshead in the database refers to [Gateshead A.F.C](https://en.wikipedia.org/wiki/Gateshead_A.F.C.) not [Gateshead F.C.](https://en.wikipedia.org/wiki/Gateshead_F.C.).
* Whilst [Leeds Unitd](https://en.wikipedia.org/wiki/Leeds_United_F.C.) were formed following/replacing [Leeds City](https://en.wikipedia.org/wiki/Leeds_City_F.C.) (and played in the same ground). No players or management from Leeds City moved to Leeds United so we treat them as separate football clubs.
* [Middlesbrough Ironopolis](https://en.wikipedia.org/wiki/Middlesbrough_Ironopolis_F.C.) (1889-1894) is separate team from [Middlesbrough](https://en.wikipedia.org/wiki/Middlesbrough_F.C.) (1876-).
* [Rotherham County](https://en.wikipedia.org/wiki/Rotherham_County_F.C.) merged with [Rotherham Town](https://en.wikipedia.org/wiki/Rotherham_Town_F.C._(1899)) in 1925 to form [Rotherham United](https://en.wikipedia.org/wiki/Rotherham_United_F.C.).
* Throughout the database we refer to [Stevenage](https://en.wikipedia.org/wiki/Stevenage_F.C.) not Stevenage Borough ("Borough" was dropped in June 2010).
* [Wigan Athletic](https://en.wikipedia.org/wiki/Wigan_Athletic_F.C.) were formed (1932) a year after [Wigan Borough](https://en.wikipedia.org/wiki/Wigan_Borough_F.C.) were wound up (1931) and we treat them separately. Wigan Athletic was the sixth attempt to create a stable football club in Wigan following the dissolving of Wigan A.F.C., [County](https://en.wikipedia.org/wiki/Wigan_County_F.C.) (1897-1900), [United](https://en.wikipedia.org/wiki/Wigan_United_A.F.C.) (1896-1914), [Town](https://en.wikipedia.org/wiki/Wigan_Town_A.F.C.) (1905-1908) and [Borough](https://en.wikipedia.org/wiki/Wigan_Borough_F.C.) (1920-1931).

The 1888-2016 data is based on that from the [Rec.Sport.Soccer Statistics Foundation](https://www.rsssf.org/) and James P. Curley ([2016](http://dx.doi.org/10.5281/zenodo.13158)).

A number of tools making use of the data, such as a [league table generator](https://seanelvidge.com/leaguetable) and [head-to-head statistics](https://seanelvidge.com/h2h) are available at [seanelvidge.com/tools](https://seanelvidge.com/tools/)


# England League Results with team strength rankings (EnglandLeagueResults_wRank.csv)
This file contains the same data as `EnglandLeagueResults.csv` but with a measure of the teams strength via a ranking scheme.

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


# England League Names (EnglandLeagueNames.csv)

A comma (",") delimited csv file of the names of the English football divisions and the years they were active. It has the following columns:

| Column | Details |
| ------ | ------- |
| Name | the name of the division (string) |
| Years Active | the seasons [inclusive - exclusive) that the name was/is active (string) |
| Tier | numerical representation of the tier which the match was from: 1, 2, 3 or 4, where "1" is the top tier (integer) |


# English Team Point Deductions (EnglishTeamPointDeductions.csv)

A comma (",") delimited csv file of all point deductions (and in two cases, additions), with reasoning, applied to English football league teams.

It has the following columns:

| Column | Details |
| ------ | ------- |
| Season | the season the deduction took place in (where, for example, 2025 refers to the 2024/2025 season) (integer) |
| Team | the team who the deduction was applied to (string) |
| Pts_deducted | the number of points deducted (a negative value means a point addition) (integer) |
| Notes | the reasoning for the points deduction (string) |


# English Team Logos (EnglishTeamLogos.csv)

A comma (",") delimited csv file of all (known) English football league team logos.

It has the following columns:

| Column | Details |
| ------ | ------- |
| Team Name |the English football league team name (matching the names in EnglandLeagueResults.csv) |
| URL | the link to image (png or svg), usually on Wikipedia |


# English Team Active Years (EnglishTeamActivePeriods.csv)

A comma (",") delimited csv file of the periods which each club, which appears at least once in the database, was active within the top four tiers of English football (Premier League and English Football League). Breaks in apperances in these divisions are separated by a semicolon (";").

It has the following columns:

| Column | Details |
| ------ | ------- |
| Team | the English football league team name (matching the names in EnglandLeagueResults.csv) |
| ShortName | the short form name of the team (if they have one). E.g. "West Ham United" becomes "West Ham", "Manchester City" becomes "Man City" |
| Years | semicolon delimited list of active years, e.g. of the form YYYY-YYYY; YYYY-YYYY; YYYY-present. YYYY represents the initial year of that season, e.g. a club appearing in the top 4 tiers in the 1991/1992 season, leaving in 1995/1996 and then coming back from 2004 to present day would be: 1991-1995; 2004-present |



