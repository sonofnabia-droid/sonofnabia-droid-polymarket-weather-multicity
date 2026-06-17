# Guia de Uso - Enhanced Telegram Bot

## 🚀 Rápido Start

1. **Configurar Telegram**:
   ```bash
   export TELEGRAM_TOKEN="seu_token"
   export TELEGRAM_CHAT_ID="seu_chat_id"
   ```

2. **Testar bot**:
   ```bash
   python simplified_tg_bot.py
   ```

3. **Integrar com live_bot.py**:
   - Adicione telegram_integration.py ao live_bot.py
   - Modifique _get_tg() para usar EnhancedTGBot

## 📱 Relatórios Recebidos

Você receberá relatórios como:

```
🟡 Multi-City Trading Bot
📊 Relatório Periódico — 17:30
────────────────────────────────────

📈 Resumo Geral
   Modo: PAPER
   Total Trades: 0
   P&L Total: $+0.00
   P&L Diário: $+0.00
   Trades Diários: 0

🌍 Status por Cidade
   🟢 Ativas
   Madrid: 33.5°C (max 33.5°C) █████ 5.1%

🌡️ Temperaturas Máximas Atuais
   Karachi: 37.0°C @ 15:30
   Beijing: 34.2°C @ 17:30

🧠 Probabilidades de Pico
   🔥 Madrid: █████ 5.1%
   ⚡ Buenos_Aires: ███ 0.6%
```

## ⚙️ Configurações

- **Intervalo**: 30 minutos (configurável)
- **Formato**: HTML (para Telegram)
- **Cidades**: Todas as 14 cidades
- **Dados**: Tempo real do snapshot

## 🐛 Troubleshooting

1. **Bot não envia mensagens**:
   - Verificar token e chat ID
   - Checar variáveis de ambiente

2. **Dados desatualizados**:
   - Verificar live_bot_logs/live_snapshot.json
   - Checar se live_bot.py está rodando

3. **Erro de importação**:
   - Instalar python-telegram-bot: pip install python-telegram-bot
   - Ou usar versão simplificada

## 📊 Comandos Disponíveis

- `/menu` - Menu interativo
- `/status` - Status detalhado
- `/resumo` - Resumo do dia
- `/posicoes` - Posições abertas
- `/ultimas` - Últimas vitórias

## 🎯 Benefícios

- Monitoramento a cada 30 minutos
- Dashboard completo com todas as cidades
- Análise detalhada de probabilidades
- Alertas em tempo real
- Formatação profissional para Telegram
