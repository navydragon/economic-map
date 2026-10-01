"""Compare port hotspot SQL against independently bucketed synthetic points."""

from collections import Counter
import importlib.util
from pathlib import Path
import sys

from sqlalchemy import text

from app.database import get_engine


PIPELINE = Path(__file__).resolve().parents[3] / "pipelines" / "ports"
sys.path.insert(0, str(PIPELINE))
spec = importlib.util.spec_from_file_location("port_benchmark_integration", PIPELINE / "benchmark.py")
assert spec is not None and spec.loader is not None
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_density_hotspot_matches_fixture_point_buckets() -> None:
    with get_engine().connect() as connection:
        rows = connection.execute(text("""
            SELECT p.name, ST_X(p.geom) AS lon, ST_Y(p.geom) AS lat
            FROM public.ports AS p
            JOIN public.data_sources AS source ON source.id = p.source_id
            WHERE source.slug = 'ci-synthetic-ports'
        """)).all()
        source_id = connection.scalar(text("""
            SELECT id FROM public.data_sources WHERE slug = 'ci-synthetic-ports'
        """))
        assert len(rows) == 8 and source_id is not None
        for zoom in benchmark.ZOOMS:
            counts = Counter(
                benchmark.tile_coordinates(row.lon, row.lat, zoom)
                for row in rows if benchmark.eligible_at_zoom(zoom, row.name)
            )
            (x, y), count = min(counts.items(), key=lambda item: (
                -item[1], item[0][0], item[0][1]))
            assert benchmark.density_hotspot(connection, source_id, zoom) == {
                "x": x, "y": y, "candidate_point_count": count,
            }
