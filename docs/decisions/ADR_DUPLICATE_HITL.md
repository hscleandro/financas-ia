# Decisão de Arquitetura — Detecção de Duplicatas com HITL

> Branch: `feature/hitl-duplicata`  
> Data: 2026-08-26  
> Contexto: Alterar o comportamento de detecção de duplicatas de gastos e ganhos de rejeição automática para confirmação do usuário (Human-in-the-Loop).

---

## 1. Objetivo

Permitir que o bot detecte gastos ou ganhos idênticos, mas ao invés de rejeitar automaticamente, ele alerte o usuário e pergunte se deseja prosseguir. Caso o usuário confirme, o registro duplicado é inserido normalmente.

---

## 2. Decisões Tomadas

### 2.1 Remoção da constraint UNIQUE no hash

Removida a constraint `UNIQUE` das colunas `hash` nas tabelas `expenses` e `incomes`. A unicidade física no banco não deve impedir o registro intencional de duplicatas confirmadas pelo usuário.

**Motivação:**
- Duplicatas legítimas existem na vida real (ex.: dois pagamentos iguais no mesmo dia, dois saques de mesma descrição).
- A restrição de integridade não pode decidir pela pessoa.
- Facilita a implementação de confirmação HITL sem precisar abrir exceções no banco.

### 2.2 Detecção de duplicata no service layer

A lógica de detecção permanece baseada no hash SHA-256 de `amount|normalized_description|date`, calculado pelos serviços `ExpenseService` e `IncomeService`. Antes de inserir, o serviço busca um registro ativo com o mesmo hash.

**Comportamento:**
- Se não houver duplicata → insere normalmente.
- Se houver duplicata e `force=False` → retorna `{"warning": ..., "tipo": "duplicata", "record": {...}}`.
- Se houver duplicata e `force=True` → insere normalmente.

### 2.3 Confirmação HITL via LLM

A confirmação é conduzida pelo próprio agente conversacional, sem nó adicional no grafo LangGraph.

**Motivação:**
- Reutiliza o mecanismo de conversação já existente.
- Evita complexidade extra no `agent/graph.py`.
- O agente já sabe interpretar retornos de ferramentas e fazer follow-up.

**Fluxo:**
1. Usuário manda "gastei 20 reais no almoço".
2. Agente chama `record_expense(...)` com `force=False`.
3. Tool retorna warning de duplicata.
4. Agente pergunta: "Já existe um gasto idêntico em [data]. Deseja cadastrar mesmo assim?".
5. Usuário confirma.
6. Agente chama `record_expense(...)` novamente, agora com `force=True`.

### 2.4 Exposição do parâmetro `force` nas tools

As tools `record_expense` e `record_income` expõem o parâmetro booleano `force`. O prompt instrui o agente a gerenciá-lo automaticamente, da mesma forma que faz com `confirmed` em operações destrutivas.

---

## 3. Migração

Migration `0010_remove_hash_unique_constraint.py`:
- Remove a constraint `UNIQUE` de `expenses.hash`.
- Remove a constraint `UNIQUE` de `incomes.hash`.
- Recria os índices comuns mantidos (user_id, date, category).

---

## 4. Impactos

### 4.1 Positivos
- Experiência mais natural: o bot pergunta em vez de simplesmente negar.
- Permite duplicatas reais quando o usuário quiser.
- Reduz frustração com mensagens do tipo "gasto duplicado" sem contexto.

### 4.2 Cuidados
- É possível cadastrar duplicatas acidentalmente se o usuário confirmar sem atenção.
- O agente deve ser instruído no prompt a só usar `force=True` após confirmação explícita.

---

## 5. Arquivos Alterados

- `migrations/versions/0010_remove_hash_unique_constraint.py` (novo)
- `database/setup.py`
- `services/expense_service.py`
- `services/income_service.py`
- `agent/tools.py`
- `agent/prompts_telegram.py`
- `tests/test_service_layer.py`
- `tests/test_income_service.py`
- `docs/decisions/ADR_DUPLICATE_HITL.md` (este arquivo)
