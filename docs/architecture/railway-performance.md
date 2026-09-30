# Railway performance baseline

The normal push/PR CI uses only the synthetic OSM fixture. The separate [Railway real-data benchmark](../../.github/workflows/railway-benchmark.yml) runs only through **Actions → Railway real-data benchmark → Run workflow**. Its default input is the small [Geofabrik Kaliningrad OSM PBF](https://download.geofabrik.de/russia/kaliningrad.html); another HTTPS `.osm.pbf` URL and source metadata can be supplied manually. Leave `snapshot_at` empty unless the source reports an exact timestamp. The PBF stays in temporary runner storage and is not uploaded.

The workflow writes a Markdown GitHub Step Summary and uploads `benchmark.json` and `benchmark.md`. It measures download size, SHA-256 and duration; PostGIS startup; Alembic migration; osm2pgsql import; canonical normalization; Martin startup; staging and canonical row counts; table and index sizes; railway attributes and geometry quality; extent; and representative Martin MVT samples at z5, z7, z9, z11 and z13. Sample points come from the imported railway lines. MVT samples report HTTP status, transferred bytes, decoded payload bytes and feature counts. A 204/empty tile can be valid. The workflow fails if canonical geometry has an invalid shape, unexpected type, wrong SRID, or is empty.

To measure an already imported local database with Martin running, from `apps/api` run:

```powershell
uv run --env-file ../../.env python ../../pipelines/railways/benchmark.py --source-slug osm-russia --martin-url http://127.0.0.1:3000
```

The script writes ignored `benchmark.json` and `benchmark.md` in the current directory. Add `--input-path` when the original PBF is available to include its size and SHA-256. Add `--timings-json` with the importer's `--timings-json` output to include measured import and normalization durations. Table sizes cover all sources in the table; row distributions and extent cover the selected slug. Staging rows describe the most recent railway import and should be interpreted accordingly.

## Phase 2C: zoom-aware delivery

Three real-data runs established the initial scale: Kaliningrad (~29 MB PBF, 1,796 canonical segments), North Caucasus Federal District (~129 MB, 6,182 segments), and Central Federal District (~879 MB, 51,712 segments). In the Central run, a hot sampled z5 tile contained 12,341 features, transferred ~144 KB gzip, and took ~335 ms. A hot sampled z7 tile contained 8,110 features, transferred ~114 KB gzip, and took ~232 ms. These are **before** zoom-aware delivery measurements, not improvement claims.

Many of these features are service tracks that MapLibre hides below z11. Phase 2C moves that visibility rule into a PostgreSQL MVT function: no railway content below z5, non-service rows at z5–z10, and all canonical rows from z11. Martin publishes the function under the existing `railway_segments` source ID, so the manual benchmark samples the production tile path unchanged at z5, z7, z9, z11, and z13. The Central benchmark should be rerun with the same input and parameters to measure the effect. PMTiles and generalized geometries remain possible future options if subsequent evidence calls for them.
