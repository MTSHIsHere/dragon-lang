# Dragon Language Specification (v0.2)

## 1. Goal
Dragon is a simple language to accelerate app prototyping and, in the future, become one of the main languages of DragonOS.

## 2. File extension
Dragon files use the extension:

```text
.dragon
```

## 3. Lexical rules
- Leading spaces and tabs are ignored in v0.2.
- Comments start with `#`.
- Empty lines are ignored.

## 4. Syntax (v0.2)

### 4.1 Basic types
Supported types in the MVP:
- `int`
- `string`
- `bool`

### 4.2 Variables
Explicit declaration with type:

```dragon
let name: string = "Dragon"
let x: int = 10
let active: bool = true
```

Type inference is also allowed when declaring without annotation:

```dragon
let total = 42
```

Reassignment uses `=` without `let`:

```dragon
total = total + 1
```

### 4.3 Output
```dragon
print("Hello")
print(name)
```

### 4.4 Input
```dragon
let name: string = input("Your name: ")
print(name)
```

### 4.5 Functions
Function parameters must include types:

```dragon
func add(a: int, b: int)
    return a + b
end
```

### 4.6 Function call
```dragon
let result: int = add(2, 3)
print(result)
```

### 4.7 Conditionals
```dragon
if x > 10
    print("greater")
else
    print("less or equal")
end
```

### 4.8 Loops
```dragon
let i: int = 0
while i < 3
    print(i)
    i = i + 1
end
```

## 5. Semantics (v0.2)
- `let` creates a variable in the current scope.
- `input(...)` reads terminal input and returns `string`.
- `func` defines a function; the block ends with `end`.
- `if`/`else` enables conditional branching.
- `while` enables condition-based repetition.
- `return` ends function execution and returns a value.
- Expressions are compiled to Dragon bytecode and executed in the Dragon VM.
- The compiler performs static checking:
  - `if/while` conditions must be `bool`;
  - reassignment to a different type is not allowed;
  - use of undeclared variables is not allowed;
  - argument types in function calls are validated.

## 6. MVP limitations
- No classes or advanced module system.
- No explicit function return type annotation in `func`.
- `.dbc` format still has no signature/encryption for secure distribution.

## 7. Short roadmap
- v0.3: improve type inference and function return type handling.
- v0.4: evolve toolchain (`dragon build`) and packaging.
