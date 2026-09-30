# Road performance baseline

No real-data road performance conclusion exists yet. Major roads begin with server-side semantic zoom filtering because the railway benchmarks showed that dense linear infrastructure can over-deliver at low zoom. The road MVT function selects candidates with the same `64 / 4096` query margin as its encoder buffer, preserving line fragments near tile edges.

The manual [Road real-data benchmark](../../.github/workflows/road-benchmark.yml) will establish the first baseline on an explicit OSM PBF. It samples production Martin tiles at z5, z7, z9, z11, and z13 and records import timing, canonical quality, relation sizes, and tile payloads. A sample request time is diagnostic, not a production latency SLO. PMTiles, generalized geometry, and simplification remain evidence-driven options; none is introduced in this phase.
