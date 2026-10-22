# Validation against the 2019 Storm Drainage Master Plan

Benchmark: TMR Figures 8.2 and 8.3, existing conditions, 1:100-year 4-hour storm (Dillon Consulting, June 2019), georeferenced and digitised in `scripts/08a_georef_benchmark.py`. The two figures cover 99% of the Lesperance study area.

Our results: pass 2 (spill-over), storm sewers assumed full, rail-ditch and pond depressions excluded. Water depth at the end of each storm.

## A. Plan test: problem areas

The plan's test counts problem areas that contain or touch an overflowing depression. Only 2 of the plan's problem areas overlap the Lesperance study area, so this test is reported for completeness but cannot support a 7-in-10 judgement.

| Problem area | Type | Area in study area | 100-year | 2017-like |
|---|---|---|---|---|
| fig82_R1 | regional | 67.5 ha | hit (393 depressions) | hit (395 depressions) |
| fig83_R2 | regional | 2.7 ha | hit (13 depressions) | hit (13 depressions) |

## B. Spot test (primary)

Domain: streets (OSM centrelines ± 10 m) inside the study area and inside the figures, where the plan reports ponding. Tolerance 15 m.

| Measure | 100-year | 2017-like |
|---|---|---|
| **Recall**: plan deep spots (> 0.30 m) with our water ≥ 0.15 m within 15 m | **94%** (81/86) | **94%** (81/86) |
| Chance level: street length within 15 m of our water ≥ 0.15 m (recall a random spot would get) | 54.9% | 55.1% |
| Precision: our deep spots (≥ 0.30 m) with any plan ponding within 15 m (chance level 77.2%) | 80% (33/41) | 81% (35/43) |
| Precision: our deep spots (≥ 0.30 m) with plan ponding ≥ 0.15 m within 15 m (chance level 61.6%) | 80% (33/41) | 81% (35/43) |
| Precision: our deep spots (≥ 0.30 m) with plan ponding > 0.30 m within 15 m (chance level 11.8%) | 39% (16/41) | 40% (17/43) |
| Plan ponding ≥ 0.15 m area with our water ≥ 0.15 m nearby | 75.7% | 75.8% |
| Our water ≥ 0.15 m area with plan ponding ≥ 0.15 m nearby | 84.4% | 84.0% |

**Pass mark: at least 7 in 10. Result: PASS** (recall 94% for the 100-year storm, 94% for the 2017-like storm).

**Reading the numbers against chance.** Our water covers a lot of the street network, so a randomly placed spot would be 'hit' 55% of the time; the 7-in-10 pass mark is therefore lenient here. Recall of 94% is far above that (probability of 81/86 or better by chance: 5.6e-16). Precision against *any* plan ponding is close to its chance level (77.2%), because the plan shows some ponding on most streets, so it carries little information; precision against the plan's deeper ponding is the more telling figure.

### Effect of the rail-ditch rule

The rail-ditch rule was changed during validation, so both versions are scored here on the same water results:

| Rail-ditch rule | Recall 100-year | Recall 2017-like | Precision 100-year | Verdict |
|---|---|---|---|---|
| v1: any depression touching a 30 m railway buffer | 87% (75/86) | 87% | 77% | PASS |
| **v2 (final)**: ≥ 50 % of the depression within 15 m of the track | **94%** (81/86) | **94%** | 80% | **PASS** |

Why it changed: under v1, misses on Tecumseh Rd lay on depressions that hold 0.15–1.5 m of water but were excluded because Tecumseh Rd runs only 16–55 m from the CN tracks; the plan's own model, which includes pipes and culverts, shows deep ponding at the same places. v2 limits the flag to the rail right-of-way. Because the change was prompted by this test, the v2 result is not an independent confirmation; it measures the remaining disagreement once the rule error was fixed.

## Misses (100-year) and likely reasons

| Spot | Nearest street | Plan spot area | Our depth nearby | Our depth if full | Likely reason |
|---|---|---|---|---|---|
| 89 | Tecumseh Road | 311 m² | 0.03 m | 0.03 m | no depression in the terrain: plan's ponding comes from sewer surcharge / pump-station backwater (HGL), not a surface low point |
| 69 | Tecumseh Road East | 196 m² | 0.00 m | 0.00 m | no depression in the terrain: plan's ponding comes from sewer surcharge / pump-station backwater (HGL), not a surface low point |
| 93 | Southpark Lane | 136 m² | 0.06 m | 0.06 m | only a shallow depression in our terrain (< 0.15 m when full) |
| 95 | Lesperance Road | 110 m² | 0.06 m | 0.06 m | only a shallow depression in our terrain (< 0.15 m when full) |
| 66 | Lacasse Boulevard | 94 m² | 0.10 m | 0.10 m | only a shallow depression in our terrain (< 0.15 m when full) |

Reason counts: 3 × only a shallow depression in our terrain (< 0.15 m when full); 2 × no depression in the terrain: plan's ponding comes from sewer surcharge / pump-station backwater (HGL), not a surface low point

## Why the methods differ

- The plan's 2D PCSWMM model includes the pipes, pump-station capacity and backwater (HGL); ours is terrain-only with sewers assumed full. Ponding caused by surcharging sewers with no surface low point cannot appear in our results.
- The plan excluded parkland and private property; it reports roadway ponding only. Most of our depressions are in yards, which is why the comparison is limited to streets.
- The benchmark was digitised from a figure without coordinates; alignment error is about 10–20 m, and the plan's ponding is drawn as ~17 m hexagons.
- The plan's terrain model dates from before 2019; our lidar is 2016–18 and imagery 2025.
