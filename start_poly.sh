#!/bin/bash

cd ~/POLY-MULTI-CITY || exit 1

echo "Entrando em ~/POLY-MULTI-CITY..."

source venv/bin/activate

export TELEGRAM_TOKEN="8667652003:AAG2wPIJTpCJ4Yy6BLzFb4yLZMMXTfKQWyE"
export TELEGRAM_CHAT_ID="7743367116"
export WU_API_KEY="e1f10a1e78da46f5b10a1e78da96f525"
export POLY_PRIVATE_KEY="8132158a8d2239270ea93b8d9a2a1e0d548a5772ab9352701e0b8052ff3ba4bf"
export POLY_FUNDER="0x929DcC8d2d227E2da27Ef354DE5571E717aC9495"
export POLY_SIGNATURE_TYPE="2"

echo "Ambiente POLY carregado."
echo "Sessão tmux pronta em ~/POLY-MULTI-CITY"
echo

exec bash
