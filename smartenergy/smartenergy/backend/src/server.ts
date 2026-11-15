import express, { NextFunction, Request, Response } from "express";
import cors from "cors";
import path from "path";
import bcrypt from "bcryptjs";
import jwt from "jsonwebtoken";
import { PrismaClient } from "@prisma/client";
import type { User } from "@prisma/client";

// ---------------------------------------------------------------------------
// Inicialização
// ---------------------------------------------------------------------------

const prisma = new PrismaClient();
const app = express();

const ML = process.env.ML_URL ?? "http://localhost:8000";
const TARIFA = Number(process.env.TARIFA_KWH ?? 0.95);
const JWT_SECRET = process.env.JWT_SECRET ?? "dev-secret";
const PORT = Number(process.env.PORT) || 3000;

app.use(cors(), express.json());
app.use(express.static(path.join(__dirname, "../../frontend")));

// ---------------------------------------------------------------------------
// Autenticação — JWT
// ---------------------------------------------------------------------------

type Authed = Request & { user: User };

const sign = (id: number): string =>
  jwt.sign({ id }, JWT_SECRET, { expiresIn: "7d" });

/**
 * Middleware de autenticação.
 * O plano vem SEMPRE do banco de dados — nunca do token nem do frontend.
 */
async function auth(
  req: Request,
  res: Response,
  next: NextFunction
): Promise<void> {
  try {
    const token = (req.headers.authorization ?? "").replace("Bearer ", "");
    const { id } = jwt.verify(token, JWT_SECRET) as { id: number };
    const user = await prisma.user.findUnique({ where: { id } });
    if (!user) throw new Error("Usuário não encontrado.");
    (req as Authed).user = user;
    next();
  } catch {
    res.status(401).json({ error: "Faça login para continuar." });
  }
}

/** Exige plano Premium. */
function premium(req: Request, res: Response, next: NextFunction): void {
  if ((req as Authed).user.plano === "PREMIUM") {
    next();
    return;
  }
  res.status(403).json({ error: "Recurso exclusivo do plano Premium." });
}

// ---------------------------------------------------------------------------
// Rotas de autenticação
// ---------------------------------------------------------------------------

/**
 * Cadastro de novo usuário.
 * O plano enviado pelo frontend é aceito diretamente — sem gateway de pagamento.
 * Valores válidos: "FREE" (padrão) ou "PREMIUM".
 */
app.post("/api/auth/cadastro", async (req, res) => {
  const { nome, email, senha, cpfCnpj, plano } = req.body ?? {};
  const cpf = String(cpfCnpj ?? "").replace(/\D/g, "");

  if (
    !nome ||
    !email ||
    ![11, 14].includes(cpf.length) ||
    String(senha ?? "").length < 6
  ) {
    res.status(400).json({
      error:
        "Preencha nome, e-mail, CPF/CNPJ válido e senha (mínimo 6 caracteres).",
    });
    return;
  }

  if (await prisma.user.findUnique({ where: { email } })) {
    res.status(409).json({ error: "Este e-mail já está cadastrado." });
    return;
  }

  const planoFinal = plano === "PREMIUM" ? "PREMIUM" : "FREE";

  const user = await prisma.user.create({
    data: { nome, email, cpfCnpj: cpf, senhaHash: await bcrypt.hash(senha, 10), plano: planoFinal },
  });

  res.status(201).json({ token: sign(user.id), plano: user.plano });
});

app.post("/api/auth/login", async (req, res) => {
  const { email, senha } = req.body ?? {};
  const u = await prisma.user.findUnique({
    where: { email: String(email ?? "") },
  });

  if (!u || !(await bcrypt.compare(String(senha ?? ""), u.senhaHash))) {
    res.status(401).json({ error: "E-mail ou senha inválidos." });
    return;
  }

  res.json({ token: sign(u.id), plano: u.plano });
});

app.get("/api/me", auth, (req, res) => {
  const { nome, email, plano } = (req as Authed).user;
  res.json({ nome, email, plano });
});

// ---------------------------------------------------------------------------
// Atualização de plano (sem pagamento)
// ---------------------------------------------------------------------------

/**
 * Permite alternar entre FREE e PREMIUM sem nenhuma verificação financeira.
 * O plano é atualizado diretamente no banco.
 */
app.post("/api/assinatura/premium", auth, async (req, res) => {
  const user = (req as Authed).user;

  if (user.plano === "PREMIUM") {
    res.status(400).json({ error: "Você já é Premium." });
    return;
  }

  const atualizado = await prisma.user.update({
    where: { id: user.id },
    data: { plano: "PREMIUM" },
  });

  res.json({ plano: atualizado.plano });
});

// ---------------------------------------------------------------------------
// Dados de energia
// ---------------------------------------------------------------------------

