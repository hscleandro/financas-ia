# Guidelines de UX para Telegram Bot

Documento de boas práticas para otimizar a experiência do usuário no Telegram.

## 📱 Características do Telegram

### Limitações Técnicas
- **Limite de mensagem:** 4096 caracteres
- **Usuário mobile:** Interface touch, tela pequena
- **Contexto interrompido:** Usuário pode estar em movimento, multitarefas
- **Notificações:** Mensagens chegam como notificações push

### Boas Práticas de Design

1. **Mensagens Curtas**
   - Máximo 2-3 linhas por mensagem quando possível
   - Dividir informações longas em múltiplas mensagens
   - Usar resumos em vez de listas completas

2. **Formatação Markdown**
   - `*negrito*` para valores monetários e palavras-chave
   - `_itálico_` para notas e observações secundárias
   - ` `código` ` para IDs e dados técnicos
   - Quebras de linha para separar seções

3. **Emojis Estratégicos**
   - ✅ Confirmações de sucesso
   - ❌ Erros e cancelamentos
   - 💰 Valores monetários
   - 📊 Resumos e relatórios
   - 🗑️ Exclusões
   - ✏️ Edições
   - 📝 Descrições
   - 📅 Datas
   - 🏷️ Categorias
   - 💳 Métodos de pagamento

## 🎯 Otimizações Implementadas (Sprint 5)

### 1. System Prompt Otimizado

**Arquivo:** `agent/prompts_telegram.py`

**Mudanças:**
- Instruções mais diretas e concisas
- Exemplos de formatação com Markdown
- Regras explícitas sobre limite de caracteres
- Tom mais conversacional ("Você está no celular do usuário")
- Ênfase em resolver com menos interações

**Antes:**
```
Seu papel: registrar gastos, consultar histórico financeiro, e corrigir ou excluir registros quando solicitado.
```

**Depois:**
```
🎯 **SEU PAPEL**
Registrar gastos, consultar histórico e corrigir registros quando solicitado.

⚠️ **REGRAS DE COMUNICAÇÃO TELEGRAM**
- Mensagens CURTAS e DIRETAS (máx 2-3 linhas por vez)
- Use *negrito* para valores e categorias
- Use emojis para feedback visual
```

### 2. Mensagens de Confirmação Melhoradas

**Arquivo:** `agent/graph.py`

**Antes:**
```
Confirme a exclusão do registro:
  ID #123 · R$ 50.00 · Almoço · Alimentação · pix · 2026-05-19

Tem certeza? (sim/não)
```

**Depois:**
```
🗑️ *Confirme a exclusão*

📝 Almoço
💰 *R$ 50,00*
🏷️ Alimentação · pix
📅 2026-05-19
🔢 ID #123

Tem certeza?
```

**Benefícios:**
- Estrutura visual clara
- Emojis facilitam escaneamento rápido
- Informação mais importante (valor) em negrito
- Melhor legibilidade em tela pequena

### 3. Botões Inline Aprimorados

**Arquivo:** `bot/keyboards.py`

**Antes:**
```
[✅ Confirmar] [❌ Cancelar]
```

**Depois:**
```
[✅ Sim, confirmar] [❌ Não, cancelar]
```

**Mudanças:**
- Texto mais explícito (não apenas emoji)
- Ação clara em português
- Reduz ambiguidade

### 4. Formatação de Listas e Resumos

**Novas Funções:** `format_expense_list()` e `format_summary()`

**Recursos:**
- Limita a 10 itens por padrão
- Mostra resumo "...e mais N itens"
- Total sempre visível
- Emojis por categoria
- Ordem decrescente (maior → menor)

**Exemplo de saída:**
```
📊 *Resumo - Janeiro 2026*

🍔 Alimentação: *R$ 1.250,00*
🚗 Transporte: *R$ 450,00*
🏠 Moradia: *R$ 2.100,00*

💰 *Total geral:* R$ 3.800,00
```

## 📝 Mensagens por Contexto

### Registro de Gasto

**Sucesso:**
```
✅ *R$ 50,00* · Almoço · Alimentação · pix · 19/05/2026
```

**Falta informação:**
```
Qual foi o método de pagamento?
```

**Erro (duplicata):**
```
❌ Gasto duplicado detectado.

Já existe um registro idêntico cadastrado.
```

### Consultas

**Lista de gastos:**
```
🍔 *Gastos de Alimentação*

1. *R$ 50,00* · Almoço · 19/05
2. *R$ 30,00* · Café · 18/05
3. *R$ 45,00* · Jantar · 17/05

💰 Total: R$ 125,00
```

**Nenhum resultado:**
```
❌ Não encontrei gastos com essa descrição.

Quer buscar em outro período?
```

### Erros e Problemas

**Erro genérico:**
```
❌ Ocorreu um erro.

Tente novamente em alguns instantes.
```

**Operação proibida:**
```
🚫 Exclusões em massa não são permitidas.

O sistema permite excluir apenas *um registro por vez*, com confirmação.
```

## 🧪 Testes de UX Recomendados

### Checklist de Qualidade

- [ ] Todas as mensagens cabem em uma tela de celular?
- [ ] Valores monetários estão em negrito?
- [ ] Emojis são consistentes por tipo de operação?
- [ ] Mensagens de erro são amigáveis e orientam próxima ação?
- [ ] Confirmações são claras e inequívocas?
- [ ] Listas longas são truncadas com resumo?
- [ ] Feedback de sucesso é imediato e visual?

### Casos de Teste

1. **Fluxo de registro completo**
   - Usuário menciona valor, descrição e método
   - Confirmação em 1 linha
   - Tempo: < 5 segundos

2. **Fluxo de registro incompleto**
   - Usuário não menciona método
   - Bot pergunta sem assumir padrão
   - Resposta clara com opções

3. **Consulta com muitos resultados**
   - > 10 gastos encontrados
   - Mostra top 10 + resumo
   - Total sempre visível

4. **Exclusão com confirmação**
   - Botões inline funcionais
   - Mensagem formatada com emojis
   - Feedback claro após ação

## 🔮 Melhorias Futuras (Pós-MVP 3)

### Curto Prazo
- [ ] Quick replies para métodos comuns ("pix", "crédito", "dinheiro")
- [ ] Mensagens contextuais baseadas em horário (bom dia/boa tarde)
- [ ] Sugestões de categoria baseadas em histórico

### Médio Prazo
- [ ] Gráficos inline via Chart.js + Telegram Photo API
- [ ] Notificações proativas (ex: "Você já gastou R$ X hoje")
- [ ] Comandos rápidos via / (ex: /resumo, /hoje)

### Longo Prazo
- [ ] Reconhecimento de voz para registro rápido
- [ ] OCR de notas fiscais via Telegram Photo
- [ ] Mini webapp integrado (Telegram Web Apps)

## 📚 Referências

- [Telegram Bot API - Formatting](https://core.telegram.org/bots/api#formatting-options)
- [Telegram Bot API - Inline Keyboards](https://core.telegram.org/bots/features#inline-keyboards)
- [Mobile UX Best Practices](https://www.nngroup.com/articles/mobile-ux/)
- [Conversational UI Design](https://www.nngroup.com/articles/conversational-interfaces/)

---

**Última atualização:** Sprint 5 - Estabilização (MVP 3)
**Próxima revisão:** Após 2 semanas de uso real
