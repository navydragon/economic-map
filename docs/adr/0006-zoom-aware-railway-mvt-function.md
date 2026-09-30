# ADR 0006: Zoom-aware railway MVT function

## Status

Accepted

## Context

The Central Federal District benchmark imported 51,712 canonical railway segments. A sampled z5 tile sent 12,341 features (~144 KB gzip, ~335 ms) and a sampled z7 tile sent 8,110 (~114 KB gzip, ~232 ms). Many service tracks were transferred even though MapLibre hides them below z11.

## Decision

Keep `public.railway_segments` as the canonical PostGIS model. Deliver railway MVT through a PostgreSQL function published as an explicit Martin Function Source under the existing `railway_segments` source ID. The function returns no railways below z5, excludes rows with non-null `service` at z5–z10, and includes all railway rows at z11 and above. It uses the existing spatial index for candidate selection and preserves the public MVT layer contract.

## Consequences

Fewer unnecessary low-zoom tile features can be sent while retaining dynamic tiles and canonical PostGIS storage. This addresses the measured over-delivery before adopting PMTiles or generalized geometry. Tile generation now includes custom SQL, and frontend and backend zoom visibility rules must stay aligned. This decision applies to railway delivery; other domains can choose their own source strategy.
