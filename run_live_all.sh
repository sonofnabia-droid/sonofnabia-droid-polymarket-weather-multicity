#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

MODE="${1:-interactive}"         # interactive | daemon | stop | status | logs
RUN_MODE="${2:-paper}"           # paper | real
INTERVAL="${3:-30}"

DEFAULT_CITIES="beijing,phoenix,las_vegas,buenos_aires,kuala_lumpur,miami,karachi"
CITIES="${CITIES:-$DEFAULT_CITIES}"
PID_FILE="${ROOT_DIR}/live_bot_logs/live_all.pid"
LOG_FILE="${ROOT_DIR}/live_bot_logs/live_all.log"

mkdir -p "${ROOT_DIR}/live_bot_logs"

if [[ -f "${ROOT_DIR}/venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/venv/bin/activate"
fi

cmd=(python live_bot.py --cities "$CITIES" --run "$RUN_MODE" --interval "$INTERVAL")

case "$MODE" in
  interactive)
    if [[ ! -t 1 ]]; then
      echo "Erro: modo interactive requer TTY (terminal interativo) para mostrar dashboard."
      echo "Usa sem pipe/redirect. Exemplo:"
      echo "  ./run_live_all.sh interactive paper 30"
      exit 1
    fi
    echo "A iniciar live_bot em modo interactive (dashboard ativa)..."
    echo "Cidades: $CITIES"
    exec "${cmd[@]}" --force-dashboard
    ;;

  daemon)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "Já existe live_all em execução (PID $(cat "$PID_FILE"))."
      exit 0
    fi
    echo "A iniciar live_bot em daemon (sem dashboard terminal)..."
    echo "Log: $LOG_FILE"
    nohup "${cmd[@]}" >"$LOG_FILE" 2>&1 &
    echo "$!" >"$PID_FILE"
    echo "PID $(cat "$PID_FILE")"
    ;;

  stop)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      kill "$(cat "$PID_FILE")"
      rm -f "$PID_FILE"
      echo "live_all parado."
    else
      echo "live_all não está em execução."
      rm -f "$PID_FILE"
    fi
    ;;

  status)
    if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "live_all a correr (PID $(cat "$PID_FILE"))."
      exit 0
    fi
    echo "live_all parado."
    exit 1
    ;;

  logs)
    touch "$LOG_FILE"
    tail -n 120 -f "$LOG_FILE"
    ;;

  *)
    echo "Uso:"
    echo "  ./run_live_all.sh [interactive|daemon|stop|status|logs] [paper|real] [interval_s]"
    echo
    echo "Exemplos:"
    echo "  ./run_live_all.sh interactive paper 30"
    echo "  ./run_live_all.sh daemon paper 30"
    echo "  CITIES='munich,dallas' ./run_live_all.sh interactive real 20"
    exit 2
    ;;
esac
