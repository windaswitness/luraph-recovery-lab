-- Generated ONLY from authored synthetic fixtures. No application source.
local fixtures = {}
fixtures.escaping_close = function()
    local v0_2
    local v0_1 = {value = nil}
    v0_1.value = 7
    v0_2 = (function(captured1_0)
        return function()
            return captured1_0.value
        end
    end)(v0_1)
    v0_1 = {value = v0_1.value}
    v0_1.value = 9
    return v0_2
end
fixtures.single_call = function(v0_1)
    return (v0_1())
end
fixtures.multi_call = function(v0_1)
    return v0_1()
end
fixtures.fixed_call = function(v0_1)
    local v0_2
    v0_1, v0_2 = v0_1()
    return v0_1, v0_2
end
fixtures.varargs = function(...)
    return ...
end
fixtures.arithmetic = function(v0_1, v0_2)
    local v0_3
    v0_3 = (v0_1 + 10)
    if v0_2 then
        v0_3 = (v0_3 * 2)
    else
        v0_3 = 5
    end
    return v0_3
end

-- Call the returned function to run the authored contracts.
return function()
    assert(fixtures.arithmetic(7, true) == 34, "true branch")
    assert(fixtures.arithmetic(7, false) == 5, "false branch")
    assert(fixtures.escaping_close()() == 7, "closed mutable capture")
    local function values() return 3, 4, 5 end
    local result = table.pack(fixtures.single_call(values))
    assert(result.n == 1 and result[1] == 3, "single result")
    result = table.pack(fixtures.multi_call(values))
    assert(result.n == 3 and result[1] == 3 and result[2] == 4 and result[3] == 5, "multiple results")
    result = table.pack(fixtures.fixed_call(values))
    assert(result.n == 2 and result[1] == 3 and result[2] == 4, "fixed result count")
    result = table.pack(fixtures.varargs(1, nil, 3, nil))
    assert(result.n == 4 and result[1] == 1 and result[2] == nil
        and result[3] == 3 and result[4] == nil, "nil varargs")
    return {passed = 7}
end
