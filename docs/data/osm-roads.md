# OSM major road ingestion

This milestone models **major civilian road infrastructure**, not the complete street network. It accepts a local OpenStreetMap-compatible `.osm.pbf` extract or a small `.osm` fixture. [Geofabrik](https://download.geofabrik.de/russia.html) is one supported provider, not an architectural dependency. Normal imports do not download data; the separate manual benchmark workflow does. OpenStreetMap data is © OpenStreetMap contributors under [ODbL 1.0](https://www.openstreetmap.org/copyright), and the map shows that attribution.

The osm2pgsql Flex importer accepts only `motorway`, `trunk`, `primary`, `secondary`, and `tertiary`, plus each class's `_link` variant. It rejects `area=yes` ways. Residential, unclassified, living streets, service, track, pedestrian, footway, path, cycleway, steps, raceway, busway, construction, proposed, and all other highway classes are excluded. Relations, routing restrictions, ferry routes, and traffic data are outside this domain. Link variants become their base `road_class` with `is_link=true`; non-link variants use `is_link=false`. Values such as lanes, maxspeed, oneway, toll, bridge, and tunnel remain text; unknown tags remain NULL.

## Import a local extract

Start PostGIS from the repository root, then migrate and import from `apps/api`, with Docker Compose and the locked Python environment available:

```powershell
docker compose up -d --wait postgres
cd apps/api
uv sync --locked --group dev
uv run --env-file ../../.env alembic upgrade head
uv run --env-file ../../.env python ../../pipelines/roads/import_roads.py import --input C:\data\kaliningrad-latest.osm.pbf --source-slug osm-kaliningrad-roads --source-name "OSM Kaliningrad major roads" --source-url https://download.geofabrik.de/russia/kaliningrad.html --retrieved-at 2026-09-30T00:00:00+00:00
cd ../..
docker compose up -d --wait martin
```

Use the input file's actual provider URL and retrieval time. Supply `--snapshot-at` only when the provider reports an exact source timestamp. The importer uses the repository's pinned `iboates/osm2pgsql:2.3.1` image and recreates only `staging_osm_roads`; it does not drop railway or unrelated staging. Flex writes `staging_osm_roads.road_lines` in SRID 4326. Transactional normalization validates staging, upserts metadata in the existing `public.data_sources`, upserts `public.road_segments` by `(source_id, source_object_type, source_object_id)`, and removes disappeared ways for that source. Repeating normalization preserves canonical IDs and does not create duplicates.

A source slug identifies the **current active dataset** for one logical road source. Reimporting a changed extract with the same slug replaces that slug's current coverage; removed ways disappear, and previous metadata is not retained as history. Different slugs containing overlapping extracts may produce duplicate spatial roads. Cross-source geometry deduplication is not part of this milestone. Use distinct road and railway slugs because both domains share `data_sources`.

For a first real-data baseline, run the manual [Road real-data benchmark](../../.github/workflows/road-benchmark.yml). It downloads a PBF into temporary runner storage and uploads only reports.
