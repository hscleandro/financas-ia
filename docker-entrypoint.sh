#!/bin/bash
set -e

# Se um comando foi passado explicitamente (ex: setup_telegram_user.py),
# executa esse comando em vez de iniciar o bot.
if [ $# -gt 0 ]; then
    exec "$@"
fi

echo "🚀 Iniciando Finanças IA Bot..."
echo "📂 Diretório: $(pwd)"
echo "🔧 Modo: ${BOT_MODE}"

# Verificar variáveis obrigatórias
if [ -z "$OPENAI_API_KEY" ]; then
    echo "❌ ERRO: OPENAI_API_KEY não configurado"
    exit 1
fi

if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "❌ ERRO: TELEGRAM_BOT_TOKEN não configurado"
    exit 1
fi

# Executar baseado no modo
case "$BOT_MODE" in
    polling)
        echo "📡 Iniciando em modo POLLING (desenvolvimento)..."
        exec python main_telegram_polling.py
        ;;
    webhook)
        echo "🌐 Iniciando em modo WEBHOOK (produção)..."
        exec uvicorn api.webhook:app --host 0.0.0.0 --port 8000
        ;;
    *)
        echo "❌ ERRO: BOT_MODE inválido: $BOT_MODE"
        echo "   Use: 'polling' ou 'webhook'"
        exit 1
        ;;
esac
