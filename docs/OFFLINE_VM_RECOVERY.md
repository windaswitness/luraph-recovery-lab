# Offline Recovery of Nested Lua/Luau VMs

This workflow reproduces a loader's byte transformations outside the Lua runtime,
then analyzes the extracted program. NARSIL 0.3.0 adds reusable unpacking
primitives and a native bytecode inventory. It does not bundle a complete
adapter for the custom buffer VM described below.

## What Was Different

An investigation encountered 39 protected scripts: 38 used a custom buffer VM,
while another contained packed native Luau bytecode interpreted by a wrapper.
One buffer-VM script contained a further packed native-bytecode layer.
These observations are not a reliable vendor fingerprint. No specific Luraph
version is attributed to this family.

The custom VM stored prototypes, constants, operands, and branch data in encoded
byte streams. Its loader used an embedded 81-symbol alphabet, position-dependent
symbol offsets, and XOR with an evolving byte key. Numeric expressions and
renamed instruction fields obscured the decoder. Instruction numbers and fields
had to be mapped to behavior for each variant; copying an opcode table from
another script was insufficient.

The native-bytecode wrappers used a different path: base85, byte-pair
permutations, position-dependent XOR passes, and extraction of periodically
spaced bytes. Decoding exposed Luau version-6/type-version-3 containers.
A nested envelope can therefore change the kind of VM being analyzed.

Renaming identifiers or encrypting strings leaves more of the program's
operations visible. Virtualization hides operations as data: decoding every
string can still leave a whole interpreter to understand. Compared with the
existing column-table adapter, the buffer family needs a new binary reader,
operand decoder, and semantic mapping.

## Why Decode Offline

A cooperative loader guard cannot preempt every native call, recursion path, or
long straight-line section. In this investigation, a live-host capture attempt
became unreliable, so extraction moved to a data-only decoder.

Offline decoding means translating observed byte operations into bounded
host-language functions. It does not mean evaluating arbitrary expressions from
an input file. Unpack profiles contain only allowlisted operations and numeric
parameters; there are no executable hooks.

The CLI neither starts the recovered application nor changes its access checks.
Application-specific modifications remain outside this repository.

## Reproduce the Method

From a downloaded checkout or an installed package:

~~~sh
python -m narsil demo-offline --out work/offline-demo
~~~

The demo generates an authored packed fixture and its exact-hash profile, decodes
six layers, then runs the existing recovery adapter on the extracted graph.
Its output directory contains:

- **packed.bin** and **unpack-profile.json**: input and reviewed transform plan.
- **unpacked/layer-01.bin** through **layer-06.bin**: intermediate bytes.
- **unpacked/payload.bin**: the original synthetic graph, byte for byte.
- **recovered/reconstructed.luau**: output from the column VM adapter.
- **demo-report.json**: separate unpacking and recovery diagnostics.

Replay only extraction:

~~~sh
python -m narsil unpack work/offline-demo/packed.bin --profile work/offline-demo/unpack-profile.json --out work/replay
~~~

The payload is the public synthetic **column-vm-v1 graph**, not a private buffer
format or native Luau sample. The envelope demonstrates the new unpacking
mechanism without implying support for every underlying VM.

For a new sample, extract its payload bytes during static inspection, derive a
profile from the loader, and run:

~~~sh
python -m narsil unpack private/payload.bin --profile private/unpack.json --out work/unpacked
python -m narsil bytecode-info private/decoded.luau.bin --out work/native-inventory
~~~

The first command accepts extracted bytes, not a complete obfuscated Lua file.
The second accepts decoded native bytecode. Neither guesses keys or maps unknown
VM instructions to source code. Use fresh output directories.

## Unpack Profile Schema

All top-level fields are required:

- **schema_version**: integer 1.
- **name**: a nonempty description.
- **input_sha256**: lowercase SHA-256 of the exact extracted input bytes.
- **output_sha256**: expected lowercase SHA-256 of the final decoded bytes.
- **layers**: an ordered array of 1 to 32 transformations.

Each layer has an **op**, the parameters below, and an optional **output_sha256**.
Unknown keys, duplicate JSON keys, booleans used as integers, unsupported
operations, and mismatched hashes are errors. The generated demo profile is a
working example.

For your own profile, independently check decoded output before recording its
expected hash. A matching hash confirms identity with that reviewed result; it
does not prove that the chosen algorithm is correct.

### Supported Transformations

Positions and pair indices are zero-based. Operations run in the listed order.

- **base85** takes **alphabet**, exactly 85 unique ASCII symbols. Five symbols
  become one big-endian uint32. Partial groups, unknown symbols, and overflow
  are rejected; there are no whitespace or abbreviation rules.
