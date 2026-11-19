"""
predictor.py — SHIM de retrocompatibilidade.
O código real vive em cassiopeia_predictor.py (prefixo unificado).
Este ficheiro só existe para não partir imports antigos
(from predictor import ... em train.py, cassiopeia_train.py,
cassiopeia_backtester.py, live_bot.py, etc.).
"""
from cassiopeia_predictor import *          # noqa: F401,F403
from cassiopeia_predictor import (          # noqa: F401  (nomes explícitos p/ IDEs)
    FEATURE_COLS, StreamingPeakDetector, build_features, compute_prev7,
    get_seasonal_prior, init_history_max, load_model, load_models,
    predict_ensemble, predict_p, set_city, set_seasonal_prior,
    update_history_max, _get_city, _lookup_seasonal_prior,
)