# Adapters, Capture, and Data Formats

Luraph Recovery Lab has two different kinds of profiles. A **capture profile** is a JSON file containing reviewed changes for one specific loader. A **recovery profile** is a Python adapter that understands a VM's data layout and opcode semantics. A match for one profile does not establish compatibility with the other.

Run all commands below from the repository root with Python 3.10+. The `--out` directory must be new or empty. These commands do not execute Lua or connect to Studio.

## Commands and Their Scope

```sh
python -m luraph_lab profiles
python -m luraph_lab inspect private/input.lua --out work/inspection
python -m luraph_lab capture-plan private/input.lua --profile private/capture-profile.json --out work/capture-plan
python -m luraph_lab recover private/capture.json --profile column-vm-v1 --out work/recovered
python -m luraph_lab demo --out work/demo
```

- `profiles` lists the built-in adapters and their supported scope.
- `inspect` normalizes supported literals and produces a string inventory. It statically examines the source text; it does not execute the decoder or reconstruct the VM.
- `capture-plan` validates a capture profile and generates a modified Lua/Luau file for review. The capture itself is performed separately.
- `recover` accepts an already captured JSON table graph. It does not accept an obfuscated `.lua` file directly.
- `demo` runs the same recovery pipeline on the original synthetic data included in the package.

For full usage information, run `python -m luraph_lab --help` or `python -m luraph_lab recover --help`. Invalid input or an unsupported construct causes the command to exit with a nonzero status.

## Capture Profiles: Exact Source, Exact Replacement

The working tutorial pair is [examples/toy_loader.lua](../examples/toy_loader.lua) and [examples/capture_profile.example.json](../examples/capture_profile.example.json). This loader was written specifically for the example; it is not someone else's obfuscated script.

```sh
python -m luraph_lab capture-plan examples/toy_loader.lua --profile examples/capture_profile.example.json --out work/toy-capture-plan
```

JSON profile fields:

- `schema_version`: currently must be the integer `1`.
- `name`: a nonempty name describing the profile's purpose.
- `input_sha256`: the SHA-256 of **the exact input file's bytes**, expressed as 64 hexadecimal characters. Changing line endings also changes the hash.
- `intercept.marker`: an exact source fragment that must occur exactly once and have valid token boundaries.
- `intercept.replacement`: the replacement text. In `prototype` mode, it must begin with `return` after comments are skipped.
- `intercept.returns`: `prototype` by default, or `reviewed_custom` for an explicitly reviewed custom return value.
- `intercept.reviewed`: a Boolean field that must be `true` for `reviewed_custom`.
- `strip_tail.suffix`: an optional exact suffix to remove, such as a final wrapper invocation. A mismatch is an error.
- `guard`: required settings for the cooperative execution guard.
- `include_graph_serializer`: an optional Boolean field; when `true`, the graph serializer is saved alongside the plan.

Unknown and duplicate profile keys are rejected. This makes configuration typos visible instead of silently ignoring them.

The hash confirms that the change applies to the expected file. The unique marker confirms the location of the text replacement. Neither proves that the loader can no longer execute the application. The `prototype` mode and `reviewed` field are declarations by the profile author, not the result of analyzing every possible call.

### What `guard` Actually Limits

Settings:

- `instruction_limit`: a positive integer up to 1 000 000 000. Despite its name, this counts **checkpoints**, not CPU or VM instructions.
- `time_limit_seconds`: a finite positive number no greater than 3600; elapsed time is checked when a checkpoint is reached.
- `hook_name`: an identifier beginning with `__`, defaulting to `__capture_guard`. It must not already appear among the source's identifiers.
- `yield_every`: the yield interval, defaulting to 1000; `0` disables yielding. Yielding is possible only when the environment provides the required APIs and permits it.

The generator inserts checks after recognized `do` and `repeat` tokens, plus one initial check. It does not instrument string or comment contents. This guard cannot interrupt a long native call, recursion without checkpoints, or a large straight-line section of code. It must not be described as a preemptive timeout or a sandbox.

### Plan Artifacts

- `capture.luau` — the modified source with interception and guard checks.
- `manifest.json` — hashes, sizes, replacement details, and an explicit `executed_input: false` flag.
- `serialize_graph.luau` — an optional, separate export helper.

The generator does not compile the resulting Lua. Before executing it elsewhere, check its syntax in the chosen dialect and review the changes. Adapting a profile to another file requires analyzing that loader again, not simply replacing the SHA-256 to pass validation.

## Serializing a Table Graph

Prototypes can share tables and reference one another. A regular nested JSON tree loses shared identity and cannot represent cycles. The capture therefore uses a graph:

```json
{
  "root": {"ref": 1},
  "nodes": [
    [[1, {"ref": 2}], [{"hex": "6c6162656c"}, {"hex": "64656d6f"}]],
    [[1, false], [2, 42], [3, {"nil": true}]]
  ]
}
```

This short example illustrates **only the graph format**. It does not contain a prototype for the required VM and is not an input on which `recover` is expected to succeed. For a complete synthetic example, see [examples/synthetic_capture.json](../examples/synthetic_capture.json).

Format rules:

- `nodes` is an array of tables. Each table is an array of `[key, value]` pairs.
- `{"ref": N}` refers to `nodes[N - 1]`; references are numbered starting at one.
- A Lua string is encoded as bytes: `{"hex": "..."}`. This preserves null bytes and strings that are not valid UTF-8.
- Finite numbers and Boolean values use ordinary JSON values.
- `{"nil": true}` represents `nil`; the loader also accepts JSON `null` as a value.
- `{"number": "nan"}`, `{"number": "+inf"}`, and `{"number": "-inf"}` represent special numeric values.

