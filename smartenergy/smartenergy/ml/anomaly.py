"""
anomaly.py
==========
Detecção de anomalias de consumo energético por dispositivo.

Estratégia
----------
O método original usava Z-score global (comparando cada dia com a média de
todo o histórico). Isso ignora a sazonalidade semanal: fins de semana e
segunda-feira têm padrões distintos de dias úteis, gerando falsos positivos.

Esta implementação usa **Z-score sazonal por dia da semana**:
  - Para cada dispositivo, calcula média e desvio padrão separadamente
    para cada dia da semana (0=segunda … 6=domingo), usando somente o
    histórico de referência (excluindo os últimos 7 dias analisados).
  - Um ponto é anomalia se |z| > Z_THRESHOLD.

Complementarmente, aplica **IQR fence** para detectar picos extremos que
escapam ao Z-score quando o desvio padrão histórico é muito pequeno
(dispositivos com consumo muito estável).

Requisitos mínimos
------------------
Pelo menos BASELINE_DAYS de histórico para o cálculo da baseline ser
estatisticamente significativo.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Dict, List

import numpy as np

from features import fill_gaps

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

Z_THRESHOLD    = 2.5   # z-score para considerar anomalia (< 3 para mais sensibilidade)
IQR_MULTIPLIER = 2.0   # fence = Q3 + k * IQR
BASELINE_DAYS  = 21    # mínimo de dias de histórico por dispositivo
ANALYSIS_DAYS  = 7     # últimos N dias a inspecionar

# ---------------------------------------------------------------------------
# Detecção principal
# ---------------------------------------------------------------------------

def _baseline_stats_by_weekday(
    dates: List[date],
    values: List[float],
    baseline_end: int,          # índice exclusivo (tudo antes desse índice é baseline)
) -> Dict[int, Dict[str, float]]:
    """
    Calcula média e desvio padrão por dia da semana usando apenas
    os dados de baseline (antes do período de análise).

    Returns
    -------
    {weekday: {"mean": float, "std": float, "q3": float, "iqr": float}}
    """
    stats: Dict[int, Dict[str, float]] = {}
    for wd in range(7):
        vals = [
            values[i]
            for i in range(baseline_end)
            if dates[i].weekday() == wd
        ]
        if len(vals) < 2:
            # Poucos dados para esse dia da semana — usa global como fallback
            vals = values[:baseline_end]
        arr = np.array(vals, dtype=float)
        q1, q3 = float(np.percentile(arr, 25)), float(np.percentile(arr, 75))
        stats[wd] = {
            "mean": float(arr.mean()),
            "std":  float(arr.std()) or 1e-6,
            "q3":   q3,
            "iqr":  q3 - q1,
        }
    return stats


def detect_anomalies(
    devices: Dict[str, Dict[str, float]],
) -> List[Dict[str, object]]:
    """
    Detecta anomalias de consumo para cada dispositivo.

    Parameters
    ----------
    devices : {device_name: {iso_date: kwh, ...}}

    Returns
    -------
    Lista de ocorrências, cada uma com:
      - device  : str
      - day     : str (ISO)
      - kwh     : float  — valor observado
      - esperado: float  — média esperada para aquele dia da semana
      - z       : float  — z-score
      - metodo  : str    — "zscore" | "iqr"
    """
    out: List[Dict[str, object]] = []

    for device_name, raw_days in devices.items():
        if not raw_days:
            continue

        # Preenche lacunas para manter cronologia contínua
        filled = fill_gaps(raw_days)
        ds     = sorted(filled)

        if len(ds) < BASELINE_DAYS + 1:
            logger.debug(
                "[Anomaly] %s: histórico insuficiente (%d dias), mínimo %d.",
                device_name, len(ds), BASELINE_DAYS + 1,
            )
            continue

        dates  = [date.fromisoformat(d) for d in ds]
        values = [filled[d] for d in ds]

        # Os últimos ANALYSIS_DAYS são o período de análise
        baseline_end   = len(ds) - ANALYSIS_DAYS
        analysis_range = list(range(baseline_end, len(ds)))

        stats = _baseline_stats_by_weekday(dates, values, baseline_end)

        for i in analysis_range:
            d   = dates[i]
            kwh = values[i]
            wd  = d.weekday()
            st  = stats[wd]

            # Z-score sazonal
            z = (kwh - st["mean"]) / st["std"]

            # IQR fence
            fence     = st["q3"] + IQR_MULTIPLIER * st["iqr"]
            iqr_alert = kwh > fence and st["iqr"] > 0.1  # ignora se consumo é quasi-zero

            if z > Z_THRESHOLD or iqr_alert:
                method = "zscore" if z > Z_THRESHOLD else "iqr"
                out.append({
                    "device":   device_name,
                    "day":      d.isoformat(),
                    "kwh":      round(kwh, 2),
                    "esperado": round(st["mean"], 2),
                    "z":        round(z, 1),
                    "metodo":   method,
                })
                logger.info(
                    "[Anomaly] %s em %s: %.2f kWh (esperado ~%.2f, z=%.1f, método=%s)",
                    device_name, d.isoformat(), kwh, st["mean"], z, method,
                )

    # Ordena por z-score descendente para destacar os casos mais críticos
    out.sort(key=lambda x: float(x["z"]), reverse=True)   # type: ignore[arg-type]
    return out
