# Telegram Bot — MVP 3

Assistente Financeiro Pessoal via Telegram Bot.

## 🚀 Quick Start (Modo Polling — Desenvolvimento)

### 1. Criar Bot no Telegram

```bash
# 1. Abra o Telegram
# 2. Busque por @BotFather
# 3. Envie: /newbot
# 4. Escolha nome e username do bot
# 5. Copie o token: "1234567890:ABCdef..."
```

### 2. Configurar `.env`

```env
TELEGRAM_BOT_TOKEN=seu_token_aqui
TELEGRAM_WEBHOOK_SECRET=qualquer_string_secreta
```

### 3. Instalar dependências

```bash
pip install -r requirements.txt
```

### 4. Descobrir seu Telegram ID

```bash
# 1. Abra o Telegram
# 2. Busque por @userinfobot
# 3. Envie: /start
# 4. O bot responderá com seu ID (ex: 123456789)
```

### 5. Criar usuário no sistema

```bash
python setup_telegram_user.py 123456789 "Seu Nome"
```

### 6. Iniciar bot em modo polling

```bash
python main_telegram_polling.py
```

### 7. Testar no Telegram

```
1. Abra o Telegram
2. Busque pelo username do seu bot
3. Envie: /start
4. Converse normalmente:
   - "registra um gasto de 50 reais em alimentação"
   - "quais foram meus gastos de hoje?"
   - "resumo do mês"
```

---

## 🌐 Modo Webhook (Produção)

### Com ngrok (desenvolvimento local com webhook)

```bash
# Terminal 1: FastAPI
uvicorn api.webhook:app --port 8000

# Terminal 2: ngrok
ngrok http 8000

# Terminal 3: Registrar webhook
curl -X POST http://localhost:8000/webhook/register
```

### Com servidor real (EC2, VPS, etc.)

1. **Deploy da aplicação**
   ```bash
   # No servidor
   uvicorn api.webhook:app --host 0.0.0.0 --port 8000
   ```

2. **Configurar `.env` no servidor**
   ```env
   TELEGRAM_BOT_TOKEN=seu_token
   TELEGRAM_WEBHOOK_SECRET=secret_forte_aqui
   TELEGRAM_WEBHOOK_URL=https://seu-dominio.com/webhook/telegram
   ```

3. **Registrar webhook**
   ```bash
   curl -X POST https://seu-dominio.com/webhook/register
   ```

4. **Verificar webhook**
   ```bash
   curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo
   ```

---

## 📋 Comandos Úteis

### Remover webhook (para voltar ao polling)

```bash
curl -X DELETE http://localhost:8000/webhook/unregister
```

### Verificar status do webhook

```bash
curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo
```

### Healthcheck da API

```bash
curl http://localhost:8000/health
```

---

## 🧪 Testando HITL (Botões Inline)

```
1. "exclui meu último gasto de alimentação"
   → Bot mostra detalhes do gasto
   → Bot envia botões: ✅ Confirmar | ❌ Cancelar
   → Clique em ✅ Confirmar
   → Gasto excluído

2. "atualiza o valor do almoço de hoje para 35 reais"
   → Bot mostra mudanças
   → Botões aparecem
   → Confirme ou cancele
```

---

## 🔒 Whitelist de Usuários

Apenas usuários cadastrados podem usar o bot:

```bash
# Adicionar novo usuário
python setup_telegram_user.py <telegram_id> "Nome"

# Via Python (programaticamente)
from database.setup import get_connection
from database.user_setup import create_user

conn = get_connection()
user_id = create_user(conn, telegram_id=987654321, name="Alice")
conn.close()
```

### Desativar usuário

```python
from database.setup import get_connection
from database.user_setup import deactivate_user

conn = get_connection()
deactivate_user(conn, user_id=1)
conn.commit()
conn.close()
```

---

## 📂 Estrutura do Código

```
telegram/
  __init__.py
  handlers.py        # Lógica compartilhada (polling + webhook)
  keyboards.py       # Botões inline para HITL

api/
  __init__.py
  webhook.py         # FastAPI webhook receiver

main_telegram_polling.py   # Modo polling (desenvolvimento)
setup_telegram_user.py     # Script para adicionar usuários
```

---

## 🐛 Troubleshooting

### Bot não responde no polling

```bash
# Verificar se webhook está ativo (deve estar vazio)
curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo

# Se houver webhook, remover:
curl -X POST https://api.telegram.org/bot<TOKEN>/deleteWebhook

# Reiniciar polling
python main_telegram_polling.py
```

### "Acesso não autorizado"

```
✅ Verificar se seu telegram_id foi cadastrado:
   python setup_telegram_user.py <seu_telegram_id> "Seu Nome"

✅ Verificar no banco:
   sqlite3 financas.db "SELECT * FROM users"
```

### Erro "TELEGRAM_BOT_TOKEN não configurado"

```
✅ Verificar .env:
   cat .env | grep TELEGRAM_BOT_TOKEN

✅ Token correto (copie do @BotFather):
   TELEGRAM_BOT_TOKEN=1234567890:ABCdef...
```

---

## 🎯 Próximos Passos

- [ ] Sprint 4: Docker + EC2 (deploy produção)
- [ ] Sprint 5: Estabilização (monitoring, backups)
- [ ] MVP 4: Production Hardening (CI/CD, alertas)

---

**Desenvolvido com ❤️ usando LangGraph + python-telegram-bot**
