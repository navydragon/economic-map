"""Aggregate low-zoom waterway presentation geometry by class and name.

Revision ID: 0008_waterway_mvt_aggregation
Revises: 0007_waterway_domain
"""

from alembic import op


revision = "0008_waterway_mvt_aggregation"
down_revision = "0007_waterway_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
        CREATE OR REPLACE FUNCTION public.waterway_segments_mvt(z integer, x integer, y integer)
        RETURNS bytea
        LANGUAGE plpgsql STABLE STRICT PARALLEL SAFE
        AS $function$
        DECLARE
            tile_bounds geometry;
            query_bounds geometry;
            tile_bytes bytea;
        BEGIN
            IF z < 5 THEN
                RETURN '\x'::bytea;
            END IF;

            tile_bounds := ST_TileEnvelope(z, x, y);
            query_bounds := ST_TileEnvelope(z, x, y, margin => 64.0 / 4096.0);
            IF z < 9 THEN
                SELECT ST_AsMVT(tile, 'waterway_segments', 4096, 'geom')
                INTO tile_bytes
                FROM (
                    SELECT w.waterway_class, NULLIF(BTRIM(w.name), '') AS name,
                        ST_AsMVTGeom(
                            ST_Collect(ST_Transform(w.geom, 3857)),
                            tile_bounds, 4096, 64, true
                        ) AS geom
                    FROM public.waterway_segments AS w
                    WHERE w.geom && ST_Transform(query_bounds, 4326)
                    GROUP BY w.waterway_class, NULLIF(BTRIM(w.name), '')
                ) AS tile
                WHERE tile.geom IS NOT NULL;

                RETURN COALESCE(tile_bytes, '\x'::bytea);
            END IF;

            SELECT ST_AsMVT(tile, 'waterway_segments', 4096, 'geom', 'id')
            INTO tile_bytes
            FROM (
                SELECT w.id, w.name, w.ref, w.waterway_class,
                    w.boat_access, w.motorboat_access, w.ship_access,
                    w.oneway_boat, w.cemt_class, w.usage, w.intermittent, w.tidal,
                    ST_AsMVTGeom(ST_Transform(w.geom, 3857),
                        tile_bounds, 4096, 64, true) AS geom
                FROM public.waterway_segments AS w
                WHERE w.geom && ST_Transform(query_bounds, 4326)
            ) AS tile
            WHERE tile.geom IS NOT NULL;

            RETURN COALESCE(tile_bytes, '\x'::bytea);
        END;
        $function$
    """)
    op.execute("""
        COMMENT ON FUNCTION public.waterway_segments_mvt(integer, integer, integer) IS
        '{
          "description": "OSM river, canal, and fairway centerlines; z5-z8 presentation geometry grouped by class and trimmed exact name without canonical IDs or navigation details; z9+ individual canonical segments with IDs and detailed attributes; navigation is not inferred",
          "minzoom": 5,
          "maxzoom": 14,
          "attribution": "© OpenStreetMap contributors",
          "vector_layers": [{
            "id": "waterway_segments",
            "fields": {
              "name": "String", "ref": "String", "waterway_class": "String",
              "boat_access": "String", "motorboat_access": "String",
              "ship_access": "String", "oneway_boat": "String",
              "cemt_class": "String", "usage": "String",
              "intermittent": "Boolean", "tidal": "Boolean"
            }
          }]
        }'
    """)


def downgrade() -> None:
    op.execute(r"""
        CREATE OR REPLACE FUNCTION public.waterway_segments_mvt(z integer, x integer, y integer)
        RETURNS bytea
        LANGUAGE plpgsql STABLE STRICT PARALLEL SAFE
        AS $function$
        DECLARE
            tile_bounds geometry;
            query_bounds geometry;
            tile_bytes bytea;
        BEGIN
            IF z < 5 THEN
                RETURN '\x'::bytea;
            END IF;

            tile_bounds := ST_TileEnvelope(z, x, y);
            query_bounds := ST_TileEnvelope(z, x, y, margin => 64.0 / 4096.0);
            SELECT ST_AsMVT(tile, 'waterway_segments', 4096, 'geom', 'id')
            INTO tile_bytes
            FROM (
                SELECT w.id, w.name, w.ref, w.waterway_class,
                    w.boat_access, w.motorboat_access, w.ship_access,
                    w.oneway_boat, w.cemt_class, w.usage, w.intermittent, w.tidal,
                    ST_AsMVTGeom(ST_Transform(w.geom, 3857),
                        tile_bounds, 4096, 64, true) AS geom
                FROM public.waterway_segments AS w
                WHERE w.geom && ST_Transform(query_bounds, 4326)
            ) AS tile
            WHERE tile.geom IS NOT NULL;

            RETURN COALESCE(tile_bytes, '\x'::bytea);
        END;
        $function$
    """)
    op.execute("""
        COMMENT ON FUNCTION public.waterway_segments_mvt(integer, integer, integer) IS
        '{
          "description": "OSM river, canal, and fairway centerline ways; navigation is not inferred",
          "minzoom": 5,
          "maxzoom": 14,
          "attribution": "© OpenStreetMap contributors",
          "vector_layers": [{
            "id": "waterway_segments",
            "fields": {
              "name": "String", "ref": "String", "waterway_class": "String",
              "boat_access": "String", "motorboat_access": "String",
              "ship_access": "String", "oneway_boat": "String",
              "cemt_class": "String", "usage": "String",
              "intermittent": "Boolean", "tidal": "Boolean"
            }
          }]
        }'
    """)
