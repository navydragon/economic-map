import importlib.util
from pathlib import Path
import sys


ROAD_PIPELINE = Path(__file__).resolve().parents[3] / "pipelines" / "roads"
sys.path.insert(0, str(ROAD_PIPELINE))
spec = importlib.util.spec_from_file_location("road_benchmark", ROAD_PIPELINE / "benchmark.py")
assert spec is not None and spec.loader is not None
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_road_tile_samples_use_production_source_and_zooms(monkeypatch) -> None:
    requested_urls = []

    class Response:
        status_code = 200
        content = b"tile"
        num_bytes_downloaded = 2
        headers = {"content-encoding": "gzip"}

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def get(self, url):
            requested_urls.append(url)
            return Response()

    monkeypatch.setattr(benchmark.httpx, "Client", lambda **_: Client())
    monkeypatch.setattr(benchmark.mapbox_vector_tile, "decode", lambda _: {
        "road_segments": {"features": [{}, {}]}
    })

    samples = benchmark.sample_tiles("http://localhost:3000", [(37.6, 55.72)])
    assert [sample["z"] for sample in samples] == [5, 7, 9, 11, 13]
    assert all("/road_segments/" in url for url in requested_urls)
    assert all(sample["feature_count"] == 2 and sample["decode_error"] is None
               for sample in samples)
    assert all(sample["wire_bytes"] == 2 and sample["decoded_payload_bytes"] == 4
               for sample in samples)
