"""
test_ml.py
==========
Testes de validação dos módulos de ML do SmartEnergy.
Execute com: python test_ml.py
"""

import random
from datetime import date, timedelta


def make_daily(days=60, seed=42):
    """Gera série diária sintética com tendência + sazonalidade semanal + ruído."""
    random.seed(seed)
    base = date(2026, 9, 1)
    daily = {}
    for i in range(days):
        d = base + timedelta(days=i)
        kwh = 20 + 0.05 * i + (3 if d.weekday() >= 5 else 0) + random.gauss(0, 1.5)
        daily[d.isoformat()] = max(0.0, round(kwh, 2))
    return daily


def test_features():
    from features import fill_gaps, build_features, add_lag_features
    import numpy as np

    # fill_gaps: interpola lacuna
    daily = {"2026-01-01": 10.0, "2026-01-03": 12.0}
    filled = fill_gaps(daily)
    assert "2026-01-02" in filled, "fill_gaps deve inserir o dia ausente"
    assert abs(filled["2026-01-02"] - 11.0) < 0.1, "interpolação incorreta"

    # build_features: shape correto
    days = [date(2026, 1, i) for i in range(1, 15)]
    X = build_features(days, days[0])
    assert X.shape == (14, 9), f"shape incorreto: {X.shape}"

    # add_lag_features: remove primeiras max_lag linhas
    y = np.arange(20, dtype=float)
    X2 = build_features([date(2026, 1, i) for i in range(1, 21)], date(2026, 1, 1))
    X_aug, y_aug = add_lag_features(X2, y, lags=(1, 7))
    assert len(X_aug) == len(y_aug) == 20 - 7, "tamanho incorreto após lag"

    print("  [PASS] features.py")


def test_forecaster():
    from forecaster import run_forecast

    daily = make_daily(days=60)
    result = run_forecast(daily, horizon=7)

    assert isinstance(result["previsao"], list), "previsao deve ser lista"
    assert len(result["previsao"]) == 7, "deve retornar 7 dias"
    assert result["kwh_total"] >= 0, "total deve ser não-negativo"
    assert result["modelo"] not in ("insuficiente", "erro"), f"modelo falhou: {result['modelo']}"

    # Verifica que todos os valores são positivos
    for p in result["previsao"]:
        assert p["kwh"] >= 0, f"kwh negativo em {p['day']}"

    print(f"  [PASS] forecaster.py — modelo={result['modelo']}, total={result['kwh_total']} kWh")

    # Verifica dados insuficientes
    result_vazio = run_forecast({"2026-01-01": 10.0}, horizon=7)
    assert result_vazio["previsao"] == [], "deve retornar vazio com poucos dados"
    print("  [PASS] forecaster.py — dados insuficientes tratados corretamente")


def test_anomaly():
    from anomaly import detect_anomalies

    # Gera histórico normal + 1 anomalia clara
    base = date(2026, 9, 1)
    devices = {}
    vals = {}
    random.seed(0)
    for i in range(30):
        d = base + timedelta(days=i)
        vals[d.isoformat()] = 5.0 + random.gauss(0, 0.3)
    # Anomalia: último dia com consumo 10x acima
    ultimo = (base + timedelta(days=29)).isoformat()
    vals[ultimo] = 50.0
    devices["ArCondicionado"] = vals

    result = detect_anomalies(devices)
    assert any(a["device"] == "ArCondicionado" for a in result), "anomalia não detectada"
    anomalia = next(a for a in result if a["device"] == "ArCondicionado")
    assert anomalia["kwh"] == 50.0, "valor errado na anomalia"

    print(f"  [PASS] anomaly.py — detectou {len(result)} anomalia(s)")

    # Verifica dispositivo com dados insuficientes
    result_poucos = detect_anomalies({"TV": {"2026-01-01": 1.0}})
    assert result_poucos == [], "não deve detectar com 1 dia"
    print("  [PASS] anomaly.py — dados insuficientes ignorados corretamente")


def test_chat():
    from chat import run_chat

    ctx = {
        "total": 320.5,
        "custo": 304.5,
        "tarifa": 0.95,
        "economiaPotencial": 25.0,
        "ranking": [
            {"name": "Ar-condicionado", "room": "Quarto", "kwh": 180.0, "custo": 171.0, "pct": 56.2},
            {"name": "Chuveiro", "room": "Banheiro", "kwh": 90.0, "custo": 85.5, "pct": 28.1},
        ],
        "forecast": {"kwh_total": 75.0, "modelo": "GradientBoosting", "previsao": []},
        "anomalies": [],
    }

    for pergunta in [
        "qual aparelho consome mais?",
        "qual a previsão para a semana?",
        "tem alguma anomalia?",
        "como posso economizar?",
        "qual o custo do mês?",
        "quais aparelhos tenho?",
        "resumo geral",
    ]:
        r = run_chat(pergunta, ctx)
        assert "resposta" in r, f"sem campo resposta para: {pergunta}"
        assert len(r["resposta"]) > 10, f"resposta muito curta para: {pergunta}"
        print(f"  [PASS] chat.py — '{pergunta[:40]}' → OK")


if __name__ == "__main__":
    print("\n=== Testes SmartEnergy ML ===\n")
    for test_fn in [test_features, test_forecaster, test_anomaly, test_chat]:
        name = test_fn.__name__
        try:
            test_fn()
        except AssertionError as e:
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")
    print("\n=== Concluído ===")
