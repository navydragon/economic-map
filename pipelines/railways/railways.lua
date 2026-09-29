-- Source-specific staging. Canonical tables are owned by Alembic, never osm2pgsql.
local railways = osm2pgsql.define_way_table('railway_lines', {
    { column = 'railway', type = 'text' },
    { column = 'name', type = 'text' },
    { column = 'ref', type = 'text' },
    { column = 'usage', type = 'text' },
    { column = 'service', type = 'text' },
    { column = 'operator', type = 'text' },
    { column = 'electrified', type = 'text' },
    { column = 'gauge', type = 'text' },
    { column = 'tracks', type = 'text' },
    { column = 'maxspeed', type = 'text' },
    { column = 'bridge', type = 'text' },
    { column = 'tunnel', type = 'text' },
    { column = 'geom', type = 'linestring', projection = 4326 },
}, { schema = 'staging_osm_railways' })

function osm2pgsql.process_way(object)
    local tags = object.tags
    if tags.railway ~= 'rail' and tags.railway ~= 'narrow_gauge' then
        return
    end
    if tags.disused == 'yes' or tags.abandoned == 'yes' or tags.razed == 'yes'
        or tags.construction == 'yes' or tags.proposed == 'yes' then
        return
    end

    local geom = object:as_linestring()
    if geom:is_null() then
        return
    end

    railways:insert({
        railway = tags.railway,
        name = tags.name,
        ref = tags.ref,
        usage = tags.usage,
        service = tags.service,
        operator = tags.operator,
        electrified = tags.electrified,
        gauge = tags.gauge,
        tracks = tags.tracks,
        maxspeed = tags.maxspeed,
        bridge = tags.bridge,
        tunnel = tags.tunnel,
        geom = geom,
    })
end
