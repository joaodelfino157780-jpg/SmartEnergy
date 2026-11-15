"""
chat.py
=======
Assistente virtual do SmartEnergy.

Dois modos de operação
----------------------
1. Claude (Anthropic) — quando ANTHROPIC_API_KEY está configurada.
   O contexto completo do dashboard é injetado no system prompt para que
   o modelo responda com base nos dados reais do usuário.

2. Motor de regras local — fallback quando não há chave Anthropic.
   Responde com precisão às perguntas mais comuns usando os dados do contexto,
   sem depender de rede externa.

O motor de regras é uma melhoria em relação à versão anterior:
- Detecta intenção por categorias de palavras-chave priorizadas.
- Formata valores monetários e kWh de forma consistente.
- Inclui dicas de economia específicas por dispositivo e por horário.
- Gera resposta de fallback rica com resumo do período.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tipos auxiliares
# ---------------------------------------------------------------------------

Context = Dict[str, Any]


# ---------------------------------------------------------------------------
# Motor de regras local
# ---------------------------------------------------------------------------

def _fmt_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_kwh(value: float) -> str:
    return f"{value:.1f} kWh"


def _top_device(ranking: List[Dict[str, Any]]) -> Dict[str, Any]:
    return ranking[0] if ranking else {}


_INTENT_MAP = [
    # (categoria, palavras-chave)
    ("ranking",    ["maior", "vilão", "vilao", "mais gasta", "ranking", "top", "pior", "consume mais"]),
    ("forecast",   ["previs", "próximo", "proximo", "futuro", "vai gastar", "semana que vem", "próximos dias"]),
    ("anomaly",    ["anorm", "desperd", "estranh", "pico", "alto demais", "suspeito", "irregular"]),
    ("economy",    ["econom", "reduzir", "dica", "poupar", "diminuir", "gastar menos", "eficien"]),
    ("cost",       ["custo", "valor", "reais", "conta", "fatura", "gasto"]),
    ("total",      ["total", "consumo", "kwh", "quanto gast", "histórico"]),
    ("devices",    ["aparelho", "dispositivo", "equipamento", "lista"]),
    ("period",     ["período", "periodo", "mês", "mes", "30 dias", "último", "ultimo"]),
]


def _detect_intent(message: str) -> str:
    msg = message.lower()
    for intent, keywords in _INTENT_MAP:
        if any(k in msg for k in keywords):
            return intent
    return "general"


def _rules_response(message: str, ctx: Context) -> str:
    intent  = _detect_intent(message)
    ranking = ctx.get("ranking", [])
    tarifa  = float(ctx.get("tarifa", 0.95))
    total   = float(ctx.get("total", 0))
    custo   = float(ctx.get("custo", 0))

    if intent == "ranking" and ranking:
        top = _top_device(ranking)
        lines = [
            f"🏆 O maior consumidor é **{top['name']}** ({top.get('room', '–')}): "
            f"{_fmt_kwh(top['kwh'])} em 30 dias ({top['pct']:.0f}% do total, {_fmt_brl(top['custo'])}).",
        ]
        if len(ranking) >= 2:
            sec = ranking[1]
            lines.append(
                f"Em 2º lugar: **{sec['name']}** com {_fmt_kwh(sec['kwh'])} "
                f"({sec['pct']:.0f}%, {_fmt_brl(sec['custo'])})."
            )
        return " ".join(lines)

    if intent == "forecast":
        fc = ctx.get("forecast") or {}
        kwh_fc = fc.get("kwh_total", 0)
        modelo = fc.get("modelo", "")
        if kwh_fc:
            custo_fc = kwh_fc * tarifa
            modelo_txt = f" (modelo: {modelo})" if modelo and modelo not in ("insuficiente", "erro") else ""
            return (
                f"📈 Previsão para os próximos 7 dias{modelo_txt}: "
                f"{_fmt_kwh(kwh_fc)} (~{_fmt_brl(custo_fc)}). "
                "Reduza o uso de ar-condicionado e chuveiro elétrico nos horários de pico (18h–21h) para economizar."
            )
        return "Ainda não há dados suficientes para gerar uma previsão confiável."

    if intent == "anomaly":
        anomalies = ctx.get("anomalies") or []
        if not anomalies:
            return "✅ Nenhuma anomalia de consumo detectada nos últimos 7 dias. Parabéns!"
        items = [
            f"**{a['device']}** em {a['day']}: {a['kwh']} kWh (esperado ~{a['esperado']} kWh, z={a['z']})"
            for a in anomalies[:3]
        ]
        return "⚠️ Consumo anormal detectado:\n" + "\n".join(f"• {i}" for i in items)

    if intent == "economy" and ranking:
        top = _top_device(ranking)
        eco_15 = top["custo"] * 0.15
        eco_20 = top["custo"] * 0.20
        return (
            f"💡 Dicas de economia:\n"
            f"• Reduza 15% do uso de **{top['name']}** → economize ~{_fmt_brl(eco_15)}/mês.\n"
            f"• Reduza 20% → ~{_fmt_brl(eco_20)}/mês.\n"
            "• Evite o horário de pico (18h–21h) para aparelhos de alto consumo.\n"
            "• Desligue dispositivos em standby quando não estiver em casa."
        )

    if intent == "cost":
        return (
            f"💰 Nos últimos 30 dias o custo estimado foi {_fmt_brl(custo)} "
            f"({_fmt_kwh(total)} × {_fmt_brl(tarifa)}/kWh)."
        )

    if intent == "devices" and ranking:
        lines = [f"• {r['name']} ({r.get('room', '–')}): {_fmt_kwh(r['kwh'])}" for r in ranking[:5]]
        return "🔌 Aparelhos registrados (top 5 por consumo):\n" + "\n".join(lines)

    # Resposta geral com resumo completo
    eco_pot = float(ctx.get("economiaPotencial", 0))
    return (
        f"⚡ Resumo dos últimos 30 dias:\n"
        f"• Consumo total: {_fmt_kwh(total)}\n"
        f"• Custo estimado: {_fmt_brl(custo)}\n"
        f"• Economia potencial: {_fmt_brl(eco_pot)}/mês\n\n"
        "Pergunte sobre: ranking de consumo, previsão, anomalias, dicas de economia ou custo."
    )


# ---------------------------------------------------------------------------
# Integração Anthropic (opcional)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "Você é o assistente inteligente do SmartEnergy, especializado em gestão energética residencial. "
    "Responda SEMPRE em português do Brasil, de forma clara, objetiva e prática. "
    "Use SOMENTE os dados fornecidos no contexto. "
    "Nunca invente valores. Se os dados não permitirem responder, diga isso claramente. "
    "Sugira ações concretas e específicas para reduzir o consumo de energia."
)


def _claude_response(message: str, ctx: Context, api_key: str) -> str:
    try:
        import anthropic  # type: ignore
        client = anthropic.Anthropic(api_key=api_key)
        context_json = json.dumps(ctx, ensure_ascii=False, default=str)
        result = client.messages.create(
            model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-5"),
            max_tokens=800,
            system=SYSTEM_PROMPT + f"\n\nDados do contexto:\n{context_json}",
            messages=[{"role": "user", "content": message}],
        )
        return str(result.content[0].text)
    except Exception as exc:
        logger.warning("[Chat] Falha na API Anthropic: %s. Usando regras locais.", exc)
        return _rules_response(message, ctx)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_chat(message: str, context: Context) -> Dict[str, str]:
    """
    Processa uma mensagem do usuário e retorna a resposta do assistente.

    Parameters
    ----------
    message : str     — pergunta do usuário
    context : Context — dados do dashboard (total, ranking, forecast, anomalies, tarifa...)

    Returns
    -------
    {"resposta": str}
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()

    if api_key:
        resposta = _claude_response(message, context, api_key)
    else:
        resposta = _rules_response(message, context)

    return {"resposta": resposta}
