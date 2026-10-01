-- Explicit public port semantics only. This is the single ingestion filter.
-- Staging is disposable; Alembic owns canonical ports.
local ports = osm2pgsql.define_table({
    name = 'port_features',
    schema = 'staging_osm_ports',
    ids = { type = 'any', id_column = 'osm_id', type_column = 'osm_type' },
    columns = {
        { column = 'name', type = 'text' },
        { column = 'name_en', type = 'text' },
        { column = 'facility_class', type = 'text' },
        { column = 'water_context', type = 'text' },
        { column = 'cargo', type = 'text' },
        { column = 'operator', type = 'text' },
        { column = 'owner', type = 'text' },
        { column = 'website', type = 'text' },
        { column = 'wikidata', type = 'text' },
        { column = 'wikipedia', type = 'text' },
        { column = 'access', type = 'text' },
        { column = 'geom', type = 'geometry', projection = 4326 },
    },
})

local function has_category(categories, wanted)
    if not categories then return false end
    for category in string.gmatch(categories, '[^;]+') do
        if category == wanted then return true end
    end
    return false
end

local function classify(tags)
    local commercial = tags.industrial == 'port' or tags.landuse == 'port'
        or tags.harbour == 'commercial'
    local cargo = tags.port == 'cargo' or tags.harbour == 'cargo'
        or (tags['seamark:type'] == 'harbour'
            and has_category(tags['seamark:harbour:category'], 'cargo'))
    local fishing = tags.port == 'fishing' or tags.harbour == 'fishing'
        or (tags['seamark:type'] == 'harbour'
            and has_category(tags['seamark:harbour:category'], 'fishing'))
    local generic = tags.harbour == 'yes' or tags.harbour == 'port'
        or tags['seamark:type'] == 'harbour'
    if not (commercial or cargo or fishing or generic) then return nil end

    if tags.leisure == 'marina' or tags.landuse == 'military'
        or tags.access == 'military' or (tags.military and tags.military ~= 'no')
        or has_category(tags['seamark:harbour:category'], 'naval')
        or has_category(tags['seamark:harbour:category'], 'military')
        or has_category(tags['seamark:harbour:category'], 'marina')
        or has_category(tags['seamark:harbour:category'], 'marina_no_facilities') then
        return nil
    end
    for key, value in pairs(tags) do
        local lifecycle_prefix = false
        for _, prefix in ipairs({ 'abandoned:', 'disused:', 'razed:',
                                   'demolished:', 'construction:', 'proposed:' }) do
            if string.sub(key, 1, #prefix) == prefix then lifecycle_prefix = true end
        end
        if lifecycle_prefix or ((key == 'abandoned' or key == 'disused' or key == 'razed'
                or key == 'demolished' or key == 'construction' or key == 'proposed')
                and value ~= 'no') then
            return nil
        end
    end

    -- Ferry-only and leisure facilities are not economic port candidates.
    if tags.amenity == 'ferry_terminal' and not (commercial or cargo or fishing) then
        return nil
    end
    if has_category(tags['seamark:harbour:category'], 'ferry')
        and not (commercial or cargo or fishing) then
        return nil
    end
    if cargo then return 'cargo_terminal' end
    if fishing then return 'fishing_port' end
    if commercial then return 'commercial_port' end
    return 'port'
end

local function insert(object, geom, facility_class)
    local tags = object.tags
    if geom:is_null() then return end
    ports:insert({
        name = tags.name,
        name_en = tags['name:en'],
        facility_class = facility_class,
        -- inland_port covers rivers and lakes, so it remains unknown.
        water_context = tags['port:type'] == 'seaport' and 'sea' or nil,
        cargo = tags.cargo,
        operator = tags.operator,
        owner = tags.owner,
        website = tags.website,
        wikidata = tags.wikidata,
        wikipedia = tags.wikipedia,
        access = tags.access,
        geom = geom,
    })
end

function osm2pgsql.process_node(object)
    local facility_class = classify(object.tags)
    if facility_class then insert(object, object:as_point(), facility_class) end
end

function osm2pgsql.process_way(object)
    -- Open ways and generic piers cannot define a port facility footprint.
    local facility_class = classify(object.tags)
    if facility_class then insert(object, object:as_polygon(), facility_class) end
end

function osm2pgsql.process_relation(object)
    if object.tags.type ~= 'multipolygon' then return end
    local facility_class = classify(object.tags)
    if facility_class then insert(object, object:as_multipolygon(), facility_class) end
end
