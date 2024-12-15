This is a plain text database of all England football (soccer) league results from 1888 to 2024/12/11, covering 208,972 matches).

The database is updated roughly every two days (although I am looking for approaches to speed this up) for the top four divisions in England: Premier League, Championship, League 1 and League 2.

The 1888-2016 data is based on that from:
James P. Curley (2016). engsoccerdata: English Soccer Data 1871-2016. http://dx.doi.org/10.5281/zenodo.13158

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
| Division | numerical representation of the division which the match was from: 1, 2, 3 or 4, where "1" is the top division (currently the Premier League) (integer) |
| Result | the result "H" (home win), "A" (away win), "D" (draw) (string) |


Between 1921 and 1958 there was a Third Division North and South, in the database we give both the numerical representation "3".

Such a long database of results leads to some confusion around team names, the answer to the most common set of questions I have received in terms of team names:

* [Accrington F.C.](https://en.wikipedia.org/wiki/Accrington_F.C.) is a different team to [Accrington Stanley](https://en.wikipedia.org/wiki/Accrington_Stanley_F.C.). Acrrington F.C. were one of the founder members of the Football League, but unfortunately were dissolved in 1896.
* [Brighton & Hove Albion](https://en.wikipedia.org/wiki/Brighton_%26_Hove_Albion_F.C.), [New Brighton Tower](https://en.wikipedia.org/wiki/New_Brighton_Tower_F.C.) and [New Brighton](https://en.wikipedia.org/wiki/New_Brighton_A.F.C.) are all different clubs. New Brighton Tower were in existence from 1896-1901 and whilst Brighton & Hove Albion were formed in 1901, the "spiritual" successor to New Brighton Tower, was New Brighton (1921-1983 and 1993-2012; originally formed by the relocation of [South Liverpool](https://en.wikipedia.org/wiki/South_Liverpool_F.C._(1890s)))
* Burton [Swifts](https://en.wikipedia.org/wiki/Burton_Swifts_F.C.), [Wanderers](https://en.wikipedia.org/wiki/Burton_Wanderers_F.C.), [United](https://en.wikipedia.org/wiki/Burton_United_F.C.), [Town](https://en.wikipedia.org/wiki/Burton_Town_F.C.) and [Albion](https://en.wikipedia.org/wiki/Burton_Albion_F.C.) are all different teams. Burton Swifts joined with Wanderers to form Burton United in 1901, which in 1924 merged with Burton Town and in 1950 merged with the newly formed Burton Albion.
* Whilst [Leeds Unitd](https://en.wikipedia.org/wiki/Leeds_United_F.C.) were formed following/replacing [Leeds City](https://en.wikipedia.org/wiki/Leeds_City_F.C.) (and played in the same ground). No players or management from Leeds City moved to Leeds United so we treat them as separate football clubs.
* [Middlesbrough Ironopolis](https://en.wikipedia.org/wiki/Middlesbrough_Ironopolis_F.C.) (1889-1894) is separate team from [Middlesbrough](https://en.wikipedia.org/wiki/Middlesbrough_F.C.) (1876-).
* [Rotherham County](https://en.wikipedia.org/wiki/Rotherham_County_F.C.) merged with [Rotherham Town](https://en.wikipedia.org/wiki/Rotherham_Town_F.C._(1899)) in 1925 to form [Rotherham United](https://en.wikipedia.org/wiki/Rotherham_United_F.C.).
* [Wigan Athletic](https://en.wikipedia.org/wiki/Wigan_Athletic_F.C.) were formed (1932) a year after [Wigan Borough](https://en.wikipedia.org/wiki/Wigan_Borough_F.C.) were wound up (1931) and we treat them separately. Wigan Athletic was the sixth attempt to create a stable football club in Wigan following the dissolving of Wigan A.F.C., [County](https://en.wikipedia.org/wiki/Wigan_County_F.C.) (1897-1900), [United](https://en.wikipedia.org/wiki/Wigan_United_A.F.C.) (1896-1914), [Town](https://en.wikipedia.org/wiki/Wigan_Town_A.F.C.) (1905-1908) and [Borough](https://en.wikipedia.org/wiki/Wigan_Borough_F.C.) (1920-1931).
