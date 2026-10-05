# Waterway real-data validation benchmark

The manual [Waterway real-data benchmark](../../.github/workflows/waterway-benchmark.yml) defaults to the fixed [Central Federal District 2026-09-28 OSM extract](https://download.geofabrik.de/russia/central-fed-district-260928.osm.pbf), `central-fed-district-260928.osm.pbf`. The measured file was 878,606,707 bytes with SHA-256 `7ee7793c58c5c9b210837d06706ae73c5152e8120490eb1a5afdd64db4288378`. A manually supplied compatible HTTPS `.osm.pbf` may differ. Normal CI remains synthetic and offline from Geofabrik.

The report records source provenance, PBF size and SHA-256, separate workflow stage timings, staging and canonical counts, class distribution, naming coverage, explicit navigation metadata coverage, a class-by-navigation matrix, top source values, geometry and identity quality, vertex counts, geodesic segment lengths, and deterministic semantic audit samples. It does not infer navigability: a river or canal is a physical waterway, and missing navigation tags are unknown. Explicit navigation metadata coverage measures OSM tagging coverage, **not** the true navigable network.

## MVT sampling

At z5, z7, z9, z11 and z13, PostgreSQL selects spatially ordered first, median and last canonical segment midpoints (`ST_LineInterpolatePoint(geom, 0.5)`) for representative tile requests. It also buckets every canonical segment midpoint into XYZ tiles and selects one density hotspot per zoom by candidate count descending, then x and y ascending. A tile selected for both roles is requested once, retaining both labels. The public Martin source `/waterway_segments/{z}/{x}/{y}` is measured directly for HTTP status, compressed wire bytes, decoded bytes, feature count and request time.

Midpoint density is a fragmentation proxy, **not** the exact densest tile or an exhaustive worst-case search. Long lines may cross tiles even when their midpoint lies elsewhere; the MVT query includes a buffer. Actual decoded MVT feature counts are authoritative for the requested tiles. Stage and single-request timings are diagnostics, not production SLOs. No arbitrary payload pass/fail threshold is used.

## Pre-aggregation Central FD baseline

The completed first run found 23,923 canonical segments: 22,311 river (93.26%), 1,605 canal (6.71%), and 7 fairway (0.03%). Geometry and identity quality errors were all zero. There were 19,579 named segments (81.84%) and 4,344 unnamed segments (18.16%). Explicit navigation-related tagging appeared on 3,810 segments (15.93%); this includes 3,114 `boat_access=no` restrictions and therefore **does not measure navigability**. Coverage was 3,660 `boat_access` (15.30%), 297 `motorboat_access` (1.24%), 53 `ship_access` (0.22%), and 241 `cemt_class` (1.01%). Missing tags remain unknown.

| Zoom | Candidate midpoints | MVT features | Wire bytes | Decoded bytes | Single request seconds |
|---|---:|---:|---:|---:|---:|
| z5 | 13,209 | 10,396 | 278,525 | 680,528 | 1.128 |
| z7 | 3,018 | 2,595 | 92,819 | 205,303 | 0.189 |
| z9 | 710 | 741 | 24,153 | 43,617 | 0.038 |
| z11 | 215 | 212 | 5,224 | 8,318 | 0.007 |
| z13 | 90 | 99 | 1,923 | 3,093 | 0.004 |

These are diagnostic single requests, not production SLOs. Severe z5 and substantial z7 feature fragmentation motivate [request-time z5–z8 presentation aggregation](../adr/0011-low-zoom-waterway-presentation-aggregation.md). The z9+ measurements do not justify changing detailed delivery. Canonical storage and the explicit OSM filter remain unchanged. No post-aggregation Central FD measurements have been recorded yet; rerun the same fixed snapshot manually for the A/B comparison.
