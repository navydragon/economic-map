# OSM waterway centerlines

The Phase 2F foundation imports public OSM `waterway=river|canal|fairway` **ways** as physical centerline or navigation-axis segments. The Flex filter at [waterways.lua](../../pipelines/waterways/waterways.lua) is the admission rule. Each qualifying way remains a separate canonical segment. Adjacent ways are not merged, named rivers are not assembled from relations, and polygon footprints or centerlines derived from `natural=water` are not used.

This domain is named **waterways**, not navigable waterways. A river or canal does **not** imply commercial navigation. `waterway=fairway` retains its explicit navigation-oriented source class. Source values for `boat`, `motorboat`, `ship`, `oneway:boat`, `CEMT`, `usage`, `service`, `width`, `operator`, `ref`, `wikidata`, and `wikipedia` are retained when present. CEMT is stored as source text without calculating a class or ranking. Recognized `intermittent` and `tidal` yes/no values become nullable booleans; missing or unrecognized values stay NULL. Missing navigation tags are unknown, not a negative navigation assertion. No navigation score or geographic inference is made.

The filter excludes streams, ditches, drains, tidal channels, pressurised lines, flowlines, links, docks, locks, dams, weirs, rapids, waterfalls, boatyards, water polygons, riverbank polygons, reservoirs, lakes, ferry routes, route relations, seamark tracks, and navigation aids. It also excludes accepted-class ways tagged as abandoned, disused, razed, demolished, proposed, or construction through lifecycle flags or `*:waterway` tags. OpenStreetMap data is © OpenStreetMap contributors under ODbL 1.0; the MapLibre vector source carries attribution.

## Import and canonical identity

From `apps/api`, after PostGIS and `alembic upgrade head` are running, import an already downloaded local `.osm.pbf` or synthetic `.osm` fixture:

```powershell
uv run --env-file ../../.env python ../../pipelines/waterways/import_waterways.py import --input C:\data\waterways.osm.pbf --source-slug osm-waterways-region --source-name "OSM regional waterway centerlines" --source-url https://example.org/waterways.osm.pbf --retrieved-at 2026-10-02T00:00:00+00:00
```

Use the actual source URL and retrieval time; supply `--snapshot-at` only when reported by the provider. The importer never downloads data. It recreates only `staging_osm_waterways` using the pinned osm2pgsql Flex image, then validates LineString/SRID 4326 geometry and unique way IDs. A transaction upserts `public.data_sources`, updates or inserts `public.waterway_segments`, and deletes missing ways for that source slug. Retained OSM ways preserve their canonical IDs. Repeating normalization is idempotent. Different source slugs may overlap; there is no cross-source deduplication or topology reconstruction.

The canonical table stores a generated ID, OSM way identity, source provenance, class and selected source metadata, active status, and valid nonempty `LineString` geometry. It is owned by Alembic. Staging remains disposable and does not affect railway, road, or port staging.

## Dynamic tiles and limits

Martin explicitly exposes `/waterway_segments/{z}/{x}/{y}` with source layer `waterway_segments`. The function returns empty MVT bytes below z5; Martin may answer 404 below its advertised minzoom. From z5 onward it returns every canonical segment with its canonical ID and selected public properties. Indexed geometry selection includes the 64/4096 query margin matching the encoder buffer. MapLibre styles river, canal, and fairway as restrained lines without presenting all waterways as navigable.

This first slice uses synthetic CI only. There is no real-data benchmark yet, no relation-based river assembly, no navigation structures or official registry enrichment, and no generalization or tile cache. A separate fixed-snapshot benchmark must measure low-zoom density and payloads before optimization choices.
