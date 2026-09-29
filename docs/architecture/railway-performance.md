# Railway performance baseline

The normal push/PR CI uses only the synthetic OSM fixture. The separate [Railway real-data benchmark](../../.github/workflows/railway-benchmark.yml) runs only through **Actions → Railway real-data benchmark → Run workflow**. Its default input is the small [Geofabrik Kaliningrad OSM PBF](https://download.geofabrik.de/russia/kaliningrad.html); another HTTPS `.osm.pbf` URL and source metadata can be supplied manually. Leave `snapshot_at` empty unless the source reports an exact timestamp. The PBF stays in temporary runner storage and is not uploaded.

The workflow writes a Markdown GitHub Step Summary and uploads `benchmark.json` and `benchmark.md`. It measures download size, SHA-256 and duration; PostGIS startup; Alembic migration; osm2pgsql import; canonical normalization; Martin startup; staging and canonical row counts; table and index sizes; railway attributes and geometry quality; extent; and representative Martin MVT samples at z5, z7, z9, z11 and z13. Sample points come from the imported railway lines. MVT samples report HTTP status, transferred bytes, decoded payload bytes and feature counts. A 204/empty tile can be valid. The workflow fails if canonical geometry has an invalid shape, unexpected type, wrong SRID, or is empty.

To measure an already imported local database with Martin running, from `apps/api` run:

```powershell
uv run --env-file ../../.env python ../../pipelines/railways/benchmark.py --source-slug osm-russia --martin-url http://127.0.0.1:3000
```

The script writes ignored `benchmark.json` and `benchmark.md` in the current directory. Add `--input-path` when the original PBF is available to include its size and SHA-256. Add `--timings-json` with the importer's `--timings-json` output to include measured import and normalization durations. Table sizes cover all sources in the table; row distributions and extent cover the selected slug. Staging rows describe the most recent railway import and should be interpreted accordingly.

No optimization strategy is selected yet. **PostGIS/Martin vs PMTiles/generalized layers will be decided from measured full/representative dataset behavior, not assumed in advance.** Compare import and normalization time, table and spatial-index growth, tile byte sizes and feature density across zoom levels, and Martin response time on representative and eventually full-country extracts before changing delivery architecture.
