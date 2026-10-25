-- Data-only graph serializer. This does not execute a captured application.
-- Explicit lazy ranges MAY invoke the loader's __index code; review them.
-- Invoke manually with the returned prototype and optional ranges:
-- { { target = knownConstantColumn, first = 1, last = instructionCount } }
-- This helper is NOT a sandbox and does not fetch or require any asset.
return function(root, lazyRanges)
    local maxNodes, maxEntries, maxLazyReads = 100000, 1000000, 1000000
    local lazyReads = 0
    local lazyErrors = {}
    for rangeIndex, range in ipairs(lazyRanges or {}) do
        assert(type(range.target) == "table", "lazy range target must be a table")
        assert(type(range.first) == "number" and range.first % 1 == 0 and range.first >= 1,
            "lazy range first must be a positive integer")
        assert(type(range.last) == "number" and range.last % 1 == 0 and range.last >= range.first,
            "lazy range last must be an integer >= first")
        assert(range.last - range.first + 1 <= maxLazyReads - lazyReads, "lazy read budget exceeded")
        assert(range.ignore_errors == nil or type(range.ignore_errors) == "boolean", "ignore_errors must be boolean")
        for index = range.first, range.last do
            lazyReads = lazyReads + 1
            local ok, value = pcall(function() return range.target[index] end)
            if ok then
                -- Preserve false; do not use an and/or expression here.
                rawset(range.target, index, value)
            elseif range.ignore_errors then
                table.insert(lazyErrors, { range = rangeIndex, index = index })
            else
                error("lazy constant read failed at range " .. rangeIndex .. ", index " .. index, 0)
            end
        end
    end

    local ids, pending, nodes = {}, {}, {}
    local entries = 0
    local function encode(value)
        local kind = type(value)
        if kind == "nil" then return { ["nil"] = true } end
        if kind == "boolean" then return value end
        if kind == "number" then
            if value ~= value then return { number = "nan" } end
            if value == math.huge then return { number = "+inf" } end
            if value == -math.huge then return { number = "-inf" } end
            return value
        end
        if kind == "string" then
            return { hex = (value:gsub(".", function(char)
                return string.format("%02x", string.byte(char))
            end)) }
        end
        if kind == "table" then
            if ids[value] == nil then
                assert(#pending < maxNodes, "graph node budget exceeded")
                ids[value] = #pending + 1
                pending[#pending + 1] = value
            end
            return { ref = ids[value] }
        end
        error("unsupported graph value type: " .. kind, 0)
    end
    local rootValue = encode(root)
    local cursor = 1
    while cursor <= #pending do
        local rows = {}
        -- Raw traversal avoids table __index / __pairs / __iter behavior.
        for key, value in next, pending[cursor] do
            entries = entries + 1
            assert(entries <= maxEntries, "graph entry budget exceeded")
            rows[#rows + 1] = { encode(key), encode(value) }
        end
        nodes[cursor] = rows
        cursor = cursor + 1
    end
    return { root = rootValue, nodes = nodes, lazy_errors = lazyErrors }
end
