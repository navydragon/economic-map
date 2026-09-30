-- Disposable road staging only; canonical tables are owned by Alembic.
local accepted = {
    motorway = true, motorway_link = true,
    trunk = true, trunk_link = true,
    primary = true, primary_link = true,
    secondary = true, secondary_link = true,
    tertiary = true, tertiary_link = true,
}

local roads = osm2pgsql.define_way_table('road_lines', {
    { column = 'highway', type = 'text' },
    { column = 'name', type = 'text' },
    { column = 'ref', type = 'text' },
    { column = 'surface', type = 'text' },
    { column = 'lanes', type = 'text' },
    { column = 'maxspeed', type = 'text' },
    { column = 'oneway', type = 'text' },
    { column = 'access', type = 'text' },
    { column = 'toll', type = 'text' },
    { column = 'bridge', type = 'text' },
    { column = 'tunnel', type = 'text' },
    { column = 'operator', type = 'text' },
    { column = 'network', type = 'text' },
    { column = 'geom', type = 'linestring', projection = 4326 },
}, { schema = 'staging_osm_roads' })

function osm2pgsql.process_way(object)
    local tags = object.tags
    if not accepted[tags.highway] or tags.area == 'yes' then
        return
    end

    local geom = object:as_linestring()
    if geom:is_null() then
        return
    end

    roads:insert({
        highway = tags.highway,
        name = tags.name,
        ref = tags.ref,
        surface = tags.surface,
        lanes = tags.lanes,
        maxspeed = tags.maxspeed,
        oneway = tags.oneway,
        access = tags.access,
        toll = tags.toll,
        bridge = tags.bridge,
        tunnel = tags.tunnel,
        operator = tags.operator,
        network = tags.network,
        geom = geom,
    })
end
