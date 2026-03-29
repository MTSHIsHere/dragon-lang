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
- `dragonc.py` → Dragon official CLI implementation (`dragon`).
- `examples/hello.dragon` → simple example.
- `examples/math.dragon` → function example.
- `examples/control_flow.dragon` → `if/else` and `while` example.

## Official CLI

Prerequisite: Python 3.10+

```bash
dragon run examples/hello.dragon
dragon run examples/math.dragon
dragon run examples/input_and_func.dragon
```

To create installable bytecode (`.dbc`) and run it later:

```bash
dragon install examples/math.dragon -o build/math.dbc
dragon runbc build/math.dbc
```

To build a distributable app package for CLI or desktop launchers:

```bash
dragon build examples/hello.dragon --app-type cli -o build/hello-cli
dragon build examples/hello.dragon --app-type desktop -o build/hello-desktop
```

Build output includes bytecode, metadata (`dragon-app.json`), and platform launchers (`run.sh`, `run.bat`). Desktop builds also include a `.desktop` entry.

> Note: direct `python3 dragonc.py ...` usage is still supported for local development.

## Recommended next steps

1. Improve the `dragon build` pipeline for installer generation and signing.
2. Define the path for the future DragonOS kernel/userspace.

## Modules and standard library (initial)

- `import std` enables native functions:
  - `length(string) -> int`
  - `uppercase(string) -> string`
  - `lowercase(string) -> string`
  - `to_int(string) -> int`
  - `to_string(int) -> string`
- `import name` looks for `name.dragon` in the same folder as the main file.
