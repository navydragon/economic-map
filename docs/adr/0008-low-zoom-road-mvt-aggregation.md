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
