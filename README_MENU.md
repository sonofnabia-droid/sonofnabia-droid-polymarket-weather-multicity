# Menu Interativo do Telegram Bot 🤖

Este menu transforma seu bot de trading de um "emissor" (apenas envia alertas) para um "ouvinte" (responde a comandos), permitindo interação direta com o bot via Telegram.

## 🎯 Funcionalidades

### Comandos Disponíveis
- `/menu` - Mostra menu interativo com botões
- `/resumo` - Resumo do dia: PnL, nº de apostas, % win rate
- `/posicoes` - Posições abertas atuais (paper e real)
- `/ultimas` - Últimas 5 vitórias
- `/status` - Status do bot em todas as cidades

### Recursos
- 📊 **Dashboard Interativo**: Botões clicáveis para navegação fácil
- 📱 **Respostas em Tempo Real**: Dados atualizados a cada interação
- 📂 **Gerenciamento de Posições**: Visualização clara de posições abertas
- 📈 **Estatísticas Detalhadas**: PnL, win rate, ROI calculados automaticamente
- 🏆 **Histórico de Vitórias**: Últimos trades bem-sucedidos
- ⚙️ **Monitoramento**: Status do bot em todas as cidades

## 🚀 Como Usar

### 1. Configuração Inicial
```bash
# Configurar variáveis de ambiente
export TELEGRAM_TOKEN=seu_token_aqui
export TELEGRAM_CHAT_ID=seu_chat_id_aqui
```

### 2. Iniciar o Bot
```bash
# Iniciar o bot com menu interativo
python live_bot.py --cities munich --mode single --run paper
```

### 3. Usar no Telegram
1. Envie `/menu` no Telegram
2. Clique nos botões para ver detalhes
3. As informações são atualizadas automaticamente

## 📊 Estrutura de Arquivos

### Arquivos Modificados
- `tg.py` - Adicionado suporte a polling e comandos
- `live_bot.py` - Integrado menu ao loop principal

### Arquivos de Dados Utilizados
- `live_bot_logs/trade_ledger.jsonl` - Histórico de trades
- `live_bot_logs/paper_positions.json` - Posições paper trading
- `live_bot_logs/real_positions.json` - Posições real trading

## 🧪 Testes

### Testar Funcionalidade
```bash
python test_menu.py
```

### Ver Demonstração
```bash
python demo_menu.py
```

## 🎨 Exemplos de Mensagens

### Resumo do Dia
```
📊 Resumo de Hoje — 2026-06-10

  🎯 Trades: 12
  💰 Investido: $1,200.00
  📈 PnL: +$45.50 (+3.8%)
  🏆 Win Rate: 58.3% (7/12)

Detalhes dos trades:
  ✅ munich: [munich] bracket_25-30 (+$12.50)
  ❌ dallas: [dallas] bracket_20-25 (-$8.30)
  ...
```

### Posições Abertas
```
📂 Posições Abertas

📂 munich
  🎯 [munich] bracket_25-30
  💵 Entrada: 28.5¢
  🏦 Size: $50.00

💰 dallas
  🎯 [dallas] bracket_20-25
  💵 Entrada: 22.3¢
  🏦 Size: $100.00
```

### Últimas Vitórias
```
🏆 Últimas 5 Vitórias

🥇 1. munich — 2026-06-10
   🎯 [munich] bracket_25-30
   💵 Entrada: 28.5¢
   📈 PnL: +$12.50

🥇 2. berlin — 2026-06-10
   🎯 [berlin] bracket_30-35
   💵 Entrada: 32.1¢
   📈 PnL: +$18.75
```

### Status do Bot
```
⚙️ Status do Bot

🟢 munich
   📊 Trades: 8
   💰 PnL: +$25.30

🔴 dallas
   📊 Trades: 5
   💰 PnL: -$12.80

🤖 Bot está ativo e monitorando as cidades.
```

## 🔧 Configuração Avançada

### Modo Compatibilidade
Se `python-telegram-bot` não estiver instalado, o bot funciona em modo compatibilidade:
```bash
# Apenas envio de mensagens (sem menu interativo)
pip install python-telegram-bot
```

### Personalização
Você pode modificar os templates de mensagens em `tg.py`:
- `_generate_daily_summary()` - Formato do resumo
- `_get_open_positions()` - Formato das posições
- `_get_recent_wins()` - Formato das vitórias
- `_get_bot_status()` - Formato do status

## 🐛 Troubleshooting

### Problemas Comuns
1. **Menu não aparece**: Verificar se `python-telegram-bot` está instalado
2. **Comandos não funcionam**: Checar variáveis de ambiente `TELEGRAM_TOKEN` e `TELEGRAM_CHAT_ID`
3. **Dados vazios**: Aguardar alguns trades para preencher o histórico

### Logs
```bash
# Ver logs do Telegram
tail -f live_bot_logs/telegram.log
```

## 📈 Benefícios

1. **Controle Remoto**: Monitore seu bot de qualquer lugar
2. **Tomada de Decisão**: Veja posições abertas antes de agir
3. **Análise Rápida**: Acesse estatísticas sem precisar acessar arquivos
4. **Notificações Proativas**: Receba alertas de eventos importantes
5. **Interface Intuitiva**: Menu visual fácil de usar

## 🔄 Atualizações Futuras

- [ ] Notificações personalizadas
- [ ] Gráficos inline
- [ ] Alertas configuráveis
- [ ] Exportação de dados
- [ ] Integração com dashboards externos

---

**Nota**: O menu requer que o `live_bot.py` esteja rodando para funcionar. O polling é iniciado automaticamente quando o bot é iniciado.