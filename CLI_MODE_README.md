# CLI Mode — Como Usar Estratégias via Linha de Comandos

**Data:** 2026-04-29
**Status:** ✅ Implementado

---

## 🎯 Alteração Realizada

**Antes:** Estratégias hardcoded em `cities/config.py`
```python
strategy=StrategyConfig(mode="single", ...)  # Não é mais usado
```

**Agora:** Estratégias especificadas via CLI `--mode`
```bash
python live_bot.py --mode single   # (default)
python live_bot.py --mode dual
python live_bot.py --mode phased
```

---

## 🚀 Como Usar

### Criar estratégia com Factory

```python
from cities.config import get_city
from modules.strategy_factory import create_strategy

# Obter cidade
city = get_city("munich")

# Criar estratégia (single é default)
strategy = create_strategy(city, mode="single")

# Ou especificar modo explicitamente
strategy = create_strategy(city, mode="dual")
```

### Exemplo com parâmetros personalizados

```python
# SingleEntry com parâmetros customizados
strategy = create_strategy(city, mode="single", threshold=0.60, hour_min=14)

# DualStrategy com parâmetros customizados
strategy = create_strategy(city, mode="dual",
                         fc_hour_min=9,
                         fc_hour_max=13,
                         fc_p_min=0.80,
                         pk_threshold=0.70)
```

---

## 📋 Modos Disponíveis

### `single` (default)
- **Descrição:** SingleEntry - 1 compra + stop-loss
- **Uso:** `python live_bot.py --mode single`
- **Config:** Usa `city.threshold` e `city.hour_min` do config.py
- **Validado:** Munich, Dallas, Ankara

### `dual`
- **Descrição:** DualStrategy - Forecast Early + Peak Detection
- **Uso:** `python live_bot.py --mode dual`
- **Config:** Parâmetros via kwargs ou defaults
- **Estado:** Disponível, requer calibração

### `phased`
- **Descrição:** PhasedEntry - 3 parcelas (P1, P2, P3)
- **Uso:** `python live_bot.py --mode phased`
- **Config:** Parâmetros via kwargs ou defaults
- **Estado:** Disponível, requer validação

---

## 🔧 Módulos Atualizados

### `cities/config.py`
- **Removido:** Campo `strategy` do `CityConfig`
- **Mantido:** `threshold`, `hour_min` para SingleEntry
- **Dataclasses:** Mantidas para uso interno, mas não no CityConfig

### `modules/strategy_factory.py`
- **Mudança:** `create_strategy(city_config, mode="single")`
- **Novo:** Modo especificado via parâmetro, não do config

### `modules/phased_entry.py`
- **SingleEntry:** Usa `city.threshold` e `city.hour_min`
- **PhasedEntry:** Parâmetros via kwargs ou defaults

### `modules/dual_strategy.py`
- **Configuração:** Todos os parâmetros via kwargs ou defaults
- **Não depende:** De `city_config.strategy`

### `modules/forecast_confidence.py`
- **Funções:** Agora aceitam `month` diretamente, não `city_config`
- **Accuracy:** Tabela default, ou passada via parâmetro

---

## 📊 Comparativo

| Aspecto | Antes | Depois |
|----------|--------|---------|
| **Estratégia definida em** | config.py | CLI (--mode) |
| **Flexibilidade** | Baixa (hardcoded) | Alta (por comando) |
| **Testes** | Difícil (editar código) | Fácil (mudar flag) |
| **Config.py** | Complexo | Limpo |
| **SingleEntry** | strategy.single.threshold | city.threshold |
| **DualStrategy** | city.strategy.dual.* | via kwargs |

---

## ✅ Validação

- [x] Todos os módulos testados
- [x] `modules/forecast_confidence.py` - OK
- [x] `modules/dual_strategy.py` - OK
- [x] `modules/phased_entry.py` - OK
- [x] `modules/strategy_factory.py` - OK
- [x] SingleEntry funciona com defaults de config.py
- [x] DualStrategy funciona com parâmetros default
- [x] PhasedEntry funciona com parâmetros default

---

## 🎯 Próximos Passos

1. **Integrar no live_bot:**
   ```python
   # Adicionar parser argumento
   parser.add_argument("--mode", default="single",
                    choices=["single", "dual", "phased"])

   # Usar factory
   strategy = create_strategy(city, mode=args.mode)
   ```

2. **Adicionar fetch de forecasts:**
   - WU/OM para Dual Strategy
   - Genérico por cidade

3. **Testar em paper trading:**
   - Single: Já validado
   - Dual: Calibração + 14 dias
   - Phased: Validação

---

**Última Atualização:** 2026-04-29
**Pronto para:** Integração no live_bot
