import json
import os
from datetime import date, timedelta

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel
from sklearn.linear_model import LinearRegression

app = FastAPI(title="SmartEnergy ML")


class ForecastIn(BaseModel):
    daily: dict[str, float]
    horizon: int = 7


class AnomalyIn(BaseModel):
    devices: dict[str, dict[str, float]]


class ChatIn(BaseModel):
    message: str
    context: dict


def features(days: list[date], t0: date):
    # tendência + dia da semana (one-hot, 6 colunas)
    return [[(d - t0).days, *[int(d.weekday() == k) for k in range(6)]] for d in days]


@app.post("/forecast")
def forecast(b: ForecastIn):
    ds = sorted(b.daily)
    days = [date.fromisoformat(d) for d in ds]
    if len(days) < 14:
        return {"previsao": [], "kwh_total": 0}
    t0 = days[0]
    model = LinearRegression().fit(features(days, t0), [b.daily[d] for d in ds])
    fut = [days[-1] + timedelta(i + 1) for i in range(b.horizon)]
    pred = np.maximum(model.predict(features(fut, t0)), 0)
    return {
        "previsao": [{"day": d.isoformat(), "kwh": round(float(p), 2)} for d, p in zip(fut, pred)],
        "kwh_total": round(float(pred.sum()), 2),
    }


@app.post("/anomalies")
def anomalies(b: AnomalyIn):
    out = []
    for name, days in b.devices.items():
        ds = sorted(days)
        v = [days[d] for d in ds]
        if len(v) < 21:
            continue
        base = np.array(v[:-7])  # histórico de referência
        mu, sd = float(base.mean()), float(base.std()) or 1e-6
        for d, x in list(zip(ds, v))[-7:]:
            z = (x - mu) / sd
            if z > 3:
                out.append({"device": name, "day": d, "kwh": round(x, 2), "esperado": round(mu, 2), "z": round(z, 1)})
    return out


SYSTEM = ("Você é o assistente do SmartEnergy. Responda em português, de forma curta e prática, "
          "usando apenas os dados fornecidos e sugerindo ações concretas de economia.")


def rules(msg: str, c: dict) -> str:
    m, r = msg.lower(), c["ranking"]
    if any(k in m for k in ("maior", "vilão", "vilao", "mais gasta", "ranking")):
        t = r[0]
        return f"O maior consumo é {t['name']} ({t['room']}): {t['kwh']:.1f} kWh em 30 dias, {t['pct']:.0f}% do total (R$ {t['custo']:.2f})."
    if any(k in m for k in ("previs", "próximo", "proximo", "vai gastar")):
        f = c["forecast"]
        return f"Previsão para os próximos 7 dias: {f['kwh_total']:.1f} kWh (~R$ {f['kwh_total'] * c['tarifa']:.2f})."
    if any(k in m for k in ("anorm", "desperd", "estranh", "pico")):
        a = c["anomalies"]
        if not a:
            return "Nenhuma anomalia nos últimos 7 dias."
        return "Consumo anormal: " + "; ".join(f"{x['device']} em {x['day']} ({x['kwh']} kWh vs ~{x['esperado']} esperado)" for x in a)
    if any(k in m for k in ("econom", "reduzir", "dica")):
        t = r[0]
        return (f"Comece por {t['name']}: reduzir 15% do uso economizaria cerca de R$ {t['custo'] * 0.15:.2f} por mês. "
                "Evite o horário de pico (18h–21h) e desligue aparelhos em standby.")
    return (f"Nos últimos 30 dias a casa consumiu {c['total']:.1f} kWh (R$ {c['custo']:.2f}). "
            "Pergunte sobre ranking, previsão, anomalias ou economia.")


@app.post("/chat")
def chat(b: ChatIn):
    key = os.getenv("ANTHROPIC_API_KEY")
    if key:
        import anthropic
        r = anthropic.Anthropic(api_key=key).messages.create(
            model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"), max_tokens=600,
            system=SYSTEM + "\nDados: " + json.dumps(b.context, ensure_ascii=False),
            messages=[{"role": "user", "content": b.message}])
        return {"resposta": r.content[0].text}
    return {"resposta": rules(b.message, b.context)}
