# ADR 0009: Ports as canonical point facilities

## Status

Accepted

## Context

The economic map needs public civilian ports as transport and economic nodes for future relationships. OSM represents these facilities as nodes, polygons, and multipolygon relations with uneven tagging. Importing generic piers, marinas, or ferry stops would broaden the domain beyond cargo and civilian port facilities.

## Decision

Import only explicit port semantics through dedicated osm2pgsql Flex staging. Preserve OSM object type, numeric ID, and shared `data_sources` provenance. Store a canonical Point in PostGIS: retain source node points and use `ST_PointOnSurface` for polygon and multipolygon facilities. Publish selected attributes from a zoom-aware PostgreSQL MVT function through an explicit Martin source. Unknown water context stays NULL unless explicit source tags support a value.

## Consequences

Point delivery is compact and can support future graph or flow endpoints without browser GeoJSON. A canonical point does not preserve the full port footprint. Distinct OSM objects or overlapping source slugs may represent the same real-world facility; they remain distinct until an explicit entity resolution phase. Official registry enrichment, throughput statistics, commodity specialization, hierarchy, footprints, berths, shipping routes, and AIS are deferred.
