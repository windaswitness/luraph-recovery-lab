# Contributing

Start with `python -m unittest discover -s tests -v` and the synthetic demo.
The toolkit has no runtime dependencies outside Python's standard library.

For a new VM adapter, include its layout and opcode semantics, an authored
synthetic fixture, and tests for unsupported instructions. A version banner
alone is not a compatibility test. Explain which captures were tested without
uploading private game sources, asset data, or credentials.

For compiler changes, test observable behavior and difficult cases: `nil` and
`false`, conditional assignments, multiple return values, closure captures,
loop exits, and side-effect order. A successful parse is not an equivalence
proof. Keep original behavior and deliberate gameplay changes separate.

Use the project issue template for failures. Redact private data and prefer a
small reproducer written for the issue. Never attach an entire recovered game
just to report an opcode mapping problem.
