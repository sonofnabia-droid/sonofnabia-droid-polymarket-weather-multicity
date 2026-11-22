# Diário de decisões — auditoria Shadow (2026-11-17)

- Auditoria read-only: reconciliados custos de taker da Shadow com a fórmula Weather publicada pela Polymarket e auditada a proveniência temporal do `opportunity_logger`/`shadow_ledger`.
- Cortes horários e “primeiro sinal do dia” derivados de `captured_at` foram descartados como inválidos para inferência intradiária: a captura é horária e pode diferir até cerca de 1h do evento; o match do ledger usa amostra próxima até ±90 min.
- Os retornos fixos recalculados em `REPORT.md` são apenas diagnósticos: preços hipotéticos, múltiplos brackets por contrato, sem política de seleção, asks/depth/fills nem validação independente dos labels. Não promovem uma estratégia.
- Estado de processos não confirmado nesta sessão (sem servidor tmux acessível e sem processo nomeado identificado). Nenhum processo foi iniciado ou alterado.
- Próximo passo: reconstruir timestamps/eventos causais e definir uma decisão única por contrato antes de qualquer estimativa económica; exigir preços executáveis e labels de settlement verificados. Manter investigação isolada e sem downloads.
