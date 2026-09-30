"""Aggregate low-zoom road presentation geometry by class.

Revision ID: 0005_road_mvt_aggregation
Revises: 0004_road_domain
"""

from alembic import op


revision = "0005_road_mvt_aggregation"
down_revision = "0004_road_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
        CREATE OR REPLACE FUNCTION public.road_segments_mvt(z integer, x integer, y integer)
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
            IF z < 10 THEN
                SELECT ST_AsMVT(tile, 'road_segments', 4096, 'geom')
                INTO tile_bytes
                FROM (
                    SELECT r.road_class, false AS is_link,
                        ST_AsMVTGeom(
                            ST_Collect(ST_Transform(r.geom, 3857)),
                            tile_bounds, 4096, 64, true
                        ) AS geom
                    FROM public.road_segments AS r
                    WHERE r.geom && ST_Transform(query_bounds, 4326)
                      AND NOT r.is_link
                      AND (
                          r.road_class IN ('motorway', 'trunk')
                          OR (z >= 6 AND r.road_class = 'primary')
                          OR (z >= 7 AND r.road_class = 'secondary')
                          OR (z >= 8 AND r.road_class = 'tertiary')
                      )
                    GROUP BY r.road_class
                ) AS tile
                WHERE tile.geom IS NOT NULL;

                RETURN COALESCE(tile_bytes, '\x'::bytea);
            END IF;

            SELECT ST_AsMVT(tile, 'road_segments', 4096, 'geom', 'id')
            INTO tile_bytes
            FROM (
                SELECT
                    r.id, r.name, r.ref, r.road_class, r.is_link, r.surface,
                    r.lanes, r.maxspeed, r.oneway, r.access, r.toll, r.bridge,
                    r.tunnel, r.operator, r.network,
                    ST_AsMVTGeom(
                        ST_Transform(r.geom, 3857), tile_bounds, 4096, 64, true
                    ) AS geom
                FROM public.road_segments AS r
                WHERE r.geom && ST_Transform(query_bounds, 4326)
                  AND (z >= 10 OR (
                      NOT r.is_link AND (
                          r.road_class IN ('motorway', 'trunk')
                          OR (z >= 6 AND r.road_class = 'primary')
                          OR (z >= 7 AND r.road_class = 'secondary')
                          OR (z >= 8 AND r.road_class = 'tertiary')
                      )
                  ))
            ) AS tile
            WHERE tile.geom IS NOT NULL;

            RETURN COALESCE(tile_bytes, '\x'::bytea);
        END;
        $function$
    """)
    op.execute(r"""
        COMMENT ON FUNCTION public.road_segments_mvt(integer, integer, integer) IS
        '{
          "description": "Major OSM roads: z5-z9 presentation geometry grouped by road_class with is_link=false and no canonical feature IDs; z10+ individual canonical roads with detailed attributes",
          "minzoom": 5,
          "maxzoom": 14,
          "attribution": "© OpenStreetMap contributors",
          "vector_layers": [{
            "id": "road_segments",
            "fields": {
              "name": "String", "ref": "String", "road_class": "String",
              "is_link": "Boolean", "surface": "String", "lanes": "String",
              "maxspeed": "String", "oneway": "String", "access": "String",
              "toll": "String", "bridge": "String", "tunnel": "String",
              "operator": "String", "network": "String"
            }
          }]
        }'
    """)


def downgrade() -> None:
    op.execute(r"""
        CREATE OR REPLACE FUNCTION public.road_segments_mvt(z integer, x integer, y integer)
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
            SELECT ST_AsMVT(tile, 'road_segments', 4096, 'geom', 'id')
            INTO tile_bytes
            FROM (
                SELECT
                    r.id, r.name, r.ref, r.road_class, r.is_link, r.surface,
                    r.lanes, r.maxspeed, r.oneway, r.access, r.toll, r.bridge,
                    r.tunnel, r.operator, r.network,
                    ST_AsMVTGeom(
                        ST_Transform(r.geom, 3857), tile_bounds, 4096, 64, true
                    ) AS geom
                FROM public.road_segments AS r
                WHERE r.geom && ST_Transform(query_bounds, 4326)
                  AND (z >= 10 OR (
                      NOT r.is_link AND (
                          r.road_class IN ('motorway', 'trunk')
                          OR (z >= 6 AND r.road_class = 'primary')
                          OR (z >= 7 AND r.road_class = 'secondary')
                          OR (z >= 8 AND r.road_class = 'tertiary')
                      )
                  ))
            ) AS tile
            WHERE tile.geom IS NOT NULL;

            RETURN COALESCE(tile_bytes, '\x'::bytea);
        END;
        $function$
    """)
    op.execute(r"""
        COMMENT ON FUNCTION public.road_segments_mvt(integer, integer, integer) IS
        '{
          "description": "Major OSM road segments with semantic zoom visibility",
          "minzoom": 5,
          "maxzoom": 14,
          "attribution": "© OpenStreetMap contributors",
          "vector_layers": [{
            "id": "road_segments",
            "fields": {
              "name": "String", "ref": "String", "road_class": "String",
              "is_link": "Boolean", "surface": "String", "lanes": "String",
              "maxspeed": "String", "oneway": "String", "access": "String",
              "toll": "String", "bridge": "String", "tunnel": "String",
              "operator": "String", "network": "String"
            }
          }]
        }'
    """)