async function ml(route: string, body: unknown): Promise<unknown> {
  const r = await fetch(ML + route, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`ML ${route}: ${await r.text()}`);
  return r.json();
}

async function snapshot() {
  const since = new Date(Date.now() - 60 * 864e5);
  const rows = await prisma.reading.findMany({
    where: { day: { gte: since } },
    include: { device: true },
    orderBy: { day: "asc" },
  });
  const daily: Record<string, number> = {};
  const perDevice: Record<string, { room: string; days: Record<string, number> }> = {};
  for (const r of rows) {
    const d = r.day.toISOString().slice(0, 10);
    daily[d] = (daily[d] ?? 0) + r.kwh;
    const p = (perDevice[r.device.name] ??= { room: r.device.room, days: {} });
    p.days[d] = (p.days[d] ?? 0) + r.kwh;
  }
  return { daily, perDevice };
}

const soma = (v: Record<string, number>, ds: string[]): number =>
  ds.reduce((a, d) => a + (v[d] ?? 0), 0);

async function buildDashboard(isPremium: boolean) {
  const s = await snapshot();
  const [forecast, anomalies] = isPremium
    ? await Promise.all([
        ml("/forecast", { daily: s.daily, horizon: 7 }),
        ml("/anomalies", {
          devices: Object.fromEntries(
            Object.entries(s.perDevice).map(([k, v]) => [k, v.days])
          ),
        }),
      ])
    : [null, null];

  const last30 = Object.keys(s.daily).sort().slice(-30);
  const total = soma(s.daily, last30);
  const ranking = Object.entries(s.perDevice)
    .map(([name, v]) => ({ name, room: v.room, kwh: soma(v.days, last30) }))
    .sort((a, b) => b.kwh - a.kwh)
    .map((r) => ({
      ...r,
      custo: r.kwh * TARIFA,
      pct: total ? (r.kwh / total) * 100 : 0,
    }));

  return {
    total,
    tarifa: TARIFA,
    custo: total * TARIFA,
    economiaPotencial: ranking.slice(0, 2).reduce((a, r) => a + r.custo * 0.15, 0),
    series: last30.map((d) => ({ day: d, kwh: s.daily[d] })),
    ranking,
    forecast,
    anomalies,
  };
}

app.get("/api/dashboard", auth, async (req, res) => {
  try {
    res.json(await buildDashboard((req as Authed).user.plano === "PREMIUM"));
  } catch (e) {
    res.status(502).json({ error: String(e) });
  }
});

// Relatório avançado — Premium
app.get("/api/relatorio", auth, premium, async (_req, res) => {
  const s = await snapshot();
  const dias = Object.keys(s.daily).sort();
  const atual = dias.slice(-30);
  const anterior = dias.slice(-60, -30);
  res.json(
    Object.entries(s.perDevice)
      .map(([name, v]) => {
        const a = soma(v.days, atual);
        const b = soma(v.days, anterior);
        return {
          name,
          atual: a,
          anterior: b,
          variacao: b ? ((a - b) / b) * 100 : 0,
          custo: a * TARIFA,
        };
      })
      .sort((x, y) => y.atual - x.atual)
  );
});

// Assistente virtual — disponível para todos os planos
app.post("/api/chat", auth, async (req, res) => {
  const message = String(req.body?.message ?? "").trim();
  if (!message) {
    res.status(400).json({ error: "message é obrigatório" });
    return;
  }
  try {
    const isPremium = (req as Authed).user.plano === "PREMIUM";
    res.json(await ml("/chat", { message, context: await buildDashboard(isPremium) }));
  } catch (e) {
    // Retorna uma resposta amigável em vez de expor detalhes técnicos do erro
    res.json({
      resposta:
        "Desculpe, não consegui processar sua pergunta agora. " +
        "Verifique se o serviço de IA está rodando e tente novamente.",
    });
  }
});

// Ingestão de leituras de dispositivos
app.post("/api/readings", async (req, res) => {
  const { device, room = "Casa", day, kwh } = req.body ?? {};
  if (!device || !day || typeof kwh !== "number") {
    res.status(400).json({ error: "device, day e kwh são obrigatórios" });
    return;
  }
  const d = new Date(day);
  d.setUTCHours(0, 0, 0, 0);
  const dev = await prisma.device.upsert({
    where: { name: device },
    update: {},
    create: { name: device, room },
  });
  res.status(201).json(
    await prisma.reading.upsert({
      where: { deviceId_day: { deviceId: dev.id, day: d } },
      update: { kwh },
      create: { deviceId: dev.id, day: d, kwh },
    })
  );
});

// ---------------------------------------------------------------------------
// Start
// ---------------------------------------------------------------------------

app.listen(PORT, () => {
  console.log(`SmartEnergy backend rodando em http://localhost:${PORT}`);
});
