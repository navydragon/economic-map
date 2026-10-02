# Waterway real-data validation benchmark

The manual [Waterway real-data benchmark](../../.github/workflows/waterway-benchmark.yml) defaults to the fixed [Central Federal District 2026-09-28 OSM extract](https://download.geofabrik.de/russia/central-fed-district-260928.osm.pbf). Earlier project benchmarks used a 878,606,707-byte file with SHA-256 `7ee7793c58c5c9b210837d06706ae73c5152e8120490eb1a5afdd64db4288378`; the waterway report will measure the downloaded file's actual size and hash to confirm comparability. A manually supplied compatible HTTPS `.osm.pbf` may differ. Normal CI remains synthetic and offline from Geofabrik.

The report records source provenance, PBF size and SHA-256, separate workflow stage timings, staging and canonical counts, class distribution, naming coverage, explicit navigation metadata coverage, a class-by-navigation matrix, top source values, geometry and identity quality, vertex counts, geodesic segment lengths, and deterministic semantic audit samples. It does not infer navigability: a river or canal is a physical waterway, and missing navigation tags are unknown. Explicit navigation metadata coverage measures OSM tagging coverage, **not** the true navigable network.

## MVT sampling

At z5, z7, z9, z11 and z13, PostgreSQL selects spatially ordered first, median and last canonical segment midpoints (`ST_LineInterpolatePoint(geom, 0.5)`) for representative tile requests. It also buckets every canonical segment midpoint into XYZ tiles and selects one density hotspot per zoom by candidate count descending, then x and y ascending. A tile selected for both roles is requested once, retaining both labels. The public Martin source `/waterway_segments/{z}/{x}/{y}` is measured directly for HTTP status, compressed wire bytes, decoded bytes, feature count and request time.

Midpoint density is a fragmentation proxy, **not** the exact densest tile or an exhaustive worst-case search. Long lines may cross tiles even when their midpoint lies elsewhere; the MVT query includes a buffer. Actual decoded MVT feature counts are authoritative for the requested tiles. Stage and single-request timings are diagnostics, not production SLOs. No arbitrary payload pass/fail threshold is used.

The first manual run has not yet produced waterway measurements. No production filtering, zoom rule, geometry generalization or MVT optimization is selected before reviewing the benchmark artifact.
