# Port real-data validation benchmark

The manual [Port real-data benchmark](../../.github/workflows/port-benchmark.yml) first measures the existing civilian port filter on the fixed [Kaliningrad 2026-09-28 OSM extract](https://download.geofabrik.de/russia/kaliningrad-260928.osm.pbf). Kaliningrad is a bounded regional extract with coastal and inland tagging to inspect before considering larger runs. The fixed snapshot URL supports repeatable comparison; a compatible HTTPS `.osm.pbf` extract can be supplied manually. Normal CI uses synthetic fixtures and does not download Geofabrik data.

The report records the exact URL, filename, source metadata, retrieval time, PBF bytes and SHA-256, separate download/service/import/normalization timings, staging and canonical counts, canonical extent and relation sizes. It reports facility classes, original OSM node/way/relation types, attribute coverage, geometry and identity checks, and deterministic examples. Metadata absence, including `water_context`, is legitimate. Water context remains unknown unless explicit OSM tags support it.

For semantic review, the report selects up to ten rows per facility class ordered by OSM object type and ID, plus ten unnamed examples. This small audit sample can expose suspicious acceptance patterns for later investigation; it does not prove exhaustive correctness. It validates OSM coverage under the current filter, **not** completeness against an official port registry. No fuzzy node/polygon entity resolution exists, so several OSM objects may represent the same real-world port.

## Martin point tiles

The benchmark requests production `/ports/{z}/{x}/{y}` tiles at z5, z7, z9, z11 and z13. PostgreSQL selects spatially ordered first, median and last canonical point locations for representative tiles. At each zoom it also groups eligible canonical points into XYZ buckets and selects one highest-count density hotspot, breaking ties by x then y. At z5 only named ports qualify; at z7 and above all ports qualify. The benchmark requests a tile once when representative and hotspot roles coincide.

Candidate point count is a density proxy. The MVT function includes a 64/4096 buffer, so decoded feature count can differ. The report measures wire and decoded bytes, feature count and individual request duration, and verifies the `ports` layer, canonical IDs, Point geometry and named-only z5 output. The hotspot is one deterministic dense candidate, not an exhaustive worst-case search. Single-request timings are diagnostic, not production latency SLOs.

No real-data results are recorded before the first manual run. Production filtering and tile behavior remain subject to measured evidence from that artifact.
