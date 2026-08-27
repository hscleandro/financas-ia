# Decisões de Arquitetura — Registro de Ganhos

> Branch: `feature/income-tracking`  
> Data: 2026-08-26  
> Contexto: Adicionar ao Finanças IA a capacidade de registrar, consultar e analisar ganhos/receitas, mantendo a mesma experiência conversacional do Telegram e o isolamento multi-tenant.

---

## 1. Objetivo

Permitir que o usuário registre ganhos (salários, freelas, investimentos, etc.) além de despesas, para ter uma visão completa da sua situação financeira.

---

## 2. Decisões Tomadas

### 2.1 Modelo de Dados

#### 2.1.1 Tabela separada: `incomes`

Optamos por criar uma tabela `incomes` separada de `expenses`, em vez de uma única tabela `transactions` com uma coluna `type`.

**Motivação:**
- Despesas e receitas têm comportamentos distintos (ex.: despesas têm métodos de pagamento, ganhos não).
- Facilita queries e sumários específicos.
- Mantém o schema existente estável sem migration complexa de dados.
- Permite evoluções independentes no futuro.

**Campos da tabela `incomes`:**

```sql
CREATE TABLE incomes (
    id            INTEGER   PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER   NOT NULL REFERENCES users(id),
    amount        REAL      NOT NULL CHECK(amount > 0 AND amount < 10000000),
    description   TEXT      NOT NULL,
    category      TEXT      NOT NULL REFERENCES income_categories(name),
    income_date   DATE      NOT NULL DEFAULT CURRENT_DATE,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hash          TEXT      NOT NULL UNIQUE,
    deleted_at    TIMESTAMP DEFAULT NULL
);
```

#### 2.1.2 Categorias de ganho separadas: `income_categories`

Criar uma tabela `income_categories`, separada de `categories`, para evitar misturar categorias de despesa e receita.

**Motivação:**
- O LLM não confunde "Alimentação" com "Salário".
- Listagens e sumários ficam mais limpos.
- Facilita validação por domínio.

**Categorias padrão (seeds):**

| Categoria       | Tipo     |
|-----------------|----------|
| Salário         | system   |
| Freela          | system   |
| Investimentos   | system   |
| Reembolso       | system   |
| Outros          | system   |

### 2.2 Service Layer

#### 2.2.1 Novo service: `IncomeService`

Criar `services/income_service.py` espelhando a estrutura de `ExpenseService`, mas focado em receitas.

**Motivação:**
- Separação de responsabilidades.
- Facilita testes unitários independentes.
- Evita condicionais poluídas em um único service.

**Métodos públicos planejados:**
- `record_income(...)`
- `query_incomes(...)`
- `get_income_summary(...)`
- `list_income_categories(...)`
- `create_income_category(...)`
- `find_income_candidates(...)`
- `delete_income(...)`
- `update_income(...)`

#### 2.2.2 Não alterar `ExpenseService`

Manter `ExpenseService` inalterado, exceto se surgir necessidade de método combinado (ex.: saldo líquido).

### 2.3 Agente LangGraph

#### 2.3.1 Novas tools

Adicionar tools em `agent/tools.py` para interagir com `IncomeService`:

- `record_income`
- `query_incomes`
- `get_income_summary`
- `list_income_categories`
- `create_income_category`
- `find_income_candidates`
- `delete_income`
- `update_income`

#### 2.3.2 Prompts atualizados

Atualizar `agent/prompts_telegram.py` para ensinar o bot a:
- Reconhecer intenções de registro de ganho.
- Usar categorias de ganho.
- Distinguir ganho de despesa pela linguagem natural.
- Responder com emojis e formatação adequados.

### 2.4 UX no Telegram

#### 2.4.1 Mensagens de confirmação

Ganhos também passarão por confirmação HITL para exclusão/edição, assim como despesas.

#### 2.4.2 Emojis distintos

Usar emojis distintos para ganhos para feedback visual rápido:

- 💰 Receita registrada
- 💸 Despesa registrada
- 📈 Resumo de ganhos

### 2.5 Consultas e Análises

#### 2.5.1 Sumários separados, mas com opção de consolidado

Inicialmente teremos:
- `get_summary` para despesas (existente)
- `get_income_summary` para ganhos (novo)

Futuramente podemos adicionar:
- `get_balance_summary` (ganhos - despesas) — fora do escopo inicial.

#### 2.5.2 Periodo padrão

Ambos os sumários devem respeitar o mesmo padrão de período (hoje, semana, mês, etc.).

### 2.6 Multi-tenancy

Todas as operações de ganho devem respeitar `user_id`, assim como despesas.
A tabela `incomes` terá `user_id` obrigatório.

### 2.7 Migrations

Criar migrations Alembic:

1. `0008_add_income_categories.py`
2. `0009_add_incomes_table.py`

**Motivação:** manter o histórico de schema versionado e permitir rollback.

### 2.8 Soft Delete e Audit

Ganhos também usarão soft delete (`deleted_at`) e terão audit_log para `delete`/`update`, reutilizando a tabela existente.

### 2.9 Duplicatas

Assim como despesas, ganhos terão hash para evitar duplicatas baseadas em `amount + descrição normalizada + income_date`.

### 2.10 Testes

Adicionar testes:
- `tests/test_income_service.py`
- `tests/test_income_query.py`
- Atualizar `tests/test_tools_integration.py` para incluir tools de ganho
- Atualizar `tests/test_guardrails.py` se necessário

---

## 3. Não Escopo Inicial

As seguintes funcionalidades foram explicitamente deixadas fora do MVP desta feature:

- Projeção de saldo futuro
- Categorização automática por ML
- Recorrência de ganhos
- Integração com bancos/plataformas
- Relatório consolidado ganhos vs despesas

---

## 4. Próximos Passos de Implementação

1. Criar migration `0008_add_income_categories.py`.
2. Criar migration `0009_add_incomes_table.py`.
3. Implementar `services/income_service.py`.
4. Criar schemas Pydantic em `models/schemas.py` (se necessário).
5. Adicionar tools de ganho em `agent/tools.py`.
6. Atualizar `agent/prompts_telegram.py`.
7. Atualizar teclados/formatação em `bot/keyboards.py` (se necessário).
8. Escrever testes.
9. Atualizar `docs/PROJECT_STRUCTURE.md`.

---

## 6. Status de Implementação

| Passo | Status | Commit |
|---|---|---|
| Migrations 0008/0009 | ✅ Concluído | `e124388` |
| IncomeService + schemas | ✅ Concluído | `fe2dcb1` |
| Tools do agente + handler | ✅ Concluído | `c15a2d7` |
| Prompt Telegram | ✅ Concluído | `038041b` |
| Testes | ✅ Concluído | `e1b88cc` |
| setup_database atualizado | ✅ Concluído | `8c58666` |

### Validação

```bash
pytest -v
# 51 passed in 5.85s
```

### Bot em produção

Bot reiniciado em modo polling após aplicação das migrations. Usuário `Leandro (974597459)` cadastrado e pronto para testes.

---

## 7. Próximos Passos Sugeridos

- Testar no Telegram mensagens como:
  - "Recebi 5000 de salário"
  - "Quanto ganhei esse mês?"
  - "Resumo dos meus ganhos"
- Considerar adicionar relatório consolidado (ganhos - despesas) no futuro
- Documentar a feature no README.md

---

**Última atualização:** 2026-08-26 — implementação concluída e testada
