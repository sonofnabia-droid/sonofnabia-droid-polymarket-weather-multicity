# Protocolo de controlos — 15/11/2026

O caso Lucknow de 25/04 é exploratório e foi escolhido após se conhecer a divergência. Não entra na avaliação confirmatória.

## Seleção antes de observar resultados

Para cada cidade, considerar em ordem cronológica os dias de 05/03 a 17/07/2026, período de sobreposição WU/METAR descrito no plano. Selecionar o primeiro dia elegível de cada semana ISO, independentemente do movimento de preços e do resultado; Lucknow e Munique são analisadas separadamente. Reservar as últimas quatro semanas elegíveis como holdout, sem examinar os seus movimentos durante a definição da análise. Reportar todos os dias excluídos e motivo.

Elegibilidade: evento e tokens identificados; regra e estado de resolução arquivados; observações originais suficientes para reconstruir a sequência intradiária; preços 5m disponíveis para a bracket candidata e adjacentes nas janelas examinadas. A confirmação da fonte oficial de settlement é necessária para avaliar acerto; dias sem confirmação mantêm-se apenas na análise descritiva. Documentar cobertura e lacunas antes de aplicar filtros meteorológicos. Não assumir que METAR substitui a fonte oficial WU.

## Medição e limitações

Usar uma observação de máximo acumulado novo por dia: o primeiro aumento após as 12:00 locais, com janela de preços de 30 minutos antes e depois; incluir dias sem aumento como categoria separada. Associar o último preço com timestamp anterior ao instante avaliado, idade máxima de 10 minutos, conservando timestamps originais e missing. Reportar mudanças em pontos percentuais por contrato/dia e cobertura, sem assumir execução. Estimar intervalos por bootstrap de dias apenas após existir amostra suficiente; não selecionar limiares pelo holdout.

O CSV fornece hora de observação e não comprova hora de publicação. Assim, a análise é alinhada ao horário de observação e não identifica causalidade ou latência. Testar deslocamentos hipotéticos de 0, 15, 30 e 60 minutos como sensibilidade, sem os apresentar como publicação verificada. Nenhum resultado serve para P&L ou promoção a PAPER.

## Evidência local do contrato piloto

O `raw_json` arquivado do mercado Lucknow 43°C de 25/04 identifica Wunderground, estação Chaudhary Charan Singh Intl/VILK, e precisão inteira em Celsius; exige finalização dos dados e exclui revisões posteriores. O registo indica `closed=true` e preços de resolução YES/NO `[1,0]`. É metadata arquivada, não prova independente do instante de finalização ou do conteúdo histórico final da fonte. O CSV METAR tem 43°C às 09:00 UTC, mas não prova por si o valor oficial WU nem a hora de publicação.

Antes de executar a extensão: inventariar cobertura com consultas indexadas e confirmar o orçamento de tempo e disco. Validar a resolução de cada contrato e obter evidência de disponibilidade quando existir; reportar explicitamente os casos sem essa evidência.
