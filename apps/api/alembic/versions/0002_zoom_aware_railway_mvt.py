"""Serve railway tiles with zoom-aware service-track visibility.

Revision ID: 0002_zoom_aware_railway_mvt
Revises: 0001_railway_domain
"""

from alembic import op


revision = "0002_zoom_aware_railway_mvt"
down_revision = "0001_railway_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION public.railway_segments_mvt(z integer, x integer, y integer)
        RETURNS bytea
        LANGUAGE plpgsql STABLE STRICT PARALLEL SAFE
        AS $function$
        DECLARE
            tile_bounds geometry;
            tile_bytes bytea;
        BEGIN
            IF z < 5 THEN
                RETURN '\\x'::bytea;
            END IF;

            tile_bounds := ST_TileEnvelope(z, x, y);
            SELECT ST_AsMVT(tile, 'railway_segments', 4096, 'geom', 'id')
            INTO tile_bytes
            FROM (
                SELECT
                    r.id,
                    r.name,
                    r.ref,
                    r.railway_type,
                    r.usage,
                    r.service,
                    r.operator,
                    r.electrified,
                    r.gauge,
                    ST_AsMVTGeom(
                        ST_Transform(r.geom, 3857), tile_bounds, 4096, 64, true
                    ) AS geom
                FROM public.railway_segments AS r
                WHERE r.geom && ST_Transform(tile_bounds, 4326)
                  AND (z >= 11 OR r.service IS NULL)
            ) AS tile
            WHERE tile.geom IS NOT NULL;

            RETURN COALESCE(tile_bytes, '\\x'::bytea);
        END;
        $function$
    """)
    op.execute("""
        COMMENT ON FUNCTION public.railway_segments_mvt(integer, integer, integer) IS
        '{
          "description": "Canonical railway segments with zoom-aware service tracks",
          "minzoom": 5,
          "maxzoom": 14,
          "attribution": "© OpenStreetMap contributors",
          "vector_layers": [{
            "id": "railway_segments",
            "fields": {
              "name": "String",
              "ref": "String",
              "railway_type": "String",
              "usage": "String",
              "service": "String",
              "operator": "String",
              "electrified": "String",
              "gauge": "String"
            }
          }]
        }'
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION public.railway_segments_mvt(integer, integer, integer)")
