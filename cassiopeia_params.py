"""
cassiopeia_params.py
Helper central para ler, mergear, versionar e resolver parâmetros calibrados.
Suporta histórico de calibrações e rollback para versões anteriores.
"""
import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

DEFAULT_PARAMS = {
    "threshold": 0.35,
    "min_spread": 0.5,
    "bracket_half": 0.5,
    "start_hour": 13,
    "end_hour": 19,
    "outlier_cap": 3.0,
    "trailing_stop": None,
    "max_trades_per_day": 1,
    # FIX banda v4 (19/09): fallback = banda histórica pré-D7; o valor real
    # vive na config ativa (D-V1: 0.80-0.86) e é lido pelo CassiopeiaEntry
    "min_buy_ask": 0.60,
    "max_buy_ask": 0.85,
}

ACTIVE_CONFIG_PATH = Path("cassiopeia_active_config.json")
HISTORY_DIR = Path("cassiopeia_config_history")
MAX_HISTORY_PER_CITY = 20  # manter últimas N calibrações


def _ensure_history_dir():
    HISTORY_DIR.mkdir(exist_ok=True)


def _history_path(city: str, version_id: str) -> Path:
    _ensure_history_dir()
    return HISTORY_DIR / f"{city}_{version_id}.json"


def _generate_version_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:-3]


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Dict[str, Any]) -> None:
    # FIX P1: escrita atomica (tmp + os.replace). O active config e lido pelo
    # bot live em simultaneo com o watchdog daemon a escrever — escrita directa
    # permitia leitura de JSON truncado -> crash do bot.
    tmp = path.with_name(f".tmp_{path.name}_{int(datetime.now().timestamp()*1000)}")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def get_active_config() -> Dict[str, Dict[str, Any]]:
    """Devolve o dicionário completo de config ativa (city -> params)."""
    cfg = load_json(ACTIVE_CONFIG_PATH)
    return cfg if cfg is not None else {}


def get_calibrated_params(city: str) -> Optional[Dict[str, Any]]:
    """Devolve os parâmetros calibrados para uma cidade, ou None."""
    cfg = get_active_config()
    key = city.lower().strip()
    return cfg.get(key)


def resolve_params(city: str, **cli_overrides) -> Dict[str, Any]:
    """
    Resolve a cadeia de prioridade:
      1. CLI overrides (mais prioritário)
      2. Parâmetros calibrados ativos (cassiopeia_active_config.json)
      3. Defaults (menos prioritário)
    """
    params = dict(DEFAULT_PARAMS)
    calibrated = get_calibrated_params(city)
    if calibrated:
        # ignorar metadados internos
        clean = {k: v for k, v in calibrated.items() if not k.startswith("_")}
        # V4.1: validar ranges TAMBÉM na leitura (a sanitização só corria
        # no apply — JSON editado à mão passava valores absurdos)
        for k, v in clean.items():
            if k in VALID_PARAM_KEYS:
                if v is None:        # None legítimo (ex: trailing_stop null)
                    continue
                lo, hi = VALID_PARAM_KEYS[k]
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    # FIX v4.1 (19/09): lixo não-numérico ficava na config e
                    # partia o float() a jusante — a usar default + aviso
                    print(f"⚠️  resolve_params: '{k}={v!r}' não numérico "
                          f"— a usar default {DEFAULT_PARAMS.get(k)}")
                    clean[k] = DEFAULT_PARAMS.get(k)
                    continue
                if not (lo <= fv <= hi):
                    print(f"⚠️  resolve_params: '{k}={v}' fora de [{lo},{hi}] "
                          f"— a usar default {DEFAULT_PARAMS.get(k)}")
                    clean[k] = DEFAULT_PARAMS.get(k)
        params.update(clean)
    # CLI overrides têm prioridade absoluta
    for k, v in cli_overrides.items():
        if v is not None:
            params[k] = v
    return params


