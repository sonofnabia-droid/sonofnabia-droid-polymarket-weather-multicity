# Instruções de melhoria — bot de previsão de temperatura (Polymarket)

> Documento de especificação técnica para implementação por Codex.  
> Arquitectura base: LightGBM, Open-Meteo + Weather Underground, `py_clob_client`, walk-forward CV.  
> Todas as alterações devem ser compatíveis com a estrutura existente de `munich_live_bot.py` generalizada para multi-cidade.

---

## Índice

1. [Filtros de entrada — reduzir sinais prematuros](#1-filtros-de-entrada)
2. [Feature engineering — meteorologia adicional](#2-feature-engineering)
3. [Modelos por estação](#3-modelos-por-estação)
4. [Gestão de capital — Kelly variável e filtros de odds](#4-gestão-de-capital)
5. [Configuração por cidade](#5-configuração-por-cidade)
6. [Testes e validação](#6-testes-e-validação)

---

## 1. Filtros de entrada

### 1.1 Threshold de confiança mínima por cidade

**Contexto:** O modelo dispara sinal quando `P(pico) >= global_threshold`. Cidades como Phoenix (premature 71.6%) e Las Vegas (77.4%) precisam de um threshold mais exigente. Cidades como Moscow devem manter threshold baixo pois a selectividade é a estratégia.

**O que implementar:**

Adicionar ao ficheiro de configuração (ex. `config.py` ou `cities.json`) um campo `min_conf` por cidade:

```python
CITY_CONFIG = {
    "phoenix":     {"min_conf": 0.68, "max_lag_h": 1.0, "max_entry_hour": 16},
    "las_vegas":   {"min_conf": 0.70, "max_lag_h": 1.0, "max_entry_hour": 16},
    "dallas":      {"min_conf": 0.62, "max_lag_h": 1.1, "max_entry_hour": 17},
    "karachi":     {"min_conf": 0.60, "max_lag_h": 0.9, "max_entry_hour": 17},
    "buenos_aires":{"min_conf": 0.62, "max_lag_h": 1.0, "max_entry_hour": 17},
    "tel_aviv":    {"min_conf": 0.52, "max_lag_h": 0.9, "max_entry_hour": 18},
    "miami":       {"min_conf": 0.50, "max_lag_h": 1.0, "max_entry_hour": 18},
    "singapore":   {"min_conf": 0.50, "max_lag_h": 1.0, "max_entry_hour": 18},
    "ankara":      {"min_conf": 0.50, "max_lag_h": 0.6, "max_entry_hour": 18},
    "moscow":      {"min_conf": 0.35, "max_lag_h": 0.9, "max_entry_hour": 18},
    # ... restantes cidades com defaults
}

DEFAULT_CONFIG = {"min_conf": 0.52, "max_lag_h": 1.0, "max_entry_hour": 17}
```

Na função de decisão de entrada (`should_enter_position` ou equivalente):

```python
def should_enter_position(city: str, p_peak: float, current_hour: int, estimated_lag_h: float) -> bool:
    cfg = CITY_CONFIG.get(city, DEFAULT_CONFIG)
    
    if p_peak < cfg["min_conf"]:
        logger.info(f"[{city}] Sinal rejeitado: P={p_peak:.3f} < min_conf={cfg['min_conf']}")
        return False
    
    if estimated_lag_h > cfg["max_lag_h"]:
        logger.info(f"[{city}] Sinal rejeitado: lag estimado {estimated_lag_h:.2f}h > max={cfg['max_lag_h']}h")
        return False
    
    if current_hour > cfg["max_entry_hour"]:
        logger.info(f"[{city}] Sinal rejeitado: hora {current_hour}h > max_entry={cfg['max_entry_hour']}h")
        return False
    
    return True
```

---

### 1.2 Filtro de persistência do sinal

**Contexto:** Evitar entrar num sinal que aparece e desaparece em minutos. O sinal deve manter-se acima do threshold durante uma janela mínima antes de abrir posição.

**O que implementar:**

Manter um buffer de histórico de P(pico) por cidade. O sinal só é confirmado se estiver acima do threshold durante `min_persistence_minutes` consecutivos.

```python
from collections import deque
from datetime import datetime, timedelta

class SignalPersistenceFilter:
    def __init__(self, min_persistence_minutes: int = 10):
        self.min_persistence = timedelta(minutes=min_persistence_minutes)
        # city -> deque de (timestamp, p_value)
        self._history: dict[str, deque] = {}
    
    def update(self, city: str, p_value: float, threshold: float) -> bool:
        """
        Actualiza o histórico e retorna True se o sinal persiste
        acima do threshold durante o período mínimo.
        """
        now = datetime.utcnow()
        
        if city not in self._history:
            self._history[city] = deque()
        
        buf = self._history[city]
        buf.append((now, p_value))
        
        # Remover entradas antigas (> 2x o período de persistência)
        cutoff = now - 2 * self.min_persistence
        while buf and buf[0][0] < cutoff:
            buf.popleft()
        
        # Verificar se todos os pontos dentro do período estão acima do threshold
        window_start = now - self.min_persistence
        window_points = [(t, p) for t, p in buf if t >= window_start]
        
        if not window_points:
            return False
        
        first_in_window = window_points[0][0]
        window_duration = now - first_in_window
        
        if window_duration < self.min_persistence:
            return False  # janela ainda não completa
        
        all_above = all(p >= threshold for _, p in window_points)
        return all_above
    
    def reset(self, city: str):
        """Chamar quando uma posição é aberta ou cancelada."""
        self._history.pop(city, None)

# Instanciar uma vez e partilhar entre o loop de monitorização
signal_filter = SignalPersistenceFilter(min_persistence_minutes=10)
```

---

### 1.3 Feature de momentum de temperatura

**Contexto:** Se a temperatura está em plateau ou a descer, o sinal é prematuro mesmo que P(pico) seja alto. Adicionar derivadas temporais como features ao modelo.

**O que implementar:**

Na função de preparação de features (`build_features` ou equivalente), adicionar:

```python
def compute_temperature_momentum(temp_series: list[float], timestamps: list[datetime]) -> dict:
    """
    Recebe as últimas N leituras de temperatura e retorna features de momentum.
    temp_series e timestamps devem estar ordenados do mais antigo para o mais recente.
    """
    if len(temp_series) < 3:
        return {
            "temp_delta_30m": 0.0,
            "temp_delta_60m": 0.0,
            "temp_acceleration": 0.0,
            "is_plateau": False,
            "minutes_since_last_peak": 999,
        }
    
    now = timestamps[-1]
    temps = temp_series
    
    # Delta nos últimos 30 e 60 minutos
    def temp_at_offset(minutes_ago: int) -> float | None:
        target = now - timedelta(minutes=minutes_ago)
        # encontrar o ponto mais próximo
        closest = min(zip(timestamps, temps), key=lambda x: abs(x[0] - target))
        if abs(closest[0] - target) > timedelta(minutes=15):
            return None
        return closest[1]
    
    t30 = temp_at_offset(30)
    t60 = temp_at_offset(60)
    t_now = temps[-1]
    
    delta_30 = (t_now - t30) if t30 is not None else 0.0
    delta_60 = (t_now - t60) if t60 is not None else 0.0
    
    # Aceleração aproximada (2ª derivada)
    acceleration = delta_30 - (delta_60 - delta_30) if t60 is not None else 0.0
    
    # Detectar plateau: variação < 0.3°C nos últimos 30 min
    is_plateau = abs(delta_30) < 0.3
    
    # Minutos desde o máximo local
    max_temp = max(temps[-12:]) if len(temps) >= 12 else max(temps)  # últimas ~1h
    max_idx = temps.index(max_temp) if max_temp in temps else -1
    if max_idx >= 0:
        minutes_since_peak = (now - timestamps[max_idx]).total_seconds() / 60
    else:
        minutes_since_peak = 0
    
    return {
        "temp_delta_30m": round(delta_30, 2),
        "temp_delta_60m": round(delta_60, 2),
        "temp_acceleration": round(acceleration, 3),
        "is_plateau": int(is_plateau),
        "minutes_since_last_peak": round(minutes_since_peak, 1),
    }
```

Integrar no filtro de entrada — **bloquear entrada se temperatura está em plateau ou a descer:**

```python
def momentum_allows_entry(momentum: dict, city: str) -> bool:
    # Se plateau e já passou do meio-dia local, provavelmente o pico já passou
    if momentum["is_plateau"] and momentum["minutes_since_last_peak"] > 45:
        logger.info(f"[{city}] Bloqueado por plateau: {momentum['minutes_since_last_peak']:.0f}min desde pico local")
        return False
    
    # Se temperatura está a descer significativamente
    if momentum["temp_delta_30m"] < -0.8:
        logger.info(f"[{city}] Bloqueado: temperatura a descer {momentum['temp_delta_30m']}°C/30min")
        return False
    
    return True
```

---

## 2. Feature Engineering

### 2.1 Cobertura de nuvens (Open-Meteo)

**Contexto:** A cobertura de nuvens é o preditor mais directo do pico de temperatura. O Open-Meteo fornece `cloud_cover` em percentagem hora-a-hora sem custo.

**Endpoint a usar:**

```
https://api.open-meteo.com/v1/forecast?
  latitude={lat}&longitude={lon}
  &hourly=cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high
  &forecast_days=1
  &timezone=auto
```

**O que implementar:**

```python
import httpx
from functools import lru_cache

async def fetch_cloud_cover(lat: float, lon: float, timezone: str) -> dict:
    """
    Retorna features de cloud cover para o dia actual.
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high",
        "forecast_days": 1,
        "timezone": timezone,
    }
    
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    
    hourly = data["hourly"]
    hours = hourly["time"]  # lista de strings "2026-05-17T00:00"
    cc = hourly["cloud_cover"]
    cc_low = hourly["cloud_cover_low"]
    
    # Calcular features agregadas para as horas de pico (10h-16h local)
    peak_hours_idx = [i for i, h in enumerate(hours) if 10 <= int(h[11:13]) <= 16]
    
    cc_peak_mean = sum(cc[i] for i in peak_hours_idx) / max(len(peak_hours_idx), 1)
    cc_peak_max  = max((cc[i] for i in peak_hours_idx), default=0)
    cc_now_idx   = min(range(len(hours)), key=lambda i: abs(
        datetime.fromisoformat(hours[i]) - datetime.now()
    ))
    
    # Tendência: diferença entre cloud cover actual e média das próximas 3h
    future_idx = [j for j in range(cc_now_idx, min(cc_now_idx + 4, len(cc)))]
    cc_trend = (sum(cc[j] for j in future_idx) / max(len(future_idx), 1)) - cc[cc_now_idx]
    
    return {
        "cloud_cover_now":       cc[cc_now_idx],
        "cloud_cover_peak_mean": round(cc_peak_mean, 1),
        "cloud_cover_peak_max":  cc_peak_max,
        "cloud_cover_low_now":   cc_low[cc_now_idx],
        "cloud_cover_trend_3h":  round(cc_trend, 1),  # positivo = mais nuvens a chegar
    }
```

**Features a adicionar ao DataFrame de treino:**

| Feature | Tipo | Descrição |
|---|---|---|
| `cloud_cover_now` | float 0–100 | % cobertura no momento do sinal |
| `cloud_cover_peak_mean` | float 0–100 | Média de cobertura nas horas de pico |
| `cloud_cover_peak_max` | float 0–100 | Máximo de cobertura nas horas de pico |
| `cloud_cover_trend_3h` | float | Positivo = mais nuvens, negativo = a clarear |
| `cloud_cover_low_now` | float 0–100 | Nuvens baixas (mais impacto na temperatura) |

---

### 2.2 Pressão atmosférica e ponto de orvalho

**Endpoint Open-Meteo (adicionar ao mesmo pedido):**

```
&hourly=surface_pressure,dewpoint_2m,relative_humidity_2m,windspeed_10m
```

**Features a calcular:**

```python
def compute_pressure_features(pressure_series: list[float], hours: list[str]) -> dict:
    """
    Pressão alta e a subir → dia claro → pico mais alto.
    """
    if len(pressure_series) < 4:
        return {"pressure_now": 1013.0, "pressure_trend_3h": 0.0, "pressure_regime": 0}
    
    p_now = pressure_series[-1]
    p_3h_ago_idx = max(0, len(pressure_series) - 4)
    p_3h_ago = pressure_series[p_3h_ago_idx]
    
    trend = p_now - p_3h_ago  # positivo = pressão a subir = bom sinal
    
    # Regime: 0=baixa, 1=normal, 2=alta
    regime = 0 if p_now < 1005 else (2 if p_now > 1020 else 1)
    
    return {
        "pressure_now":      round(p_now, 1),
        "pressure_trend_3h": round(trend, 2),
        "pressure_regime":   regime,
    }

def compute_dewpoint_features(temp_now: float, dewpoint_now: float, humidity_now: float) -> dict:
    """
    Diferença entre temperatura e ponto de orvalho indica margem disponível para subir.
    Temperatura alta + dewpoint baixo = pode subir mais.
    """
    spread = temp_now - dewpoint_now  # quanto maior, mais "seco" e mais pode subir
    
    return {
        "temp_dewpoint_spread": round(spread, 2),
        "relative_humidity":    round(humidity_now, 1),
        "high_humidity_flag":   int(humidity_now > 75),  # humidade alta limita o pico
    }
```

---

### 2.3 Divergência forecast vs actual

**Contexto:** Se o forecast meteorológico previu 38° e a temperatura actual está em 32° às 13h, é sinal de que o pico pode não ser atingido. Esta divergência deve ser capturada como feature.

**O que implementar:**

```python
def compute_forecast_divergence(
    forecast_max: float,      # previsão do máximo diário emitida de manhã
    actual_current: float,    # temperatura actual
    target_bracket: float,    # bracket do mercado Polymarket
    current_hour: int,        # hora local actual
) -> dict:
    """
    Quantifica o quanto a realidade se está a desviar do forecast.
    """
    # Progresso esperado: a que % do máximo diário devemos estar a esta hora?
    # Modelo simplificado: pico tipicamente às 14h-15h
    expected_fraction_at_hour = {
        8: 0.55, 9: 0.65, 10: 0.72, 11: 0.80,
        12: 0.88, 13: 0.94, 14: 1.00, 15: 0.98,
        16: 0.92, 17: 0.85, 18: 0.75,
    }
    fraction = expected_fraction_at_hour.get(current_hour, 0.9)
    expected_now = forecast_max * fraction
    
    divergence = actual_current - expected_now  # negativo = abaixo do esperado
    
    # Probabilidade implícita de atingir o target dado o ritmo actual
    # Se estamos abaixo do esperado às 12h, o target está em risco
    implied_max = actual_current / fraction if fraction > 0 else actual_current
    implied_probability = 1.0 if implied_max >= target_bracket else (implied_max / target_bracket)
    
    return {
        "forecast_divergence":      round(divergence, 2),
        "implied_max_from_current": round(implied_max, 1),
        "forecast_on_track":        int(divergence >= -1.0),  # dentro de 1° do esperado
        "implied_target_prob":      round(min(implied_probability, 1.0), 3),
    }
```

---

### 2.4 Fourier terms para sazonalidade (substituir polinómio DOY)

**Contexto:** O polinómio de grau N sobre o DOY tem descontinuidades e overfitting nos extremos. Fourier terms capturam a sazonalidade de forma mais robusta.

**O que implementar:**

```python
import numpy as np

def add_fourier_features(df, date_col: str = "date", n_harmonics: int = 3) -> None:
    """
    Adiciona Fourier terms ao DataFrame.
    Modifica df in-place adicionando colunas sin_k e cos_k para k=1..n_harmonics.
    
    Args:
        df: DataFrame com coluna de datas
        date_col: nome da coluna de data
        n_harmonics: número de pares sin/cos (3 é suficiente para sazonalidade anual)
    """
    doy = df[date_col].dt.dayofyear.values  # 1..365
    period = 365.25
    
    for k in range(1, n_harmonics + 1):
        df[f"sin_{k}"] = np.sin(2 * np.pi * k * doy / period)
        df[f"cos_{k}"] = np.cos(2 * np.pi * k * doy / period)
    
    # Remover colunas antigas de polinómio DOY se existirem
    poly_cols = [c for c in df.columns if c.startswith("doy_poly_")]
    if poly_cols:
        df.drop(columns=poly_cols, inplace=True)

# Features resultantes (n_harmonics=3):
# sin_1, cos_1  → ciclo anual básico (verão/inverno)
# sin_2, cos_2  → semi-anual (dois picos por ano)
# sin_3, cos_3  → trimestral (refinamento)
```

---

## 3. Modelos por Estação

### 3.1 Separação em dois modelos (inverno/verão)

**Contexto:** Cidades temperadas (Munich, Warsaw, Madrid, Taipei, Moscow) têm dinâmicas de temperatura radicalmente diferentes entre inverno e verão. Um único modelo faz compromissos que prejudicam ambos os períodos.

**O que implementar:**

```python
from enum import Enum

class Season(Enum):
    WINTER = "winter"  # meses frios
    SUMMER = "summer"  # meses quentes

CITY_SEASON_MONTHS = {
    # Hemisfério Norte
    "munich":  {Season.WINTER: [11,12,1,2,3], Season.SUMMER: [5,6,7,8,9]},
    "warsaw":  {Season.WINTER: [11,12,1,2,3], Season.SUMMER: [5,6,7,8,9]},
    "madrid":  {Season.WINTER: [12,1,2,3],    Season.SUMMER: [5,6,7,8,9,10]},
    "moscow":  {Season.WINTER: [10,11,12,1,2,3,4], Season.SUMMER: [6,7,8,9]},
    "taipei":  {Season.WINTER: [12,1,2,3],    Season.SUMMER: [5,6,7,8,9,10]},
    "beijing": {Season.WINTER: [11,12,1,2,3], Season.SUMMER: [5,6,7,8,9]},
    # Cidades tropicais/subtropicais: usar modelo único (sem separação)
    "singapore":    None,
    "jakarta":      None,
    "kuala_lumpur": None,
    "karachi":      None,
    "lagos":        None,
    "miami":        None,
}

def get_season(city: str, month: int) -> Season | None:
    """Retorna a estação para uma cidade e mês, ou None se cidade tropical."""
    mapping = CITY_SEASON_MONTHS.get(city)
    if mapping is None:
        return None  # cidade tropical — modelo único
    
    for season, months in mapping.items():
        if month in months:
            return season
    
    return None  # meses de transição — pode usar modelo mais próximo

def train_seasonal_models(city: str, df_full) -> dict:
    """
    Treina até dois modelos por cidade (winter/summer) ou um único para tropicais.
    Retorna dict com Season -> modelo treinado.
    """
    models = {}
    
    season_config = CITY_SEASON_MONTHS.get(city)
    
    if season_config is None:
        # Cidade tropical: treinar modelo único
        models[None] = train_lgbm(df_full, city=city)
    else:
        for season, months in season_config.items():
            df_season = df_full[df_full["month"].isin(months)]
            if len(df_season) < 365:
                # Amostra insuficiente — usar modelo global como fallback
                models[season] = train_lgbm(df_full, city=city)
            else:
                models[season] = train_lgbm(df_season, city=city)
    
    return models

def predict_with_seasonal_model(models: dict, city: str, features, month: int) -> float:
    """Selecciona o modelo correcto para a estação actual e faz previsão."""
    season = get_season(city, month)
    
    model = models.get(season) or models.get(None)
    if model is None:
        raise ValueError(f"Nenhum modelo disponível para {city} / season={season}")
    
    return float(model.predict([features])[0])
```

---

### 3.2 Detector de regime (ADWIN)

**Contexto:** Quando o modelo começa a errar sistematicamente nas últimas N previsões, pode indicar mudança de regime climático (início de onda de calor, mudança de padrão sinóptico). O threshold deve ser ajustado dinamicamente.

**O que implementar:**

Instalar `river` se ainda não estiver no ambiente:

```bash
pip install river
```

```python
from river.drift import ADWIN
from collections import defaultdict

class RegimeDetector:
    """
    Detecta drift no desempenho do modelo por cidade.
    Quando detectado, aumenta o threshold temporariamente.
    """
    
    def __init__(self, base_threshold_multiplier: float = 1.15):
        self.detectors: dict[str, ADWIN] = defaultdict(lambda: ADWIN(delta=0.002))
        self.drift_active: dict[str, bool] = defaultdict(bool)
        self.base_multiplier = base_threshold_multiplier
    
    def update(self, city: str, was_correct: bool) -> bool:
        """
        Actualizar com o resultado da última previsão.
        Retorna True se drift detectado.
        """
        detector = self.detectors[city]
        # ADWIN recebe 1 para acerto, 0 para erro
        detector.update(int(was_correct))
        
        if detector.drift_detected:
            self.drift_active[city] = True
            logger.warning(f"[{city}] Drift detectado — aumentar threshold temporariamente")
            return True
        
        # Reset após 30 dias de bom desempenho (aprox.)
        # Em prática, implementar contador de dias sem drift
        return False
    
    def get_threshold_multiplier(self, city: str) -> float:
        """Retorna o multiplicador do threshold para esta cidade."""
        return self.base_multiplier if self.drift_active.get(city) else 1.0
    
    def reset_drift(self, city: str):
        """Chamar manualmente quando o modelo é re-treinado."""
        self.drift_active[city] = False
        self.detectors[city] = ADWIN(delta=0.002)

# Usar no loop principal:
regime_detector = RegimeDetector()

# Após resolver cada dia:
regime_detector.update(city, was_correct=trade_resolved_yes)
multiplier = regime_detector.get_threshold_multiplier(city)
effective_threshold = base_threshold * multiplier
```

---

## 4. Gestão de Capital

### 4.1 Kelly fraccionado por confiança

**Contexto:** Actualmente o stake é flat. O Kelly fraccionado proporcional a P(pico) maximiza o crescimento da bankroll sem assumir risco excessivo quando a confiança é baixa.

**O que implementar:**

```python
def kelly_stake(
    p_win: float,           # probabilidade estimada pelo modelo (P(pico))
    market_odds: float,     # odds do mercado em formato decimal (ex: 1.95 para 51.3¢)
    bankroll: float,        # saldo disponível em USDC
    kelly_fraction: float = 0.25,   # fracção conservadora (full Kelly é muito agressivo)
    min_stake: float = 1.0,
    max_stake: float = 50.0,
) -> float:
    """
    Calcula o stake óptimo usando Kelly fraccionado.
    
    Kelly: f = (p * b - q) / b
    onde b = odds - 1 (lucro por unidade apostada), q = 1 - p
    """
    b = market_odds - 1.0  # lucro por unidade se ganhar
    q = 1.0 - p_win
    
    kelly_full = (p_win * b - q) / b
    
    if kelly_full <= 0:
        # Sem edge — não apostar
        logger.info(f"Kelly negativo ({kelly_full:.4f}) — sem edge, a saltar")
        return 0.0
    
    stake = kelly_fraction * kelly_full * bankroll
    stake = max(min_stake, min(stake, max_stake))
    stake = round(stake, 2)
    
    logger.info(
        f"Kelly: p={p_win:.3f}, odds={market_odds:.2f}, "
        f"kelly_full={kelly_full:.4f}, stake=${stake:.2f}"
    )
    return stake

# Exemplo de uso:
# p_peak = 0.72 (modelo diz 72% de probabilidade de atingir target)
# market_price = 0.58  (mercado está a 58¢, portanto odds = 1/0.58 = 1.724)
# stake = kelly_stake(p_win=0.72, market_odds=1/0.58, bankroll=500.0)
```

---

### 4.2 Filtro de odds mínimas (edge mínimo)

**Contexto:** Se o mercado já precificou o resultado provável (odds baixas), o edge do modelo foi consumido. Não vale entrar.

**O que implementar:**

```python
def has_sufficient_edge(
    p_model: float,        # probabilidade do modelo
    market_price_cents: float,  # preço actual do mercado em cents (0-100)
    min_edge: float = 0.08,     # edge mínimo em probabilidade
) -> bool:
    """
    Verifica se existe edge suficiente entre o modelo e o mercado.
    
    Edge = P(modelo) - P(mercado)
    """
    p_market = market_price_cents / 100.0
    edge = p_model - p_market
    
    if edge < min_edge:
        logger.info(
            f"Edge insuficiente: modelo={p_model:.3f}, mercado={p_market:.3f}, "
            f"edge={edge:.3f} < min={min_edge}"
        )
        return False
    
    logger.info(f"Edge OK: {edge:.3f} (modelo={p_model:.3f}, mercado={p_market:.3f})")
    return True

# Configuração por cidade (cidades com mercados mais eficientes precisam de min_edge maior)
CITY_MIN_EDGE = {
    "tel_aviv":   0.10,
    "miami":      0.08,
    "singapore":  0.08,
    "ankara":     0.07,
    "karachi":    0.09,
    "phoenix":    0.12,   # mercado muito eficiente nesta cidade
    "las_vegas":  0.12,
}
DEFAULT_MIN_EDGE = 0.08
```

---

### 4.3 Stop dinâmico por temperatura

**Contexto:** Se o sinal disparou mas a temperatura estabilizou abaixo do target, fechar a posição evita perder o valor total do trade.

**O que implementar:**

```python
class DynamicStopManager:
    """
    Monitoriza posições abertas e decide se deve fechar com base
    na evolução da temperatura após a entrada.
    """
    
    def __init__(self, 
                 plateau_threshold_c: float = 0.3,
                 plateau_minutes: int = 45,
                 min_gap_to_target_c: float = 1.5):
        self.plateau_threshold = plateau_threshold_c
        self.plateau_minutes = plateau_minutes
        self.min_gap = min_gap_to_target_c
    
    def should_close(
        self,
        city: str,
        target_temp: float,          # temperatura alvo do bracket
        current_temp: float,         # temperatura actual
        temp_history: list[tuple],   # [(datetime, temp), ...]
        minutes_until_close: int,    # minutos até o mercado fechar
    ) -> tuple[bool, str]:
        """
        Retorna (deve_fechar, razão).
        """
        if not temp_history or len(temp_history) < 3:
            return False, "histórico insuficiente"
        
        gap = target_temp - current_temp
        
        # 1. Se ainda há >2°C para o target e pouco tempo, fechar
        if gap > self.min_gap and minutes_until_close < 90:
            return True, f"gap={gap:.1f}°C com apenas {minutes_until_close}min restantes"
        
        # 2. Detectar plateau abaixo do target
        recent = [t for dt, t in temp_history 
                  if (temp_history[-1][0] - dt).total_seconds() / 60 <= self.plateau_minutes]
        
        if len(recent) >= 3:
            variation = max(recent) - min(recent)
            max_recent = max(recent)
            
            if variation < self.plateau_threshold and max_recent < target_temp - 0.5:
                return True, (
                    f"plateau detectado ({variation:.2f}°C variação em {self.plateau_minutes}min), "
                    f"máximo={max_recent:.1f}°C < target={target_temp}°C"
                )
        
        # 3. Temperatura a descer consistentemente
        if len(temp_history) >= 6:
            temps_last_hour = [t for dt, t in temp_history
                               if (temp_history[-1][0] - dt).total_seconds() / 60 <= 60]
            if len(temps_last_hour) >= 4:
                # Declive dos últimos 60 min (regressão linear simples)
                n = len(temps_last_hour)
                slope = (temps_last_hour[-1] - temps_last_hour[0]) / n
                if slope < -0.15 and current_temp < target_temp - 0.5:
                    return True, f"temperatura a descer ({slope:.3f}°C/leitura), abaixo do target"
        
        return False, "manter posição"
```

---

### 4.4 Limite de posições simultâneas por correlação

**Contexto:** Miami, Dallas e Phoenix são cidades climaticamente correlacionadas (todas EUA, padrões sinópticos similares). Ter as três abertas ao mesmo tempo amplifica o risco.

**O que implementar:**

```python
# Grupos de correlação climática
CORRELATION_GROUPS = [
    {"name": "USA_SW",     "cities": {"phoenix", "las_vegas"},             "max_concurrent": 1},
    {"name": "USA_SE",     "cities": {"miami", "dallas"},                  "max_concurrent": 1},
    {"name": "SE_Asia",    "cities": {"singapore", "kuala_lumpur", "jakarta"}, "max_concurrent": 2},
    {"name": "S_Asia",     "cities": {"karachi"},                          "max_concurrent": 1},
    {"name": "Europe_W",   "cities": {"madrid", "warsaw", "munich"},       "max_concurrent": 2},
    {"name": "Middle_East",{"cities": {"tel_aviv", "ankara"},              "max_concurrent": 2}},
]

def can_open_position(city: str, open_positions: set[str]) -> tuple[bool, str]:
    """
    Verifica se é permitido abrir posição numa cidade dado as posições abertas.
    """
    for group in CORRELATION_GROUPS:
        if city not in group["cities"]:
            continue
        
        # Quantas posições do mesmo grupo estão abertas
        open_in_group = open_positions & group["cities"]
        
        if len(open_in_group) >= group["max_concurrent"]:
            return False, (
                f"Limite do grupo '{group['name']}': "
                f"{len(open_in_group)}/{group['max_concurrent']} já abertas "
                f"({', '.join(open_in_group)})"
            )
    
    return True, "ok"
```

---

## 5. Configuração por Cidade

### 5.1 Ficheiro de configuração unificado

Criar `city_profiles.py` com todas as configurações numa estrutura única:

```python
from dataclasses import dataclass, field

@dataclass
class CityProfile:
    name: str
    lat: float
    lon: float
    timezone: str
    
    # Thresholds de entrada
    min_conf: float = 0.52
    max_entry_hour: int = 17        # hora local máxima para abrir posição
    min_edge: float = 0.08         # edge mínimo vs mercado
    
    # Persistência do sinal
    persistence_minutes: int = 10
    
    # Gestão de capital
    kelly_fraction: float = 0.25
    max_stake_usd: float = 50.0
    
    # Sazonalidade
    use_seasonal_models: bool = False
    winter_months: list[int] = field(default_factory=list)
    summer_months: list[int] = field(default_factory=list)
    
    # Stop dinâmico
    enable_dynamic_stop: bool = True
    plateau_minutes: int = 45

CITY_PROFILES = {
    "tel_aviv": CityProfile(
        name="Tel Aviv", lat=32.08, lon=34.78, timezone="Asia/Jerusalem",
        min_conf=0.52, max_entry_hour=18, min_edge=0.10,
        kelly_fraction=0.25, max_stake_usd=50.0,
    ),
    "miami": CityProfile(
        name="Miami", lat=25.76, lon=-80.19, timezone="America/New_York",
        min_conf=0.50, max_entry_hour=18, min_edge=0.08,
        kelly_fraction=0.25, max_stake_usd=50.0,
    ),
    "singapore": CityProfile(
        name="Singapore", lat=1.35, lon=103.82, timezone="Asia/Singapore",
        min_conf=0.50, max_entry_hour=18, min_edge=0.08,
        kelly_fraction=0.25, max_stake_usd=50.0,
    ),
    "ankara": CityProfile(
        name="Ankara", lat=39.93, lon=32.86, timezone="Europe/Istanbul",
        min_conf=0.50, max_entry_hour=18, min_edge=0.07,
        use_seasonal_models=True,
        winter_months=[11,12,1,2,3], summer_months=[5,6,7,8,9],
    ),
    "karachi": CityProfile(
        name="Karachi", lat=24.86, lon=67.01, timezone="Asia/Karachi",
        min_conf=0.60, max_entry_hour=17, min_edge=0.09,
        kelly_fraction=0.20,  # mais conservador pelo high premature
    ),
    "moscow": CityProfile(
        name="Moscow", lat=55.75, lon=37.62, timezone="Europe/Moscow",
        min_conf=0.35, max_entry_hour=18, min_edge=0.07,
        use_seasonal_models=True,
        winter_months=[10,11,12,1,2,3,4], summer_months=[6,7,8,9],
        kelly_fraction=0.20,
    ),
    "phoenix": CityProfile(
        name="Phoenix", lat=33.45, lon=-112.07, timezone="America/Phoenix",
        min_conf=0.68, max_entry_hour=16, min_edge=0.12,
        persistence_minutes=15,  # mais exigente
        kelly_fraction=0.15,
    ),
    "las_vegas": CityProfile(
        name="Las Vegas", lat=36.17, lon=-115.14, timezone="America/Los_Angeles",
        min_conf=0.70, max_entry_hour=16, min_edge=0.12,
        persistence_minutes=15,
        kelly_fraction=0.15,
    ),
    # ... adicionar restantes cidades
}
```

---

## 6. Testes e Validação

### 6.1 Backtester actualizado

Após implementar cada melhoria, re-correr o backtester com as seguintes métricas adicionais:

```python
def run_backtest_with_improvements(city: str, df: pd.DataFrame, profile: CityProfile) -> dict:
    """
    Backtester que simula todos os filtros novos.
    Retorna métricas comparáveis com os resultados originais.
    """
    results = {
        "days": 0, "signals_fired": 0,
        "correct": 0, "premature": 0, "missed": 0,
        "filtered_by_conf": 0, "filtered_by_edge": 0,
        "filtered_by_momentum": 0, "filtered_by_persistence": 0,
        "stopped_early": 0, "pnl": 0.0,
    }
    
    # ... implementar lógica de simulação com todos os filtros
    # cada filtro deve registar quantos sinais bloqueou
    
    results["sharpe"] = compute_sharpe(daily_pnl_series)
    results["filter_efficiency"] = {
        "conf": results["filtered_by_conf"] / max(results["signals_fired"], 1),
        "edge": results["filtered_by_edge"] / max(results["signals_fired"], 1),
        "momentum": results["filtered_by_momentum"] / max(results["signals_fired"], 1),
    }
    
    return results
```

### 6.2 Comparação antes/depois

Ao apresentar resultados, incluir tabela comparativa:

```
Cidade     | Sharpe antes | Sharpe depois | Premature antes | Premature depois | ΔPnL%
-----------|-------------|---------------|-----------------|------------------|-------
Tel Aviv   | 18.73       | ?             | 51.6%           | ?                | ?
Miami      | 16.41       | ?             | 46.5%           | ?                | ?
...
```

### 6.3 Ordem de implementação recomendada

Implementar e validar por esta ordem (cada passo deve melhorar o backtest antes de avançar):

1. **`city_profiles.py`** — estrutura de configuração (sem impacto ainda)
2. **Threshold por cidade** (`min_conf`) — impacto imediato em premature
3. **Filtro de odds mínimas** (`has_sufficient_edge`) — impacto em Sharpe
4. **Filtro de hora máxima** (`max_entry_hour`) — impacto em lag
5. **Feature cloud_cover** — re-treinar modelos, comparar métricas
6. **Feature pressure + dewpoint** — re-treinar, comparar
7. **Fourier terms** (substituir polinómio DOY) — re-treinar
8. **Filtro de momentum** — requer dados de temperatura intra-dia
9. **Filtro de persistência** — apenas em live mode (backtest approximado)
10. **Modelos por estação** — para cidades temperadas
11. **Kelly variável** — substituir flat stake
12. **Stop dinâmico** — apenas em live mode

---

*Fim do documento — versão 1.0 — 17 Mai 2026*
