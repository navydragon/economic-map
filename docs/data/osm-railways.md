# OSM railway ingestion

This pipeline accepts a local `.osm.pbf` extract (or a tiny `.osm` XML fixture) from any compatible OSM provider. [Geofabrik's Russia page](https://download.geofabrik.de/russia.html) is one possible source. No download occurs during ingestion or CI. Keep downloaded extracts outside Git; `*.osm.pbf` and `data/raw/` are ignored.

OpenStreetMap data is © OpenStreetMap contributors and licensed under the [Open Database License (ODbL) 1.0](https://www.openstreetmap.org/copyright). The map's railway vector source displays the required attribution. `data_sources` records the provider URL, publisher, license, retrieval time, and optional source snapshot time. Enter the actual source URL and retrieval time for the file you use.

## Import

Start PostGIS, then apply the canonical migration from `apps/api`:

```powershell
docker compose up -d --wait postgres
cd apps/api
uv sync --locked --group dev
uv run --env-file ../../.env alembic upgrade head
```

Import an already downloaded Geofabrik extract. Replace the path, URL, and dates with the details of your file. The slug identifies a dataset lineage: use the same slug to replace it with a newer snapshot, or a different slug for an independent regional dataset. Import one extract at a time because all runs share the disposable `staging_osm` schema. Avoid overlapping regional slugs unless duplicate coverage is intentional.

```powershell
uv run --env-file ../../.env python ../../pipelines/railways/import_railways.py import --input C:\data\russia-latest.osm.pbf --source-slug osm-russia --source-name "OSM Russia extract" --source-url https://download.geofabrik.de/russia.html --publisher "OpenStreetMap contributors" --license "ODbL 1.0" --snapshot-at 2026-09-28T00:00:00+00:00 --retrieved-at 2026-09-29T00:00:00+00:00
```

Use ISO 8601 timestamps with a timezone. `--snapshot-at` may be omitted if the source did not report one. The importer uses `iboates/osm2pgsql:2.3.1`, a version-pinned image maintained by a third party and listed by the [osm2pgsql installation guide](https://osm2pgsql.org/doc/install/docker.html). Docker and Docker Compose are required. Run the command from `apps/api` so `uv` uses its locked Python environment. Set `POSTGRES_PASSWORD` in `.env` as in `.env.example`.

The import first recreates `staging_osm`, then osm2pgsql Flex writes `staging_osm.railway_lines` in SRID 4326. It accepts ways with `railway=rail` or `railway=narrow_gauge`; it ignores tram, subway, light rail, monorail, funicular, abandoned, razed, disused, construction, and non-way objects such as stations, platforms, signals, switches, and route relations. A `railway=rail` way marked `disused=yes`, `abandoned=yes`, `razed=yes`, `construction=yes`, or `proposed=yes` is also excluded. `service=yard|siding|spur|crossover` remains in the data but renders only at close zoom. Known tags (`name`, `ref`, `usage`, `service`, `operator`, `electrified`, `gauge`, `tracks`, `maxspeed`, `bridge`, `tunnel`) are copied as text without inferring units or filling missing values.

The normalizer rejects empty or invalid staging, then performs source metadata upsert, railway upsert, and removal of stale rows in one transaction. The unique `(source_id, source_object_type, source_object_id)` constraint preserves OSM way identity without using it as the application's primary key. Repeating the same import or normalizing the same staging table again does not add rows or change canonical IDs. To rerun only normalization, replace `import --input ...` with `normalize` and keep the same source metadata options. If osm2pgsql fails, canonical rows remain as they were; staging can be reset with `docker compose exec postgres psql -U russia_map -d russia_map -c "DROP SCHEMA IF EXISTS staging_osm CASCADE"`, or simply by rerunning the import. Do not reset the database volume to update domain schema.

`public.demo_sites` remains the Phase 1 development fixture created by Postgres initialization. Alembic owns `public.data_sources` and `public.railway_segments`. Osm2pgsql owns only the disposable staging schema. Martin publishes only selected fields from the canonical table.

## Inspect counts and sizes

Run these SQL statements through `docker compose exec postgres psql -U russia_map -d russia_map`:

```sql
SELECT slug, snapshot_at, retrieved_at FROM public.data_sources ORDER BY slug;
SELECT count(*) AS staging_ways FROM staging_osm.railway_lines;
SELECT source_id, railway_type, count(*) FROM public.railway_segments GROUP BY 1, 2 ORDER BY 1, 2;
SELECT pg_size_pretty(pg_total_relation_size('public.railway_segments')) AS table_with_indexes,
       pg_size_pretty(pg_relation_size('public.railway_segments_geom_gix')) AS spatial_index;
```

After Martin starts, record tile sizes at representative zooms with a local command (adjust tile coordinates to your extract):

```powershell
python -c "import urllib.request; u='http://127.0.0.1:3000/railway_segments/8/154/80'; print(len(urllib.request.urlopen(u).read()), 'bytes')"
```

Tile sizes and import capacity should be measured on real extracts before deciding on low zoom generalization. The synthetic fixture provides functional coverage, not a performance benchmark.
