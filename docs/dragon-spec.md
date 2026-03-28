# Dragon Language Specification (v0.1)

## 1. Objetivo
A Dragon é uma linguagem simples para acelerar prototipação de apps e, no futuro, ser uma das linguagens principais do DragonOS.

## 2. Extensão de arquivo
Arquivos Dragon usam a extensão:

```text
.dragon
```

## 3. Regras léxicas
- Espaços e tabs no início da linha são ignorados no v0.1.
- Comentários iniciam com `#`.
- Linhas vazias são ignoradas.

## 4. Sintaxe (v0.1)

### 4.1 Variáveis
```dragon
let nome = "Dragon"
let x = 10
```

### 4.2 Saída
```dragon
print("Olá")
print(nome)
```

### 4.3 Entrada (input)
```dragon
let nome = input("Seu nome: ")
print(nome)
```

### 4.4 Funções
```dragon
func soma(a, b)
    return a + b
end
```

### 4.5 Chamada de função
```dragon
let resultado = soma(2, 3)
print(resultado)
```

### 4.6 Condicionais
```dragon
if x > 10
    print("maior")
else
    print("menor ou igual")
end
```

### 4.7 Laços
```dragon
let i = 0
while i < 3
    print(i)
    let i = i + 1
end
```

## 5. Semântica (v0.1)
- `let` cria variável no escopo atual.
- `input(...)` lê dados do terminal e retorna `string`.
- `func` define função; bloco termina com `end`.
- `if`/`else` permite desvio condicional.
- `while` permite repetição baseada em condição.
- `return` encerra execução da função e devolve valor.
- Expressões são avaliadas pelo backend Python (MVP).

## 6. Limitações do MVP
- Sem classes e módulos.
- Sem tipagem estática.
- Backend depende de Python.

## 7. Roadmap curto
- v0.2: tipos básicos e erros melhores.
- v0.3: compilação para bytecode próprio.
