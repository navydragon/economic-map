# ADR 0002: PostGIS as canonical spatial store

## Status

Accepted

## Context

Both tile delivery and application queries need a shared spatial database.

## Decision

Store canonical geometry in PostgreSQL with PostGIS. Phase 1 stores synthetic points in SRID 4326.

## Consequences

Martin and FastAPI use the same database. The bootstrap SQL runs only for a new local volume; future changes require migrations.
