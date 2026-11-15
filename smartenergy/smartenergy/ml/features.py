"""
features.py
===========
Engenharia de atributos compartilhada entre os módulos de previsão e anomalia.

Responsabilidades
-----------------
- Converter séries de datas em vetores de features numéricas.
- Calcular lags e médias móveis.
- Preencher lacunas de dias ausentes por interpolação linear.
- Garantir que nenhum dado futuro vaze para o conjunto de treino.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import List, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Preenchimento de lacunas
# ---------------------------------------------------------------------------

def fill_gaps(daily: dict[str, float]) -> dict[str, float]:
    """
    Preenche dias ausentes entre o primeiro e o último registro usando
    interpolação linear.  Dias sem leitura alguma recebem o valor 0.0.

    Parameters
    ----------
    daily : dict[str, float]
        Mapeamento ISO-date → kWh.

    Returns
    -------
    dict[str, float]
        Série completa sem lacunas.
    """
    if not daily:
        return {}

    dates = sorted(daily)
    start = date.fromisoformat(dates[0])
    end   = date.fromisoformat(dates[-1])

    full: dict[str, float] = {}
    cur = start
    while cur <= end:
        full[cur.isoformat()] = daily.get(cur.isoformat(), float("nan"))
        cur += timedelta(days=1)

    # Interpolação linear sobre NaNs internos
    keys  = sorted(full)
    vals  = np.array([full[k] for k in keys], dtype=float)
    nans  = np.isnan(vals)
    if nans.any() and not nans.all():
        idx = np.arange(len(vals))
        vals[nans] = np.interp(idx[nans], idx[~nans], vals[~nans])
    # NaN no início ou fim → 0
    vals = np.nan_to_num(vals, nan=0.0)

    return {k: float(v) for k, v in zip(keys, vals)}


# ---------------------------------------------------------------------------
# Construção de features para séries temporais
# ---------------------------------------------------------------------------

def build_features(days: List[date], t0: date) -> np.ndarray:
    """
    Constrói uma matriz de features para uma lista de datas.

    Features geradas:
    - trend          : dias desde t0 (captura tendência linear)
    - trend_sq       : tendência ao quadrado (curvatura)
    - dow_sin/cos    : codificação circular do dia da semana
    - month_sin/cos  : codificação circular do mês (sazonalidade anual)
    - week_sin/cos   : codificação circular da semana do ano
    - is_weekend     : indicador binário de fim de semana

    A codificação circular evita a descontinuidade artificial que surge
    com one-hot ou valores inteiros (ex.: segunda=0, domingo=6 não são
    opostos — são adjacentes no ciclo semanal).

    Parameters
    ----------
    days : List[date]
    t0   : date
        Data de referência para o cálculo de tendência.

    Returns
    -------
    np.ndarray, shape (n_samples, 9)
    """
    rows = []
    for d in days:
        trend    = (d - t0).days
        dow      = d.weekday()           # 0=Mon … 6=Sun
        month    = d.month               # 1–12
        week     = d.isocalendar()[1]    # 1–53

        rows.append([
            trend,
            trend ** 2,
            np.sin(2 * np.pi * dow   / 7),
            np.cos(2 * np.pi * dow   / 7),
            np.sin(2 * np.pi * month / 12),
            np.cos(2 * np.pi * month / 12),
            np.sin(2 * np.pi * week  / 53),
            np.cos(2 * np.pi * week  / 53),
            int(dow >= 5),               # is_weekend
        ])
    return np.array(rows, dtype=float)


# ---------------------------------------------------------------------------
# Lag features (somente para uso com arrays já ordenados cronologicamente)
# ---------------------------------------------------------------------------

def add_lag_features(
    X: np.ndarray,
    y: np.ndarray,
    lags: Tuple[int, ...] = (1, 7, 14),
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Adiciona colunas de lag ao array de features, descartando as primeiras
    `max(lags)` linhas para evitar vazamento de dados.

    Importante: aplica somente em contexto de treino onde `y` está disponível.
    Para inferência use `add_lag_features_inference`.

    Parameters
    ----------
    X    : np.ndarray, shape (n, f)
    y    : np.ndarray, shape (n,)
    lags : tupla de inteiros

    Returns
    -------
    X_aug, y_aug — arrays com as primeiras `max_lag` linhas removidas.
    """
    max_lag = max(lags)
    lag_cols = np.column_stack([
        np.concatenate([np.full(lag, np.nan), y[:-lag]])
        for lag in lags
    ])
    X_aug = np.hstack([X, lag_cols])
    # Remove linhas com NaN (cabeça da série)
    valid = ~np.isnan(lag_cols).any(axis=1)
    return X_aug[valid], y[valid]


def add_lag_features_inference(
    X_fut: np.ndarray,
    y_hist: np.ndarray,
    lags: Tuple[int, ...] = (1, 7, 14),
    n_future: int = 1,
) -> np.ndarray:
    """
    Constrói lags para pontos futuros usando o histórico disponível.
    Para horizonte > 1, o lag-1 do passo t usa a predição do passo t-1
    (previsão autoregressiva).

    Parameters
    ----------
    X_fut   : np.ndarray, shape (horizon, f)  — features base dos dias futuros
    y_hist  : np.ndarray  — valores históricos (últimos max(lags) suficientes)
    lags    : tupla de lags a incluir
    n_future: int         — número de passos futuros (== len(X_fut))

    Returns
    -------
    np.ndarray, shape (horizon, f + len(lags))
    """
    buffer = list(y_hist)
    result_rows = []
    preds: list[float] = []

    for i in range(n_future):
        lag_vals = []
        for lag in lags:
            pos = len(buffer) + i - lag
            if pos >= 0 and pos < len(buffer):
                lag_vals.append(buffer[pos])
            elif pos >= len(buffer):
                pred_idx = pos - len(buffer)
                lag_vals.append(preds[pred_idx] if pred_idx < len(preds) else 0.0)
            else:
                lag_vals.append(0.0)

        row = np.concatenate([X_fut[i], lag_vals])
        result_rows.append(row)
        # placeholder; a predição real será inserida após a inferência do modelo
        preds.append(0.0)

    return np.array(result_rows, dtype=float)
