# ADR 0004: Alembic for domain schema migrations

## Status

Accepted

## Context

The Phase 1 database initialization creates PostGIS and synthetic `demo_sites` once per new volume. Real domain tables need changes that can be applied to existing databases.

## Decision

Use Alembic for canonical application schema, beginning with `data_sources` and `railway_segments`. Keep the Phase 1 initialization fixture as a development bootstrap. OSM staging tables are disposable import output and are not Alembic managed.

## Consequences

Run `alembic upgrade head` before starting Martin with a newly published canonical table. CI applies migrations to a fresh PostGIS database. Future domain changes require new revisions.