The current adapter accepts numeric keys and byte-string keys. It rejects Boolean keys, table references used as keys, `nil` keys, and nonfinite numeric keys. This is an adapter limitation: for example, Lua treats `true` and `1` as different keys, while they collide in an ordinary Python dictionary. The project does not hide that discrepancy through automatic conversion.

### Lazy Constants

A constant column may have an `__index` metamethod that computes a value on its first read. Raw table traversal cannot see entries that have not yet been materialized. The [graph_serializer.luau](../luraph_lab/resources/graph_serializer.luau) helper supports explicit ranges:

```lua
local graph = serializeGraph(prototype, {
    {target = knownConstantColumn, first = 1, last = knownInstructionCount},
})
```

Here, `serializeGraph`, `prototype`, `knownConstantColumn`, and `knownInstructionCount` are values the researcher has already obtained in the chosen environment. This is not a ready-to-run procedure for an arbitrary file.

Reading a range may execute `__index`; it is not a static operation. After each read, the serializer stores the value with `rawset`, preserving `false` as well. By default, a read error stops the export. For investigation, `ignore_errors = true` allows failed reads and records the gaps in `lazy_errors`, but the export cannot be considered complete until those errors have been investigated.

Subsequent traversal uses raw table pairs. The serializer does not export functions, environment objects, threads, or metatables as executable code. It returns an ordinary Lua table; writing that result as JSON is a separate step using facilities available in the environment.

The tutorial's `toy_loader.lua` demonstrates loader interception and export. It deliberately does not produce the `column-vm-v1` layout. Recovery is demonstrated with a separate synthetic graph; these two examples must not be presented as a universal end-to-end pipeline.

## The `column-vm-v1` Adapter

This is an experimental profile for **one observed column-based VM**. It does not identify the Luraph version and does not promise compatibility with every build of 13.8.1, 14.3, or any other version.

The current implementation is in [column_vm_v1.py](../luraph_lab/adapters/column_vm_v1.py). It expects these prototype fields:

- Field `9` — the opcode column.
- Fields `2`, `8`, and `11` — operand columns whose meanings depend on the opcode.
- Fields `1`, `3`, and `6` — constant columns.
- Field `5` — capture descriptors.
- Field `4` — integer stack information.
- Field `7` — integer metadata.
- Field `10` — an additional materialized column required by the schema.

Column fields must be tables, and instruction addresses must be positive integers. The root must be a matching prototype with no external upvalues. The adapter contains its own mappings for opcodes, aliases, and jumps. Similar field numbers are not enough if the handlers have different semantics.

The pipeline resolves supported self-modifying sections, builds a semantic IR, structures the graph, and generates Luau while preserving result counts. Captures distinguish shared mutable cells, values, and forwarded captures. Closing a cell separates the parent invocation's subsequent state from closures that already exist.

### `recover` Output

- `reconstructed.luau` — an intermediate reconstruction with generated names. The file returns the root function and **does not call it automatically**.
- `structured.json` — the structured intermediate representation for analysis.
- `selfmod.json` — a log of resolved sections and unsuccessful candidates.
- `report.json` — the profile, statistics, diagnostics, and `status: "intermediate"`.

Structuring is checked against 30 bounded abstract traces per function. These check that control flow agrees between the two representations; they do not execute the application in Lua. See [VALIDATION.md](VALIDATION.md) for details.

The adapter refuses to continue when it encounters unknown opcodes, remaining reachable VM-internal instructions, unsupported dynamic `SETLIST`, external root upvalues, reuse of one prototype at multiple lexical sites, an unstructurable graph, or an abstract trace mismatch. A reachable jump to a missing instruction and falling off the instruction stream without a terminator are also errors. These are current implementation limits, not claims that such programs are fundamentally impossible to recover.

### Size Limits

The recovery loader limits the input file to 128 MiB, the graph to 100 000 tables and 3 000 000 pairs, the prototype count to 1000, and each prototype to 100 000 instructions. The CFG has a stricter limit of 5000 reachable instructions per prototype. Register and upvalue indices must be in the range 0–4095. Structuring limits each attempt to 100 000 generated nodes. The Lua serializer has separate limits: 100 000 tables, 1 000 000 pairs, and 1 000 000 lazy reads.

These checks prevent some accidental oversized inputs. They do not impose a strict memory or time limit on the entire process.

## Adding Another Adapter

Implement a new layout as a separate profile so the existing one remains a reproducible point of comparison.

1. Document the prototype schema and establish the meaning of each field from the code that reads it.
2. Record the semantics of every handler in use: values, jumps, calls, captures, and side effects.
3. Add original, small fixtures for arithmetic, branches, loops, closures, varargs, and multiple results.
4. Implement parsing and normalization in `luraph_lab/adapters/` without including the original loader, encrypted payload, or game-specific strings.
5. Add profile selection to the pipeline and CLI; adding a Python file alone does not register it automatically.
6. Compare the IR with the structured output, then run differential tests in an appropriate Lua/Luau runtime.
7. Document refusal cases and inputs that have not yet been tested.

Fixing a specific game, installing objects in Studio, and migrating resources are outside the adapter's scope. They require separate knowledge of the application and separate integration checks.
