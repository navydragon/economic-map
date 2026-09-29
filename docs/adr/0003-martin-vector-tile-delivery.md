# ADR 0003: Martin for vector tile delivery

## Status

Accepted

## Context

The map should consume geodata as MVT without routing tile requests through the application API.

## Decision

Martin serves an explicitly configured PostGIS table as MVT to MapLibre.

## Consequences

FastAPI remains focused on structured queries. The tile source can grow independently of the API, and the published table list remains explicit.
