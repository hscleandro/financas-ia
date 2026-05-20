#!/bin/bash
# Script de controle do Telegram Bot

BOT_SCRIPT="main_telegram_polling.py"
LOG_FILE="/tmp/telegram_bot.log"
PID_FILE="/tmp/telegram_bot.pid"

case "$1" in
    start)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if ps -p $PID > /dev/null 2>&1; then
                echo "❌ Bot já está rodando (PID: $PID)"
                exit 1
            fi
        fi

        echo "🚀 Iniciando bot em background..."
        nohup python "$BOT_SCRIPT" > "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
        echo "✅ Bot iniciado (PID: $(cat $PID_FILE))"
        echo "📝 Logs: tail -f $LOG_FILE"
        ;;

    stop)
        if [ ! -f "$PID_FILE" ]; then
            echo "❌ PID file não encontrado. Tentando parar pelo nome..."
            pkill -f "$BOT_SCRIPT"
            echo "✅ Bot parado"
            exit 0
        fi

        PID=$(cat "$PID_FILE")
        if ps -p $PID > /dev/null 2>&1; then
            echo "🛑 Parando bot (PID: $PID)..."
            kill $PID
            sleep 2

            if ps -p $PID > /dev/null 2>&1; then
                echo "⚠️  Bot não respondeu, forçando..."
                kill -9 $PID
            fi

            rm -f "$PID_FILE"
            echo "✅ Bot parado"
        else
            echo "⚠️  Bot não está rodando (PID antigo: $PID)"
            rm -f "$PID_FILE"
        fi
        ;;

    restart)
        $0 stop
        sleep 2
        $0 start
        ;;

    status)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if ps -p $PID > /dev/null 2>&1; then
                echo "✅ Bot está rodando (PID: $PID)"
                echo ""
                echo "Últimas 10 linhas do log:"
                tail -10 "$LOG_FILE"
            else
                echo "❌ Bot não está rodando (PID antigo: $PID)"
                rm -f "$PID_FILE"
            fi
        else
            # Verificar se está rodando sem PID file
            PID=$(pgrep -f "$BOT_SCRIPT")
            if [ -n "$PID" ]; then
                echo "⚠️  Bot está rodando mas sem PID file (PID: $PID)"
                echo $PID > "$PID_FILE"
            else
                echo "❌ Bot não está rodando"
            fi
        fi
        ;;

    logs)
        if [ ! -f "$LOG_FILE" ]; then
            echo "❌ Arquivo de log não encontrado: $LOG_FILE"
            exit 1
        fi

        if [ "$2" == "follow" ] || [ "$2" == "-f" ]; then
            tail -f "$LOG_FILE"
        else
            tail -50 "$LOG_FILE"
        fi
        ;;

    *)
        echo "Uso: $0 {start|stop|restart|status|logs [follow]}"
        echo ""
        echo "Comandos:"
        echo "  start    - Inicia o bot em background"
        echo "  stop     - Para o bot"
        echo "  restart  - Reinicia o bot"
        echo "  status   - Verifica se o bot está rodando"
        echo "  logs     - Mostra últimas 50 linhas do log"
        echo "  logs -f  - Acompanha o log em tempo real"
        exit 1
        ;;
esac
