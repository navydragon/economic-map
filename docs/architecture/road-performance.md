# Road performance baseline

Major roads begin with server-side semantic zoom filtering because the railway benchmarks showed that dense linear infrastructure can over-deliver at low zoom. The road MVT function selects candidates with the same `64 / 4096` query margin as its encoder buffer, preserving line fragments near tile edges.

The manual [Road real-data benchmark](../../.github/workflows/road-benchmark.yml) measures production Martin tiles at z5, z7, z9, z11, and z13 and records import timing, canonical quality, relation sizes, and tile payloads. It defaults to the fixed Kaliningrad 2026-09-28 Geofabrik snapshot; a compatible HTTPS `.osm.pbf` URL may be supplied manually. The older `kaliningrad-latest.osm.pbf` default repeatedly hit a redirect loop on GitHub-hosted runners.

## Initial fixed-snapshot baselines

| Dataset | PBF bytes | SHA-256 | Canonical roads | Database total bytes |
| --- | ---: | --- | ---: | ---: |
| [Kaliningrad 2026-09-28](https://download.geofabrik.de/russia/kaliningrad-260928.osm.pbf) | 29,119,609 | `db5d410e8aca5e731a37087253b734026d495cfe0bc6c389d29c3651466eae0d` | 10,129 | 4,071,424 |
| [North Caucasus 2026-09-28](https://download.geofabrik.de/russia/north-caucasus-fed-district-260928.osm.pbf) | 128,670,929 | `c72f11d0b2b4857d0a0e44a30e4e5bf90dc75d846976d17349b8064f7f0b5dea` | 23,501 | 12,279,808 |

These runs used the original first/median/last spatial midpoint sampling. The largest payload among those representative samples at each zoom was:

| Zoom | Kaliningrad features | Kaliningrad wire bytes | Kaliningrad seconds | North Caucasus features | North Caucasus wire bytes | North Caucasus seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| z5 | 602 | 7,572 | 0.047 | 864 | 13,704 | 0.046 |
| z7 | 4,698 | 68,153 | 0.100 | 3,933 | 69,018 | 0.066 |
| z9 | 6,113 | 92,214 | 0.131 | 377 | 11,004 | 0.006 |
| z11 | 4,530 | 69,871 | 0.074 | 95 | 3,131 | 0.002 |
| z13 | 1,004 | 16,825 | 0.016 | 10 | 607 | 0.001 |

The North Caucasus source contained 11,422 tertiary, 5,713 secondary, 3,864 primary, and 2,502 trunk roads; 895 were links. Both datasets passed geometry quality checks. The large difference in higher-zoom sampled payloads exposed a limitation of the three-location sampling method, not a production regression. No production road optimization is justified by these runs.

## Density-oriented follow-up

The original representative samples remain valid and are retained for historical comparability. Before benchmarking Central Federal District, the sampler now adds one deterministic density hotspot candidate per zoom. It groups midpoints of roads eligible under that zoom's production visibility rule into XYZ tiles, then chooses the bucket with the most midpoints, breaking ties by smallest x and then y. The candidate midpoint count is a density proxy; actual MVT feature count comes from Martin. Lines may cross tile boundaries, and the MVT function has a buffer, so this is **not** an exhaustive worst-case tile search. If the hotspot and a representative sample name the same tile, the benchmark requests it once and records both roles. The earlier runs have no hotspot measurements, and none are inferred retroactively.

Individual request times are diagnostics, not production latency SLOs. PMTiles, generalized geometry, and simplification remain evidence-driven options; none is introduced in this phase.
