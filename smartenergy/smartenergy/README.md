# SmartEnergy

Monitoramento e otimização de consumo de energia em smart homes.

- `backend/`  Node.js + TypeScript + Express + Prisma (SQLite) — API principal e servidor do dashboard
- `ml/`       Python + FastAPI + scikit-learn — previsão, detecção de anomalias e assistente de IA
- `frontend/` HTML + CSS + TypeScript — dashboard e chat

## Como rodar (3 terminais)

```bash
# 1) ML (porta 8000)
cd ml && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8000

# 2) Backend (porta 3000)
cd backend && npm install
npx prisma db push && npm run seed
npm run build:front
npm run dev

# 3) Abra http://localhost:3000
```

Opcional: `export ANTHROPIC_API_KEY=...` antes do uvicorn para o assistente usar um LLM
(sem a chave, ele responde com regras sobre os dados). `TARIFA_KWH` (padrão 0.95) ajusta o custo.

## API
| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/dashboard` | KPIs, série diária, ranking, previsão 7 dias, anomalias |
| GET | `/api/devices` | Lista de aparelhos |
| POST | `/api/readings` | `{ "device": "TV", "room": "Sala", "day": "2026-11-03", "kwh": 0.7 }` |
| POST | `/api/chat` | `{ "message": "Qual aparelho mais gasta?" }` |
