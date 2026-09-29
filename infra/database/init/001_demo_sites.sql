CREATE EXTENSION IF NOT EXISTS postgis;

-- Synthetic development fixtures. These do not describe real facilities.
CREATE TABLE demo_sites (
    id integer PRIMARY KEY,
    name text NOT NULL,
    category text NOT NULL,
    value integer NOT NULL,
    geom geometry(Point, 4326) NOT NULL
);

CREATE INDEX demo_sites_geom_gix ON demo_sites USING GIST (geom);

INSERT INTO demo_sites (id, name, category, value, geom) VALUES
    (1, 'Synthetic Site A', 'demo', 10, ST_SetSRID(ST_MakePoint(37.6, 55.8), 4326)),
    (2, 'Synthetic Site B', 'demo', 20, ST_SetSRID(ST_MakePoint(60.6, 56.8), 4326)),
    (3, 'Synthetic Site C', 'demo', 30, ST_SetSRID(ST_MakePoint(92.9, 56.0), 4326)),
    (4, 'Synthetic Site D', 'demo', 40, ST_SetSRID(ST_MakePoint(129.7, 62.0), 4326)),
    (5, 'Synthetic Site E', 'demo', 50, ST_SetSRID(ST_MakePoint(131.9, 43.1), 4326));

COMMENT ON TABLE demo_sites IS '{"description":"Synthetic development points; not real facilities or infrastructure."}';
