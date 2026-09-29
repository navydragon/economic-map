# ADR 0005: OSM railway ingestion via osm2pgsql Flex

## Status

Accepted

## Context

An OSM extract is a source representation; its tags and lifecycle should not own the application's railway schema.

## Decision

Use osm2pgsql 2.3.1 Flex Output in the pinned third-party `iboates/osm2pgsql:2.3.1` image to import accepted railway ways into `staging_osm.railway_lines`. A separate SQL normalization validates staging and transactionally upserts canonical `railway_segments`, preserving OSM way identity and source provenance. Each import recreates staging; canonical records remain governed by Alembic.

## Consequences

The pipeline accepts explicit local OSM PBF or XML paths and does not download data. Repeating normalization preserves canonical IDs, and replacing a source removes its stale ways. The staging import may need substantial memory and disk for country extracts; measure before changing this approach. Replication and generalization remain later decisions.
