# ADR 0008: Low-zoom road MVT aggregation

## Status

Accepted

## Context

The fixed Central Federal District benchmark measured 24,567 and 25,481 individual road features in density hotspot tiles at z7 and z9. This demonstrates low-zoom feature fragmentation. Higher-zoom results do not currently justify delivery changes.

## Decision

At z5–z9, collect eligible road geometry by `road_class` with `ST_Collect`, exposing only `road_class` and `is_link=false` without canonical feature IDs. Preserve semantic visibility thresholds, indexed candidate selection with the buffer query margin, and the existing source-layer and URL. At z10+, retain individual canonical features and detailed attributes. Apply the function change through a reversible Alembic migration.

## Consequences

Low-zoom tiles have fewer presentation features and less per-road property overhead, without canonical schema duplication or a new storage system. Their features cannot represent individual road identity. Canonical rows and geometries remain intact. The frontend already styles roads using the two retained properties.

Generalized tables, simplification, pre-generated tiles, and PMTiles are deferred. Rerun the exact same Central FD PBF/SHA with the existing representative and density hotspot sampler before choosing further optimizations. Single-request timings are not production latency SLOs.

## Measured validation

The A/B run on the same Central FD PBF (SHA-256 `7ee7793c58c5c9b210837d06706ae73c5152e8120490eb1a5afdd64db4288378`) retained 174,930 canonical roads and the same density-hotspot midpoint counts. Aggregate feature counts fell from 8,689 to 2 at z5, 24,567 to 4 at z7, and 25,481 to 5 at z9; wire bytes fell by 62.6%, 64.5%, and 56.8%, respectively. z11 and z13 feature counts stayed at 5,588 and 773. The result resolves low-zoom feature fragmentation at the tested regional scale. Retain this decision and close Road Phase 2D for that scale. The z9 dense geometry payload remains a watchpoint for whole-Russia testing; no further production optimization is justified by this run. See [the full A/B measurements](../architecture/road-performance.md).
