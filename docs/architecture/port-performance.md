# Port real-data validation benchmark

The manual [Port real-data benchmark](../../.github/workflows/port-benchmark.yml) first measures the existing civilian port filter on the fixed [Kaliningrad 2026-09-28 OSM extract](https://download.geofabrik.de/russia/kaliningrad-260928.osm.pbf). Kaliningrad is a bounded regional extract with coastal and inland tagging to inspect before considering larger runs. The fixed snapshot URL supports repeatable comparison; a compatible HTTPS `.osm.pbf` extract can be supplied manually. Normal CI uses synthetic fixtures and does not download Geofabrik data.

The report records the exact URL, filename, source metadata, retrieval time, PBF bytes and SHA-256, separate download/service/import/normalization timings, staging and canonical counts, canonical extent and relation sizes. It reports facility classes, original OSM node/way/relation types, attribute coverage, geometry and identity checks, and deterministic examples. Metadata absence, including `water_context`, is legitimate. Water context remains unknown unless explicit OSM tags support it.

For semantic review, the report selects up to ten rows per facility class ordered by OSM object type and ID, plus ten unnamed examples. This small audit sample can expose suspicious acceptance patterns for later investigation; it does not prove exhaustive correctness. It validates OSM coverage under the current filter, **not** completeness against an official port registry. No fuzzy node/polygon entity resolution exists, so several OSM objects may represent the same real-world port.

## Martin point tiles

The benchmark requests production `/ports/{z}/{x}/{y}` tiles at z5, z7, z9, z11 and z13. PostgreSQL selects spatially ordered first, median and last canonical point locations for representative tiles. At each zoom it also groups eligible canonical points into XYZ buckets and selects one highest-count density hotspot, breaking ties by x then y. At z5 only named ports qualify; at z7 and above all ports qualify. The benchmark requests a tile once when representative and hotspot roles coincide.

Candidate point count is a density proxy. The MVT function includes a 64/4096 buffer, so decoded feature count can differ. The report measures wire and decoded bytes, feature count and individual request duration, and verifies the `ports` layer, canonical IDs, Point geometry and named-only z5 output. The hotspot is one deterministic dense candidate, not an exhaustive worst-case search. Single-request timings are diagnostic, not production latency SLOs.

## Completed fixed-snapshot validation

The [Kaliningrad 2026-09-28 extract](https://download.geofabrik.de/russia/kaliningrad-260928.osm.pbf) produced 4 canonical ports: 3 `commercial_port` and 1 generic `port`. Three were named and one was unnamed. All reported geometry and identity quality error counts were zero.

The larger [Northwestern Federal District 2026-09-28 extract](https://download.geofabrik.de/russia/northwestern-fed-district-260928.osm.pbf) was 654,169,675 bytes with SHA-256 `730f31b79e0c1ccbae51afae389d25ae7d250378a1e870cb2df3a68ab84efa28`. Its 84 staging rows became 84 canonical rows. All reported geometry and identity quality error counts were zero.

| Facility class | Canonical rows | Share |
| --- | ---: | ---: |
| `commercial_port` | 48 | 57.14% |
| `cargo_terminal` | 11 | 13.10% |
| `fishing_port` | 2 | 2.38% |
| `port` | 23 | 27.38% |

The original OSM object types were 11 nodes, 56 ways, and 17 relations. These remain separate source objects even though every canonical facility is represented by a Point.

| Northwestern metadata | Rows | Share where supplied |
| --- | ---: | ---: |
| Named | 55 | 65.48% |
| `name_en` known | 21 | — |
| `water_context` known | 0 | — |
| `cargo` known | 11 | — |
| `operator` known | 16 | — |
| `website` known | 8 | — |
| `wikidata` known | 8 | — |
| `wikipedia` known | 7 | — |

The zero known `water_context` values are legitimate under the explicit-tag rule. No sea, river, or lake classification is inferred from geography.

| Northwestern density hotspot | MVT features | Wire bytes | Single-request seconds |
| --- | ---: | ---: | ---: |
| z5 | 29 | 1,244 | 0.002 |
| z7 | 35 | 1,166 | 0.001 |
| z9 | 35 | 1,173 | 0.002 |
| z11 | 13 | 406 | 0.001 |
| z13 | 8 | 524 | 0.001 |

These single-request times are diagnostics, not production SLOs. The measured point MVT payloads require no optimization at the tested regional scale: clustering, aggregation, generalized tables, PMTiles, and a tile cache are not justified.

The real-data samples support retaining the current explicit OSM filter. The 23 generic `port` objects in the Northwestern run remain a quality watchpoint, but these results are not evidence to narrow the filter now. Unnamed facilities are intentionally retained from z7 onward. Multiple OSM objects may describe parts of one real-world port; the benchmark does not resolve them. Official registry enrichment and entity resolution remain deferred. **Phase 2E is closed for the current OSM foundation and tested regional scale.**
