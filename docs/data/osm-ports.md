# OSM civilian ports and cargo terminals

This Phase 2E foundation maps public civilian and economic port facilities as points. It uses an explicit local OSM `.osm.pbf` extract or the synthetic `.osm` CI fixture. Normal CI does not download data. The import uses the pinned osm2pgsql Flex image and only recreates `staging_osm_ports`; Alembic owns `public.ports`. OpenStreetMap data is © OpenStreetMap contributors under ODbL 1.0, and the frontend shows attribution.

## Exact candidate rules

The [Flex filter](../../pipelines/ports/ports.lua) is the single source of ingestion decisions. It accepts an object only when it carries `industrial=port`, `landuse=port`, `port=cargo|fishing`, `harbour=yes|port|commercial|cargo|fishing`, or `seamark:type=harbour`. Commercial areas follow the [OSM `industrial=port` convention](https://wiki.openstreetmap.org/wiki/Tag:industrial%3Dport); `landuse=port` is also documented for commercial port areas. OSM documents `port=cargo` and `port=fishing` as terminal and fishing categories, and [seamark harbour categories](https://wiki.openstreetmap.org/wiki/Key:seamark:harbour:category) distinguish cargo/fishing from ferry/marina use. This intentionally conservative filter may omit ports with other tagging.

Class priority is `cargo_terminal` for `port=cargo`, `harbour=cargo`, or seamark harbour category `cargo`, then `fishing_port` for `port=fishing`, `harbour=fishing`, or category `fishing`, then `commercial_port` for `industrial=port`, `landuse=port`, or `harbour=commercial`, then generic `port` for the remaining explicit harbour objects. A raw `cargo=*` value is retained as text only after an independent port candidate tag qualifies; it does not create a port by itself.

Objects tagged `leisure=marina`, military/naval, harbour category `marina|marina_no_facilities|naval`, or lifecycle `abandoned|disused|razed|demolished|construction|proposed` are excluded. A ferry-only `amenity=ferry_terminal` or harbour category `ferry` is excluded. Generic `man_made=pier`, docks, warehouses, berths, cranes, and nearby industrial or water geometry are not candidate evidence. A pier or ferry-tagged object can enter only if the same object has a qualifying commercial, cargo, or fishing port tag and is not otherwise excluded. The filter accepts nodes, closed ways with polygon geometry, and `type=multipolygon` relations. Open ways and other relation types do not qualify.

`water_context` is nullable. Only explicit `port:type=seaport` becomes `sea`. `port:type=inland_port` covers both river and lake ports, so it remains NULL. No sea/river/lake value is guessed from coordinates, name, region, or nearby water.

## Canonical identity and import

`public.ports` has a stable generated ID, a `public.data_sources` foreign key, the original OSM `node|way|relation` type and numeric ID, an explicit facility class, source attributes, active status, and Point geometry in SRID 4326. Node points remain unchanged. Polygon and multipolygon facilities use deterministic `ST_PointOnSurface` interior representatives. The canonical point does not retain the source footprint; staging is disposable.

One source slug represents its current active coverage. Normalization transactionally upserts source metadata and port rows, preserves IDs for retained OSM objects, and removes objects missing from that source's latest staging import. Importing the same staging again is idempotent. Different source slugs may overlap; a node and polygon representing the same real-world port remain distinct OSM objects. There is no fuzzy cross-object or cross-source entity resolution.

From `apps/api` with PostGIS running and Alembic upgraded to head:

```powershell
uv run --env-file ../../.env python ../../pipelines/ports/import_ports.py import --input C:\data\ports.osm.pbf --source-slug osm-ports-region --source-name "OSM regional ports" --source-url https://example.org/ports.osm.pbf --retrieved-at 2026-10-01T00:00:00+00:00
```

Supply the actual local file, provider URL, and retrieval time. Use `--snapshot-at` only for a source-reported timestamp. The importer drops and recreates only `staging_osm_ports`; it does not touch road or railway staging and never downloads the input itself.

Martin explicitly publishes `/ports/{z}/{x}/{y}` with source-layer `ports`. The PostgreSQL function returns an empty MVT below z5; Martin may reject requests below its TileJSON minzoom. At z5–z6, only named facilities appear. From z7, all canonical ports appear. The tile carries the canonical feature ID plus `name`, `facility_class`, `water_context`, `cargo`, `operator`, `access`, and `status` where values are known. Point candidates use the indexed geometry with the same 64/4096 query margin as the MVT buffer. No throughput, commodity taxonomy, official registry matching, or shipping route data is added here.
