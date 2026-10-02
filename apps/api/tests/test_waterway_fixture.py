"""Keep the synthetic OSM XML ordered for osm2pgsql's streaming reader."""

from pathlib import Path
import xml.etree.ElementTree as ET


def test_waterway_fixture_osm_object_order() -> None:
    path = Path(__file__).resolve().parents[3] / "data/fixtures/osm/waterways.osm"
    root = ET.parse(path).getroot()
    nodes = [item for item in root if item.tag == "node"]
    ways = [item for item in root if item.tag == "way"]
    assert list(root) == nodes + ways
    assert [int(item.attrib["id"]) for item in nodes] == sorted(
        int(item.attrib["id"]) for item in nodes)
    assert [int(item.attrib["id"]) for item in ways] == sorted(
        int(item.attrib["id"]) for item in ways)
