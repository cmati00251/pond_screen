# Benchmark: Tecumseh Storm Drainage Master Plan (Dillon, June 2019)

Page references give the **PDF page** first and the printed page in brackets.
TMR = Volume 2, Technical Modelling Report. APX = TMR appendices.
EA = Volume 1, EA report. PNGs listed in `pages.csv`.

## (a) The 11 drainage service areas

| PNG | Source | What it shows |
|---|---|---|
| `tmr_fig1-2_service_areas.png` | TMR p15 [p5], Fig 1.2 | The 11 service areas, colour-coded: 8 pump stations (1 Lesperance, 2 West St. Louis, 3 East St. Louis, 4 East Townline Drain (ETLD), 5 Scully, 6 St. Mark's, 7 PJ Cecile, 8 Brighton) and 3 gravity outfalls (9 Pilots Cove, 10 Southwind/Starwood, 11 Mei-Lin). |
| `tmr_fig8-6_major_system_areas.png` | TMR p91 [p81], Fig 8.6 | Service-area boundaries (grey lines) over aerial imagery, plus 11 *major system* (overland) drainage areas and the flow-barrier landforms (railways, County Rd 22, Tecumseh Rd, Manning Rd). Better for drawing boundaries than Fig 1.2. |

The same Fig 1.2 also appears as EA Fig 1.2.

## (b) Existing-condition surface flooding

The plan used a 1D/2D PCSWMM model, mainly with the **1:100-year, 4-hour Chicago
storm**. "Problem areas" are drawn as red outlines over modelled ponding
depths, shown in three bands: under 0.15 m, 0.15–0.30 m, and over 0.30 m.

| PNG | Source | What it shows |
|---|---|---|
| `tmr_fig8-2_problem_W1_W2.png` | TMR p84 [p74], Fig 8.2 (= EA Fig 6.1) | Regional problem areas **W-1** (Lesperance + West St. Louis) and **W-2** (East St. Louis), plus 6 isolated areas |
| `tmr_fig8-3_problem_W3.png` | TMR p85 [p75], Fig 8.3 (= EA Fig 6.2) | Regional problem area **W-3** (Baillargeon Drain, inside the ETLD service area south of County Rd 22), plus 1 isolated area |
| `tmr_fig8-5_problem_E1.png` | TMR p89 [p79], Fig 8.5 (= EA Fig 6.3) | Regional problem area **E-1** (Scully, St. Mark's, PJ Cecile), plus about 6 isolated areas including Southwind/Starwood |
| `tmr_fig8-1_hgl_2yr_west.png` | TMR p81 [p71], Fig 8.1 | How full the storm sewers run in a 1:2-year storm, west of Manning Rd (context only) |
| `tmr_fig8-4_hgl_2yr_east.png` | TMR p87 [p77], Fig 8.4 | The same, east of Manning Rd |
| `tmr_fig11-15` … `11-22` | TMR p151–158 [p141–148] | Each problem area under the 1:100-year storm and the 1:100-year storm + 40%, existing vs future. Gives zoomed-in views of the existing-condition ponding. |
| `apx_figC-1_ponding.png` | APX p596, Fig C-1 | Whole town, existing ponding, 1:5-year 4-hour storm |
| `apx_figC-2_ponding.png` | APX p597, Fig C-2 | Whole town, existing ponding, 1:10-year 4-hour storm |
| `apx_figC-3_ponding_24h39.png` | APX p598, Fig C-3 | Whole town, existing ponding, 1:100-year 24-hour + 39% storm (150 mm) |

Not rendered:
- APX Appendix A (p2–93) has photos of real flooding from the 2016 event.
- TMR Table 14.1 (p169 [p159]) gives capital costs by area.
- TMR Fig 2.1 (p23 [p13], = EA Fig 3.3) compares the Aug 28, 2017 storm with
  the Windsor A IDF curves. That's useful for Step 7.

## Which service areas flood worst (existing, 1:100-year)

1. **Lesperance (+ West St. Louis), problem area W-1.** This is the largest
   regional problem area. Ponding is widespread, with long stretches deeper
   than 0.30 m along Lesperance Rd, St. Pierre St, Lacasse Blvd, William St,
   Little River Blvd and Dillon Dr. The cause is backwater: during big storms
   the Lesperance and West St. Louis pump stations back flow up into the
   sewers, so water collects at road low points that have no overland escape
   route (TMR p82 [p72]). The two areas are joined by a sewer at
   St. Pierre St / Riverside Dr and act together in large storms.
2. **Scully / St. Mark's / PJ Cecile, problem area E-1.** This area has dense
   ponding deeper than 0.30 m around Grant Ave, Hayes Ave, St. Mark's Rd,
   Arlington Blvd and Clovelly Rd. The causes are mostly shallow roadside
   ditches, with backwater from the Scully pump station and a sewer
   bottleneck at Hayes Ave / Grant Ave (TMR p88 [p78]).
3. **ETLD (Baillargeon Drain), problem area W-3.** Ponding is patchy but
   deep in the subdivision east of Lesperance Rd, south of County Rd 22.
   There's also a low point on Lesperance Rd between North Pacific Ave and
   Intersection Rd with no overland route (TMR p83 [p73]).
4. **East St. Louis, problem area W-2.** The text says this area has "the
   least amount of surface flooding" west of Manning. It's concentrated
   upstream on Green Valley Dr, with a possible bottleneck at
   Green Valley Dr / St. Thomas St (TMR p82–83 [p72–73]).
5. **Gravity outfalls and Brighton.** These only have isolated problems. At
   Southwind Cres / Starwood Ln the cause is high lake levels backing up the
   outfall, not the shape of the ground (TMR p90 [p80]). Pilots Cove, Mei-Lin
   and Brighton have small isolated spots only.

## Notes for the method

- The plan's flooding comes from a model that includes the pipe network, pump
  station limits and lake levels. Our method looks only at the ground surface
  with the sewers assumed full, so it should match flooding caused by low
  points in the road and missing overland routes best (W-1, W-2, W-3 and the
  isolated areas). It will miss flooding caused by high lake levels
  (Southwind/Starwood).
- The plan says parkland and private property were "not to be analyzed" (the
  green areas on the maps). Its problem areas are only on public roads, so
  depressions in parks will look like false alarms in the Step 8 check.
- All maps are drawn in NAD 1983 UTM 17N. They have no grid, so they will be
  georeferenced in Step 8 using street intersections as control points.
