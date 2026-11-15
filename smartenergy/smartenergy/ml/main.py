"""
main.py
=======
API FastAPI do módulo de Machine Learning do SmartEnergy.

Este arquivo é exclusivamente responsável pela interface HTTP:
- Definição dos schemas de entrada e saída.
- Roteamento das requisições para os módulos especializados.
- Tratamento de erros de forma centralizada.

A lógica de ML está encapsulada em:
  forecaster.py — previsão de consumo
  anomaly.py    — detecção de anomalias
  chat.py       — assistente virtual
  features.py   — engenharia de atributos (compartilhada)
"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from anomaly import detect_anomalies
from chat import run_chat
from forecaster import run_forecast

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SmartEnergy ML",
    description="Módulo de Machine Learning para previsão de consumo, detecção de anomalias e assistente virtual.",
    version="2.0.0",
)

# ---------------------------------------------------------------------------
# Schemas de entrada
# ---------------------------------------------------------------------------


class ForecastIn(BaseModel):
    daily: Dict[str, float] = Field(
        ...,
        description="Série diária de consumo total: {'YYYY-MM-DD': kwh}",
    )
    horizon: int = Field(
        default=7,
        ge=1,
        le=30,
        description="Número de dias futuros a prever (1–30).",
    )


class AnomalyIn(BaseModel):
    devices: Dict[str, Dict[str, float]] = Field(
        ...,
        description="Consumo por dispositivo: {'device_name': {'YYYY-MM-DD': kwh}}",
    )


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, description="Pergunta do usuário.")
    context: Dict[str, Any] = Field(..., description="Dados do dashboard para contextualizar a resposta.")


# ---------------------------------------------------------------------------
# Schemas de saída
# ---------------------------------------------------------------------------


class ForecastPoint(BaseModel):
    day: str
    kwh: float


class ForecastOut(BaseModel):
    previsao:  List[ForecastPoint]
    kwh_total: float
    modelo:    str
    metricas:  Dict[str, Any]


class AnomalyPoint(BaseModel):
    device:   str
    day:      str
    kwh:      float
    esperado: float
    z:        float
    metodo:   str


class ChatOut(BaseModel):
    resposta: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> Dict[str, str]:
    """Verificação de saúde do serviço ML."""
    return {"status": "ok", "version": "2.0.0"}


@app.post("/forecast", response_model=ForecastOut)
def forecast(body: ForecastIn) -> Dict[str, Any]:
    """
    Prevê o consumo energético total para os próximos `horizon` dias.

    Treina automaticamente os melhores modelos disponíveis (Ridge,
    GradientBoosting, Huber) com validação temporal e seleciona o de
    menor MAE para gerar a previsão.

    Requer no mínimo 28 dias de histórico.
    """
    logger.info("[/forecast] Recebido: %d dias, horizonte=%d", len(body.daily), body.horizon)
    try:
        result = run_forecast(body.daily, body.horizon)
        return result
    except Exception as exc:
        logger.error("[/forecast] Erro inesperado: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/anomalies", response_model=List[AnomalyPoint])
def anomalies(body: AnomalyIn) -> List[Dict[str, Any]]:
    """
    Detecta consumo anormal por dispositivo nos últimos 7 dias.

    Usa Z-score sazonal por dia da semana + IQR fence para reduzir
    falsos positivos causados por padrões semanais legítimos.

    Requer no mínimo 21 dias de histórico por dispositivo.
    """
    logger.info("[/anomalies] Recebido: %d dispositivos", len(body.devices))
    try:
        return detect_anomalies(body.devices)
    except Exception as exc:
        logger.error("[/anomalies] Erro inesperado: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/chat", response_model=ChatOut)
def chat(body: ChatIn) -> Dict[str, str]:
    """
    Assistente virtual de gestão energética.

    Responde perguntas sobre consumo, previsão, anomalias e dicas de economia
    usando os dados reais do dashboard. Suporta integração opcional com
    Claude (Anthropic) via variável de ambiente ANTHROPIC_API_KEY.
    """
    logger.info("[/chat] Mensagem recebida (%d chars)", len(body.message))
    try:
        return run_chat(body.message, body.context)
    except Exception as exc:
        logger.error("[/chat] Erro inesperado: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
