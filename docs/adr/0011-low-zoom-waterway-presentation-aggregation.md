# ADR 0011: Low-zoom waterway presentation aggregation

## Status

Accepted for Phase 2F.2; real-data A/B pending

## Context

The fixed Central FD benchmark measured 10,396 MVT features at the z5 density hotspot and 2,595 at z7 from 23,923 canonical OSM way segments. The z9 hotspot had only 741 features and modest payload. OSM way fragmentation, rather than canonical storage or production filtering, is the measured low-zoom presentation problem. The [baseline](../architecture/waterway-performance.md) records the exact snapshot and tile results.

## Decision

At z5–z8, collect candidate segment geometry at request time with `ST_Collect`, grouped by `waterway_class` and `NULLIF(BTRIM(name), '')`. Preserve the exact case and spelling of a nonblank source name, with surrounding whitespace removed. Unnamed segments of one class share a group. Distinct names or classes stay separate. Retain the buffered spatial query and exact MVT clipping envelope. Publish only `name` when present and `waterway_class`; aggregate features have no canonical MVT ID or segment-level navigation metadata. All canonical river, canal, and fairway geometry remains eligible.

At z9 and above, retain the existing individual canonical MVT features, IDs, attributes, geometry, and buffer. Below z5, return an empty tile. Keep the same Martin source and `waterway_segments` layer. Canonical PostGIS rows and source identity are unchanged.

## Alternatives considered

- **Navigation metadata filter:** rejected. Coverage is sparse, includes negative restrictions such as `boat_access=no`, and absent tagging means unknown rather than non-navigable.
- **Named-only filter:** rejected. It discards legitimate unnamed physical waterways and does not solve fragmentation.
- **Class-only aggregation:** rejected. Exact source names remain useful for low-zoom cartography, while class-only groups would erase them.
- **Simplification, generalized tables, or PMTiles:** deferred. First measure the effect of fixing feature fragmentation with the same Central FD A/B benchmark.

## Consequences

Presentation feature count should fall without removing physical waterway geometry or changing canonical storage. Named low-zoom labels remain possible. Aggregate features do not map one-to-one to OSM objects, so navigation properties are deliberately absent. `ST_Collect` preserves geometry vertices rather than reducing their complexity. The post-change exact-snapshot A/B will show whether any further geometry optimization is justified; none is authorized by the current evidence.
