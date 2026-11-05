# SmartEnergy

Monitoramento e otimização do consumo de energia em Smart Homes.

O SmartEnergy é uma aplicação web inteligente que monitora o consumo energético de aparelhos domésticos, identifica padrões de utilização, prevê gastos futuros e detecta possíveis desperdícios de energia.

## Tecnologias utilizadas

- **Backend:** Node.js, TypeScript, Express e Prisma com SQLite.
- **Machine Learning:** Python, FastAPI e scikit-learn.
- **Frontend:** HTML, CSS e TypeScript.

## Estrutura do projeto

```text
SmartEnergy/
├── backend/
│   └── Node.js + TypeScript + Express + Prisma (SQLite)
├── ml/
│   └── Python + FastAPI + scikit-learn
└── frontend/
    └── HTML + CSS + TypeScript
```

## Como executar o projeto

O projeto utiliza três terminais.

### 1. Machine Learning (porta 8000)

```bash
cd ml

python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\Activate.ps1
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

Inicie o servidor:

```bash
uvicorn main:app --port 8000
```

### 2. Backend (porta 3000)

Abra outro terminal:

```bash
cd backend

npm install
```

Configure o banco de dados:

```bash
npx prisma db push
```

Execute a inicialização dos dados:

```bash
npm run seed
```

Compile o frontend:

```bash
npm run build:front
```

Inicie o backend:

```bash
npm run dev
```

### 3. Acessar a aplicação

Abra o navegador:

http://localhost:3000

## Configurações opcionais

Para habilitar o assistente utilizando um modelo de linguagem da Anthropic, configure a variável de ambiente:

```bash
ANTHROPIC_API_KEY=sua_chave
```

Sem essa chave, o assistente utiliza regras baseadas nos dados disponíveis.

A variável `TARIFA_KWH` permite configurar o custo do consumo energético.

Valor padrão:

```text
0.95
```

## API

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/dashboard` | KPIs, série diária, ranking, previsão de 7 dias e anomalias |
| GET | `/api/devices` | Lista os aparelhos cadastrados |
| POST | `/api/readings` | Registra uma leitura de consumo energético |
| POST | `/api/chat` | Interage com o assistente virtual |

### Exemplo de leitura

```json
{
  "device": "TV",
  "room": "Sala",
  "day": "2026-11-03",
  "kwh": 0.7
}
```

### Exemplo de pergunta ao assistente

```json
{
  "message": "Qual aparelho mais gasta?"
}
```

## Funcionalidades

- Monitoramento do consumo energético.
- Dashboard interativo.
- Ranking dos aparelhos que mais consomem.
- Previsão de consumo para os próximos 7 dias.
- Detecção de anomalias.
- Assistente virtual inteligente.
- Recomendações para economia de energia.

## Objetivo

Transformar dados de consumo energético em informações inteligentes, auxiliando os usuários a reduzir gastos, identificar desperdícios e melhorar a eficiência energética de suas residências.