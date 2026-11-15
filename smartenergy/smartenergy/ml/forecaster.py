"""
forecaster.py
=============
Módulo de previsão de consumo energético para o SmartEnergy.

Estratégia de modelagem
-----------------------
Três modelos são treinados e avaliados automaticamente para cada requisição:

1. Ridge Regression         — baseline linear regularizado
2. GradientBoostingRegressor — captura relações não-lineares e interações
3. HuberRegressor           — robusto a outliers (picos de consumo)

O modelo com menor MAE na validação temporal é selecionado para a previsão.

Validação temporal
------------------
Para evitar data leakage, a validação usa os últimos `VAL_DAYS` como conjunto
de teste e o restante como treino — nunca divisão aleatória em séries temporais.

Lags
----
Incluímos lags de 1, 7 e 14 dias para capturar autocorrelação diária e semanal,
que é o principal padrão em dados de consumo residencial.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Tuple

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import HuberRegressor, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler

from features import (
    add_lag_features,
    add_lag_features_inference,
    build_features,
    fill_gaps,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

VAL_DAYS   = 7    # dias reservados para validação temporal
MIN_DAYS   = 21   # mínimo de observações para treinar
LAGS       = (1, 7, 14)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """MAPE seguro — ignora pontos com consumo zero para evitar divisão por zero."""
    mask = y_true > 0.1
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    mae  = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2   = float(r2_score(y_true, y_pred)) if len(y_true) > 1 else float("nan")
    mape = _mape(y_true, y_pred)
    return {"mae": round(mae, 4), "rmse": round(rmse, 4),
            "r2": round(r2, 4), "mape": round(mape, 2)}


# ---------------------------------------------------------------------------
# Pipeline de treino e seleção de modelo
# ---------------------------------------------------------------------------

def _build_candidates() -> List[Tuple[str, Any]]:
    return [
        ("Ridge", Ridge(alpha=1.0)),
        ("GradientBoosting", GradientBoostingRegressor(
            n_estimators=200, max_depth=3, learning_rate=0.05,
            subsample=0.8, random_state=42,
        )),
        ("Huber", HuberRegressor(epsilon=1.5, max_iter=300)),
    ]


def _prepare_arrays(
    daily_filled: dict[str, float],
) -> Tuple[np.ndarray, np.ndarray, List[date], date]:
    """
    Converte o dicionário de consumo em arrays X, y prontos para o sklearn,
    incluindo features de lag.
    """
    ds   = sorted(daily_filled)
    days = [date.fromisoformat(d) for d in ds]
    t0   = days[0]
    y    = np.array([daily_filled[d] for d in ds], dtype=float)
    X    = build_features(days, t0)
    X, y = add_lag_features(X, y, lags=LAGS)
    return X, y, days, t0


def train_and_select(
    daily: dict[str, float],
) -> Tuple[Any, StandardScaler, date, Dict[str, Any]]:
    """
    Treina os candidatos com validação temporal e retorna o melhor modelo,
    o scaler ajustado, a data t0 e o relatório de métricas.

    Parameters
    ----------
    daily : dict[str, float]
        Série diária de consumo total (data ISO → kWh).

    Returns
    -------
    best_model  : estimador sklearn já treinado em todos os dados
    scaler      : StandardScaler ajustado em X_train
    t0          : data de referência para tendência
    report      : dict com métricas de validação de cada candidato
    """
    filled = fill_gaps(daily)
    if len(filled) < MIN_DAYS + VAL_DAYS:
        raise ValueError(
            f"Dados insuficientes: {len(filled)} dias disponíveis, "
            f"mínimo necessário: {MIN_DAYS + VAL_DAYS}."
        )

    X, y, days, t0 = _prepare_arrays(filled)

    # Separação temporal — sem aleatoriedade
    n_val    = VAL_DAYS
    n_train  = len(X) - n_val
    if n_train < MIN_DAYS:
        raise ValueError("Conjunto de treino muito pequeno após separação temporal.")

    X_train, X_val = X[:n_train], X[n_train:]
    y_train, y_val = y[:n_train], y[n_train:]

    # Normalização — fit apenas em treino para evitar leakage
    scaler  = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_val   = scaler.transform(X_val)

    report: Dict[str, Any] = {}
    best_name  = ""
    best_mae   = float("inf")
    best_model = None

    for name, model in _build_candidates():
        try:
            model.fit(X_train, y_train)
            y_pred = np.maximum(model.predict(X_val), 0)
            m = _metrics(y_val, y_pred)
            report[name] = m
            logger.info("[Forecaster] %s — MAE=%.3f RMSE=%.3f R²=%.3f MAPE=%.1f%%",
                        name, m["mae"], m["rmse"], m["r2"], m["mape"])
            if m["mae"] < best_mae:
                best_mae   = m["mae"]
                best_name  = name
                best_model = model
        except Exception as exc:
            logger.warning("[Forecaster] %s falhou no treino: %s", name, exc)
            report[name] = {"error": str(exc)}

    if best_model is None:
        raise RuntimeError("Nenhum modelo conseguiu ser treinado.")

    # Retreina o melhor modelo em TODOS os dados (treino + validação)
    # X/y já têm lags aplicados desde _prepare_arrays — basta re-escalar tudo
    X_full_sc = scaler.fit_transform(X)   # re-fit em todos os dados com lags
    best_model.fit(X_full_sc, y)

    logger.info("[Forecaster] Modelo selecionado: %s (MAE validação=%.3f)", best_name, best_mae)
    report["selected"] = best_name

    return best_model, scaler, t0, report


# ---------------------------------------------------------------------------
# Inferência
# ---------------------------------------------------------------------------

def predict(
    model: Any,
    scaler: StandardScaler,
    t0: date,
    last_days: List[date],
    y_hist: np.ndarray,
    horizon: int,
) -> List[Dict[str, Any]]:
    """
    Gera previsão para `horizon` dias futuros de forma autoregressiva.

    Parameters
    ----------
    model     : estimador treinado
    scaler    : StandardScaler ajustado
    t0        : data de referência para tendência
    last_days : lista de datas do histórico disponível
    y_hist    : valores históricos de consumo (mesmo comprimento que last_days)
    horizon   : número de dias a prever

    Returns
    -------
    Lista de {"day": str, "kwh": float}
    """
    fut_days = [last_days[-1] + timedelta(i + 1) for i in range(horizon)]
    X_base   = build_features(fut_days, t0)

    max_lag  = max(LAGS)
    y_buffer = list(y_hist[-max_lag:])
    preds: list[float] = []

    for i in range(horizon):
        lag_vals = []
        for lag in LAGS:
            pos = len(y_buffer) - lag + i
            if pos >= 0 and pos < len(y_buffer):
                lag_vals.append(y_buffer[pos])
            elif pos >= len(y_buffer):
                pred_idx = pos - len(y_buffer)
                lag_vals.append(preds[pred_idx] if pred_idx < len(preds) else 0.0)
            else:
                lag_vals.append(0.0)

        x_row = np.concatenate([X_base[i], lag_vals]).reshape(1, -1)
        x_sc  = scaler.transform(x_row)
        p     = float(np.maximum(model.predict(x_sc)[0], 0.0))
        preds.append(p)

    return [
        {"day": d.isoformat(), "kwh": round(p, 2)}
        for d, p in zip(fut_days, preds)
    ]


# ---------------------------------------------------------------------------
# Função principal (entry point para main.py)
# ---------------------------------------------------------------------------

def run_forecast(daily: dict[str, float], horizon: int = 7) -> Dict[str, Any]:
    """
    Executa o pipeline completo de previsão e retorna o resultado formatado
    para o contrato da API do SmartEnergy.

    Parameters
    ----------
    daily   : dict[str, float]  — série diária recebida do backend
    horizon : int               — número de dias futuros a prever

    Returns
    -------
    {
        "previsao": [{"day": str, "kwh": float}, ...],
        "kwh_total": float,
        "modelo": str,
        "metricas": {nome_modelo: {mae, rmse, r2, mape}, ...}
    }
    """
    filled = fill_gaps(daily)
    n = len(filled)

    if n < MIN_DAYS + VAL_DAYS:
        logger.warning("[Forecaster] Dados insuficientes (%d dias). Retornando previsão vazia.", n)
        return {"previsao": [], "kwh_total": 0, "modelo": "insuficiente", "metricas": {}}

    try:
        model, scaler, t0, report = train_and_select(daily)
    except Exception as exc:
        logger.error("[Forecaster] Falha no treinamento: %s", exc)
        return {"previsao": [], "kwh_total": 0, "modelo": "erro", "metricas": {}}

    ds        = sorted(filled)
    days      = [date.fromisoformat(d) for d in ds]
    y_hist    = np.array([filled[d] for d in ds], dtype=float)
    previsao  = predict(model, scaler, t0, days, y_hist, horizon)
    kwh_total = round(sum(p["kwh"] for p in previsao), 2)

    return {
        "previsao":  previsao,
        "kwh_total": kwh_total,
        "modelo":    report.get("selected", "?"),
        "metricas":  {k: v for k, v in report.items() if k != "selected"},
    }
