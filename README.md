# Dragon Language (MVP)

Dragon is an early-stage programming language (MVP) with the `.dragon` extension.

Repository goals:
- Define a simple foundation for the Dragon language.
- Enable building small terminal applications.
- Serve as a base to evolve into a more robust language for the future OS.

## What already exists in this MVP

- Parser, bytecode compiler, and Dragon's own VM.
- Execution of Dragon programs via CLI.
- Static type checking for basic types: `int`, `string`, `bool`.
- Basic syntax with:
  - `let` (variables)
  - `print(...)`
  - `input(...)`
  - functions with `func ... end`
  - conditionals with `if ... else ... end`
  - loops with `while ... end`
  - `return`
- comments with `#`
  - modules with `import module_name`
  - standard library with `import std`

## Structure

- `docs/dragon-spec.md` → initial language specification.
- `dragonc.py` → main compiler/transpiler.
- `examples/hello.dragon` → simple example.
- `examples/math.dragon` → function example.
- `examples/control_flow.dragon` → `if/else` and `while` example.

## How to run

Prerequisite: Python 3.10+

```bash
python3 dragonc.py run examples/hello.dragon
python3 dragonc.py run examples/math.dragon
python3 dragonc.py run examples/input_and_func.dragon
```

To transpile without running (legacy mode, useful for debugging):

```bash
python3 dragonc.py transpile examples/math.dragon -o build/math.py
```

To compile distributable bytecode (`.dbc`) and run it later:

```bash
python3 dragonc.py compile examples/math.dragon -o build/math.dbc
python3 dragonc.py runbc build/math.dbc
```

## Recommended next steps

1. Expand modules with namespaces (`math.add`) and package-based resolution.
2. Create `dragon build` for desktop/CLI apps.
3. Define the path for the future DragonOS kernel/userspace.

## Modules and standard library (initial)

- `import std` enables native functions:
  - `length(string) -> int`
  - `uppercase(string) -> string`
  - `lowercase(string) -> string`
  - `to_int(string) -> int`
  - `to_string(int) -> string`
- `import name` looks for `name.dragon` in the same folder as the main file.
