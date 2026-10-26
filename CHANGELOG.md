# Changelog

## 0.3.0 — Offline VM recovery workflow

- Add exact-hash, declarative unpack profiles for nested base85/nibble81 data,
  rolling and linear XOR, pair swaps, stride extraction, and slicing.
- Preserve intermediate byte streams and hashes without running Lua.
- Add bytecode-info for structural inspection of Luau v6/type-v3 containers.
  It does not decode opcode semantics or produce source code.
- Add demo-offline: author a nested envelope, unpack it, and recover the existing
  synthetic column-VM graph.
- Document buffer VMs, nested native-bytecode wrappers, offline extraction,
  semantic pitfalls, and the boundary between unpacking and devirtualization.
- Add malformed-input and CLI tests; retain the existing recovery adapter.

This release does not automatically decompile arbitrary custom VMs.
No private application code, assets, dumps, or access-control patches are bundled.

## 0.2.0 — NARSIL

- Rename Luraph Recovery Lab to NARSIL.
- Publish the Python CLI, column VM adapter, synthetic demo, and method guide.
