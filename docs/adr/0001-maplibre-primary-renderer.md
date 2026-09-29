# ADR 0001: MapLibre as primary renderer

## Status

Accepted

## Context

The first milestone needs a self-hostable 2D map that consumes vector tiles.

## Decision

Use MapLibre GL JS in the React application as the primary renderer.

## Consequences

The local map needs no proprietary basemap or token. Advanced 3D can be considered later when a concrete need appears.
