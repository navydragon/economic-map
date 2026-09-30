# ADR 0007: Major roads with zoom-aware MVT

## Status

Accepted

## Context

Major roads are the second real transport domain. Railway benchmarks showed substantial low-zoom over-delivery from dense linear data, and the railway tile-edge regression showed why MVT buffer margins must be included in candidate queries.

## Decision

Canonicalize public OSM `motorway` through `tertiary` ways and their `_link` variants in PostGIS. Normalize links into a base `road_class` plus `is_link`. Import through road-specific osm2pgsql Flex staging and reuse `data_sources` provenance. Publish roads from the start through a zoom-aware PostgreSQL MVT function with a buffer-aware candidate envelope, explicitly exposed by Martin.

## Consequences

The canonical model remains queryable and stable while low-zoom tiles omit road classes and links that the map does not display. Custom tile SQL and frontend zoom styling must stay aligned. The first manual benchmark will determine whether further optimization is justified. This decision does not require future domains to use function sources.
