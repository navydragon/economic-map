"""Include the MVT buffer in railway spatial candidate selection.

Revision ID: 0003_railway_mvt_buffer
Revises: 0002_zoom_aware_railway_mvt
"""

from alembic import op


revision = "0003_railway_mvt_buffer"
down_revision = "0002_zoom_aware_railway_mvt"
branch_labels = None
depends_on = None


def _install_function(*, buffered_query: bool) -> None:
    query_declaration = "query_bounds geometry;" if buffered_query else ""
    query_assignment = (
        "query_bounds := ST_TileEnvelope(z, x, y, margin => 64.0 / 4096.0);"
        if buffered_query else ""
    )
    candidate_bounds = "query_bounds" if buffered_query else "tile_bounds"
    op.execute(f"""
        CREATE OR REPLACE FUNCTION public.railway_segments_mvt(z integer, x integer, y integer)
        RETURNS bytea
        LANGUAGE plpgsql STABLE STRICT PARALLEL SAFE
        AS $function$
        DECLARE
            tile_bounds geometry;
            {query_declaration}
            tile_bytes bytea;
        BEGIN
            IF z < 5 THEN
                RETURN '\\x'::bytea;
            END IF;

            tile_bounds := ST_TileEnvelope(z, x, y);
            {query_assignment}
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
                WHERE r.geom && ST_Transform({candidate_bounds}, 4326)
                  AND (z >= 11 OR r.service IS NULL)
            ) AS tile
            WHERE tile.geom IS NOT NULL;

            RETURN COALESCE(tile_bytes, '\\x'::bytea);
        END;
        $function$
    """)


def upgrade() -> None:
    _install_function(buffered_query=True)


def downgrade() -> None:
    # Restore revision 0002's exact-envelope candidate selection, not a dropped function.
    _install_function(buffered_query=False)
