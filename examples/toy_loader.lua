return (function()
    local function decode()
        local rows = {}
        for index = 1, 3 do rows[index] = {index, index * 2} end
        return {instructions = rows, constants = {"sample", false}}
    end
    local function create(prototype)
        return function() return prototype.instructions[1][2] end
    end
    return create(decode())
end)()()