- **nibble81-v1** takes uint32 **salt**. The first 81 input bytes are a unique
  alphabet. At pair index i, subtract salt + 17*i + 11*floor(i/7) from the first
  symbol index, and 3*salt + 31*i + 13*floor(i/5) + 7 from the second, modulo 81.
  Both values must be in 0..15; combine them as 16*a + b. This is one observed
  envelope, not a universal base81 decoder.
- **rolling-xor-v1** takes byte **seed**. Decode d = input[i] XOR seed, then set
  seed = (73*seed + d + 17*i + 41) mod 256. The update uses the decoded byte.
- **xor-linear** takes byte parameters **multiplier** and **offset**. Decode
  input[i] XOR ((i*multiplier + offset) mod 256). A zero multiplier gives constant XOR.
- **swap-pairs** takes positive **skip_mod** and **skip_remainder** in
  0..skip_mod-1. Swap adjacent pairs except pair indices matching that remainder.
  An odd final byte is unchanged.
- **stride** takes **start**, positive **step**, and **count**, selecting exactly
  that many periodically spaced bytes. Out-of-bounds extraction is rejected.
- **slice** takes **start** and **length** for a checked contiguous range.

Limits: 16 MiB per input, 64 KiB per profile, 32 layers, and a conservative
64 MiB intermediate-data budget. Current transforms preserve or reduce size.
These are byte/item bounds, not a preemptive CPU timeout. The complete chain is
validated before decoded artifacts are written. Output filenames are generated
internally rather than supplied by the profile.

## Native Luau Inventory

**bytecode-info** accepts only bytecode version 6 with type version 3. It reads
strings, userdata name mappings, prototypes, raw code words, constant tags 0..7,
child references, and optional line/debug sections. It checks bounds and
references, limits item counts, and rejects trailing bytes.

Binary strings and IEEE-754 values are preserved as hex so invalid UTF-8,
signed zero, and nonfinite numbers are not silently changed by JSON.
The resulting **bytecode.json** is a structural inventory, not a disassembly.
Opcode semantics, AUX boundaries, import semantics, and type-metadata contents
still require analysis. A structurally accepted container is not necessarily
executable bytecode, and its JSON cannot be passed to **recover**.

Format references consulted during implementation:
[Luau bytecode definitions](https://github.com/luau-lang/luau/blob/master/Common/include/Luau/Bytecode.h)
and [Luau's loader](https://github.com/luau-lang/luau/blob/master/VM/src/lvmload.cpp).
The Python reader targets the narrow format above; it does not assume that the
latest Luau format is compatible.

## From Bytes to Readable Code

The remaining analysis has separate stages:

1. **Parse the actual payload.** Identify prototype boundaries, typed constants,
   integer encodings, instruction widths, and internal checksums. Require complete
   consumption of expected sections. Outer SHA-256 verification does not replace
   a format's own internal checksums.
2. **Recover handler semantics.** Follow interpreter reads and writes. Identify
   operands by behavior, not field names. Account for open argument/result counts,
   varargs, mutable captures, loop state, and jumps across auxiliary words.
3. **Translate into explicit IR.** Retain original prototype/instruction positions
   for diagnostics. Unknown instructions must remain errors.
4. **Recover structure.** Validate control-flow edges before emitting functions,
   conditionals, and loops. Transition traces do not validate arithmetic or APIs.
5. **Investigate nested payloads.** A recovered function that constructs another
   interpreter is an intermediate result. Extract its data separately instead
   of assuming the first decoded layer is the application.
6. **Validate behavior.** Compile in the target dialect, test isolated functions,
   then exercise actual initialization and user actions in the host application.

Changing a profile name does not convert arbitrary buffer/native bytecode into
the column adapter's input. A format reader and semantic lifter are still needed.

## A Mistake That Compilation Will Not Catch

Consider this authored example:

~~~lua
local material = (string.find(name, "snow") and "snow") or false
~~~

It returns a string or false. Replacing the conjunction with an OR expression
can return a numeric match position instead. Both versions compile, but a
table keyed by material names will behave differently. The failure may appear
only when a particular effect initializes.

Test value types, side effects, and boundary inputs, not just control-flow shape.
Keep application repairs separate from reconstruction errors and preserve an
original for comparison. Successful compilation and a working startup screen
are not proof that every handler was recovered correctly.

Public tests use authored data: fixed vectors, binary round trips, malformed
profiles, corrupted hashes, truncated bytecode, invalid references, and the
end-to-end CLI demo. Private application code, dumps, and sample-specific keys
are not distributed.
