# Repository guidance

- `README.md` is the product and architecture source of truth. Read relevant ADRs before changing architecture.
- MapLibre is the primary renderer; Cesium is optional and is not the default.
- PostGIS is canonical spatial storage. Use migrations for future schema changes.
- Prefer Martin/MVT or PMTiles for large geodata. Do not ship giant production GeoJSON files.
- Preserve source provenance for real datasets; the Phase 1 points are synthetic fixtures only.
- Run relevant tests, lint, and type checks before declaring work complete.
- Introduce major frameworks only with an architectural justification.