def _prune_history(city: str):
    """Mantém só as últimas MAX_HISTORY_PER_CITY versões."""
    _ensure_history_dir()
    files = sorted(
        HISTORY_DIR.glob(f"{city}_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in files[MAX_HISTORY_PER_CITY:]:
        old.unlink()


# FIX P2/P3: apenas estas chaves sao parametros legitimos, com ranges validos.
VALID_PARAM_KEYS = {
    "threshold":   (0.0, 1.0),
    "min_spread":  (0.0, 20.0),
    "bracket_half":(0.05, 5.0),
    "start_hour":  (0, 23),
    "end_hour":    (0, 23),
    "outlier_cap": (0.5, 15.0),
    "max_trades_per_day": (1, 10),          # V4.1: já não perde na sanitização
    "trailing_stop": (0.0, 5.0),            # None tratado fora (só float validado)
    # FIX banda v4 (19/09): a banda ask é parâmetro legítimo (D-V1)
    "min_buy_ask": (0.01, 0.99),
    "max_buy_ask": (0.01, 0.99),
}


def _sanitize_params(best_params: Dict[str, Any]) -> Dict[str, Any]:
    """Filtra chaves desconhecidas e valida ranges. Levanta em caso grave."""
    clean = {}
    for k, v in best_params.items():
        if k not in VALID_PARAM_KEYS:
            print(f"⚠️  apply_calibration: chave desconhecida '{k}' ignorada")
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            print(f"⚠️  apply_calibration: '{k}={v!r}' nao numerico — ignorado")
            continue
        lo, hi = VALID_PARAM_KEYS[k]
        if not (lo <= fv <= hi):
            raise ValueError(
                f"apply_calibration: '{k}={fv}' fora do range [{lo},{hi}] — "
                f"calibracao corrupta? NAO aplicada.")
        if k in ("start_hour", "end_hour"):
            fv = int(fv)
        clean[k] = fv
    if not clean:
        raise ValueError("apply_calibration: nenhum parametro valido — NAO aplicada.")
    sh, eh = clean.get("start_hour", 13), clean.get("end_hour", 19)
    if eh < sh:
        raise ValueError(f"apply_calibration: end_hour({eh}) < start_hour({sh}) — NAO aplicada.")
    return clean


def apply_calibration(city: str, best_params: Dict[str, Any],
                      metrics: Optional[Dict[str, Any]] = None,
                      source_file: Optional[str] = None) -> str:
    """
    Aplica / sobrescreve os parâmetros calibrados de uma cidade no active config.
    Guarda a versão anterior no histórico. Devolve o version_id.
    """
    cfg = get_active_config()
    key = city.lower().strip()
    version_id = _generate_version_id()
    best_params = _sanitize_params(best_params)   # FIX P2/P3

    # Guardar versão anterior no histórico (se existir)
    prev = dict(cfg.get(key, {}))
    if key in cfg:
        prev_version = prev.get("_meta", {}).get("version_id", "unknown")
        hist_path = _history_path(key, prev_version)
        save_json(hist_path, prev)
        _prune_history(key)

    entry = {
        "best_params": best_params,
        "metrics": metrics or {},
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "version_id": version_id,
        "source_file": source_file,
    }
    new_city = {**best_params, "_meta": entry}
    # FIX banda v4 (19/09): a banda ask é decisão do dono (D-V1: 0.80-0.86),
    # não output de calibração — um apply cujo best_params não a traz não a
    # pode apagar silenciosamente (era exatamente o que aconteceria com os
    # JSONs do pipeline, que não incluem min/max_buy_ask)
    for bk in ("min_buy_ask", "max_buy_ask"):
        if bk not in new_city and bk in prev:
            new_city[bk] = prev[bk]
    cfg[key] = new_city
    save_json(ACTIVE_CONFIG_PATH, cfg)
    return version_id


def get_history(city: str) -> List[Dict[str, Any]]:
    """Devolve lista de versões históricas (mais recente primeiro)."""
    _ensure_history_dir()
    key = city.lower().strip()
    files = sorted(
        HISTORY_DIR.glob(f"{key}_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    history = []
    for f in files:
        data = load_json(f)
        if data:
            vid = f.stem.replace(f"{key}_", "")
            data["_history_version_id"] = vid
            history.append(data)
    return history


def rollback(city: str, version_id: Optional[str] = None,
             steps_back: int = 1) -> bool:
    """
    Rollback para uma versão anterior.
    Se version_id for dado, volta para essa versão exata.
    Senão, volta 'steps_back' no histórico (1 = anterior, 2 = antes da anterior, etc.)
    """
    cfg = get_active_config()
    key = city.lower().strip()

    if key not in cfg:
        print(f"⚠️  {key} não tem config ativa.")
        return False

    history = get_history(key)
    if not history:
        print(f"⚠️  {key} não tem histórico de calibrações.")
        return False

    if version_id:
        target = next((h for h in history if h.get("_history_version_id") == version_id), None)
        if not target:
            print(f"⚠️  Versão {version_id} não encontrada no histórico.")
            return False
    else:
        idx = steps_back - 1
        if idx >= len(history):
            print(f"⚠️  Só existem {len(history)} versões no histórico. steps_back={steps_back} é demasiado.")
            return False
        target = history[idx]

    # Guardar atual no histórico antes de sobrescrever
    current = dict(cfg[key])
    cur_vid = current.get("_meta", {}).get("version_id", "unknown")
    save_json(_history_path(key, cur_vid), current)

    # Restaurar
    vid = target.pop("_history_version_id", "unknown")
    cfg[key] = target
    save_json(ACTIVE_CONFIG_PATH, cfg)
    print(f"✅ {key} revertido para versão {vid}.")
    return True


def list_calibrated_cities() -> list:
    cfg = get_active_config()
    return sorted(cfg.keys())


def print_params(city: str, params: Dict[str, Any]) -> None:
    print(f"\n📍 {city.upper()}")
    for k in ["threshold", "min_spread", "bracket_half", "start_hour", "end_hour", "outlier_cap"]:
        if k in params:
            print(f"   {k:20s} = {params[k]}")
    meta = params.get("_meta")
    if meta:
        print(f"   version_id       = {meta.get('version_id', 'n/d')}")
        print(f"   calibrado em     = {meta.get('applied_at', 'n/d')}")
        print(f"   source_file      = {meta.get('source_file', 'n/d')}")
        m = meta.get("metrics", {})
        if m:
            for mk, mv in m.items():
                if isinstance(mv, (int, float)):
                    print(f"   {mk:20s} = {mv:.4f}")


def print_history(city: str) -> None:
    hist = get_history(city)
    print(f"\n📜 Histórico de {city.upper()} ({len(hist)} versões):")
    for i, h in enumerate(hist, 1):
        vid = h.get("_history_version_id", "?")
        meta = h.get("_meta", {})
        when = meta.get("applied_at", "n/d")[:19] if meta else "n/d"
        m = meta.get("metrics", {}) if meta else {}
        score = m.get("sharpe", m.get("score", "n/d"))
        print(f"   [{i}] {vid}  ({when})  sharpe={score}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gerir parâmetros ativos da Cassiopeia")
    sub = parser.add_subparsers(dest="cmd")

    p_show = sub.add_parser("show", help="Mostrar parâmetros atuais")
    p_show.add_argument("--city", help="Cidade para inspecionar")

    p_history = sub.add_parser("history", help="Mostrar histórico de calibrações")
    p_history.add_argument("--city", required=True)

    p_rollback = sub.add_parser("rollback", help="Reverter para versão anterior")
    p_rollback.add_argument("--city", required=True)
    p_rollback.add_argument("--version-id", help="ID exato da versão")
    p_rollback.add_argument("--steps", type=int, default=1, help="Número de passos atrás (default=1)")

    args = parser.parse_args()

    if args.cmd == "show":
        if args.city:
            p = resolve_params(args.city)
            print_params(args.city, p)
        else:
            cities = list_calibrated_cities()
            if not cities:
                print("Nenhuma configuração ativa. Corre primeiro cassiopeia_apply_calibration.py")
            else:
                print(f"Cidades calibradas ({len(cities)}): {', '.join(cities)}")
                for c in cities:
                    p = resolve_params(c)
                    print_params(c, p)

    elif args.cmd == "history":
        print_history(args.city)

    elif args.cmd == "rollback":
        rollback(args.city, version_id=args.version_id, steps_back=args.steps)

    else:
        parser.print_help()
