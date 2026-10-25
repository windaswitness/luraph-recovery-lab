-- Native contracts for the data-only graph serializer.
-- Pass the function returned by resources/graph_serializer.luau.
return function(serialize)
    local data = {
        flag = false,
        bytes = string.char(0, 255, 10),
        notANumber = 0/0,
        infinity = math.huge,
    }
    data.self = data
    local reads = 0
    data.lazy = setmetatable({}, {__index = function(_, index)
        reads += 1
        if index == 1 then return false end
        error("intentional lazy constant failure")
    end})
    local graph = serialize(data, {{target = data.lazy, first = 1, last = 2, ignore_errors = true}})
    local fields = {}
    for _, pair in graph.nodes[1] do
        if pair[1].hex then fields[pair[1].hex] = pair[2] end
    end
    assert(fields["666c6167"] == false, "false must survive")
    assert(fields["6279746573"].hex == "00ff0a", "binary bytes must survive")
    assert(fields["73656c66"].ref == 1, "cycle must refer to the same table")
    assert(fields["6e6f74414e756d626572"].number == "nan", "NaN tag")
    assert(fields["696e66696e697479"].number == "+inf", "infinity tag")
    assert(reads == 2 and #graph.lazy_errors == 1 and data.lazy[1] == false, "lazy ranges")
    assert(serialize(nil).root["nil"] == true, "nil root")
    assert(not pcall(serialize, {function() end}), "functions must be rejected")
    return {passed = 8}
end
