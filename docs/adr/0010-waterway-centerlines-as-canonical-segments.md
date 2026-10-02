# ADR 0010: Waterway centerlines as canonical segments

## Status

Accepted

## Context

The economic map needs rivers, canals, and explicit fairways as transport and geographic infrastructure for future connections among ports, industry, and resource flows. OSM waterway tags describe physical features, while navigation metadata is incomplete. A river or canal tag alone cannot establish commercial navigability.

## Decision

Import qualifying OSM `waterway=river|canal|fairway` centerline ways through dedicated osm2pgsql Flex staging. Preserve each way's source identity and explicit navigation-related tags; keep missing evidence unknown and never infer navigability. Store each way as a canonical PostGIS LineString segment with `data_sources` provenance. Publish dynamic MVT through an explicit Martin function source. All segments are initially delivered from z5 pending real-data measurement.

## Consequences

This follows the railway and road linear-domain architecture, supports future graph relationships, and avoids large browser GeoJSON. A named river can comprise many canonical OSM segments. Navigation tags may be sparse, and physical waterways remain distinct from commercial navigation. No adjacent ways are merged and no polygon footprints are derived.

Waterway and route relations, official navigable-waterway registries, CEMT network enrichment, locks, dams and navigation barriers, depth/draft constraints, shipping routes, port-waterway graph links, topology assembly, entity resolution, and geometry generalization are deferred. The first fixed-snapshot benchmark will determine whether low-zoom MVT delivery needs optimization.
