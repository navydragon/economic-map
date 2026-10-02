-- Disposable waterway staging only; Alembic owns canonical segments.
local accepted = { river = true, canal = true, fairway = true }
local lifecycle = { 'abandoned', 'disused', 'razed', 'demolished', 'proposed', 'construction' }

local waterways = osm2pgsql.define_way_table('waterway_lines', {
    { column = 'waterway', type = 'text' },
    { column = 'name', type = 'text' },
    { column = 'name_en', type = 'text' },
    { column = 'ref', type = 'text' },
    { column = 'boat', type = 'text' },
    { column = 'motorboat', type = 'text' },
    { column = 'ship', type = 'text' },
    { column = 'oneway_boat', type = 'text' },
    { column = 'cemt', type = 'text' },
    { column = 'usage', type = 'text' },
    { column = 'service', type = 'text' },
    { column = 'width', type = 'text' },
    { column = 'intermittent', type = 'text' },
    { column = 'tidal', type = 'text' },
    { column = 'operator', type = 'text' },
    { column = 'wikidata', type = 'text' },
    { column = 'wikipedia', type = 'text' },
    { column = 'geom', type = 'linestring', projection = 4326 },
}, { schema = 'staging_osm_waterways' })

function osm2pgsql.process_way(object)
    local tags = object.tags
    if not accepted[tags.waterway] or tags.area == 'yes' then
        return
    end
    for _, state in ipairs(lifecycle) do
        local former = tags[state .. ':waterway']
        if (former and former ~= '' and former ~= 'no') or tags[state] == 'yes' then
            return
        end
    end

    local geom = object:as_linestring()
    if geom:is_null() then
        return
    end
    waterways:insert({
        waterway = tags.waterway,
        name = tags.name,
        name_en = tags['name:en'],
        ref = tags.ref,
        boat = tags.boat,
        motorboat = tags.motorboat,
        ship = tags.ship,
        oneway_boat = tags['oneway:boat'],
        cemt = tags.CEMT,
        usage = tags.usage,
        service = tags.service,
        width = tags.width,
        intermittent = tags.intermittent,
        tidal = tags.tidal,
        operator = tags.operator,
        wikidata = tags.wikidata,
        wikipedia = tags.wikipedia,
        geom = geom,
    })
end
