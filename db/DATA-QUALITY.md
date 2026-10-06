# Data quality checks

Source: CricClubs scorecards for NACL Div A. Run the checks after every load.

| Season | Matches loaded | Excluded |
|---|---|---|
| Spring 2026 | 66 of 71 | 5 with no result (below) |
| Summer 2026 | 68 of 68 | none |

| Check | Result |
|---|---|
| Innings total = batting runs + extras | 267 of 268 match |
| Last over's cumulative score = innings total and wickets | 266 of 268 match |
| Every innings has over-by-over data | 268 of 268 |

## Known source discrepancies (kept as published)

The official innings totals are treated as the source of truth.

- **Summer 4338, innings 2** (Ghadeer Lions vs Innovation Strikers): batting 142 + extras 16 = 158; published total 159.
- **Summer 4569, innings 1** (Lords vs Seamers): bowlers' figures add up to 20 overs; published total says 19.5.
- **Spring 4230, innings 2**: over-by-over ends on 85; published total 83.
- **Spring 4257, innings 2**: over-by-over wickets differ from the published total.

## Excluded Spring matches (no result)

- 4155 Vikings vs CSK Yorkers, 4156 Unstoppable vs Revenants, 4157 Lords vs NextGen Tailenders,
  4275 Singh Cricket Club vs Vikings: no play (0/0).
- 4147 Money Heist vs Astros+: abandoned at 67/3 after 10.4 overs.

## Special results

- **Summer 4346** (Astros+ vs Orange Army): tied on 191, Astros+ won the Super Over.
- **Spring 4107** (Unstoppable vs CSK Yorkers): tied on 118, no Super Over. Counts as neither a win nor a loss.
- **Spring 4212, 4247**: won by 1 run.

## Comparing seasons

11 of the 16 teams played Div A in both seasons. Spring scoring was much lower (division run rate
5.76 vs 7.35), so season comparisons use ranks and gaps to the division, not raw numbers.
