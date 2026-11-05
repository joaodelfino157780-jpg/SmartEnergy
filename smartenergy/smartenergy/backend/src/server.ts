import express from "express";
import cors from "cors";
import path from "path";
import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();
const app = express();
const ML = process.env.ML_URL ?? "http://localhost:8000";
const TARIFA = Number(process.env.TARIFA_KWH ?? 0.95);

app.use(cors(), express.json());
app.use(express.static(path.join(__dirname, "../../frontend")));

async function ml(route: string, body: unknown) {
  const r = await fetch(ML + route, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`ML ${route}: ${await r.text()}`);
  return r.json();
}

async function buildDashboard() {
  const since = new Date(Date.now() - 60 * 864e5);
  const rows = await prisma.reading.findMany({ where: { day: { gte: since } }, include: { device: true }, orderBy: { day: "asc" } });
  const daily: Record<string, number> = {};
  const perDevice: Record<string, { room: string; days: Record<string, number> }> = {};
  for (const r of rows) {
    const d = r.day.toISOString().slice(0, 10);
    daily[d] = (daily[d] ?? 0) + r.kwh;
    const p = (perDevice[r.device.name] ??= { room: r.device.room, days: {} });
    p.days[d] = (p.days[d] ?? 0) + r.kwh;
  }
  const [forecast, anomalies] = await Promise.all([
    ml("/forecast", { daily, horizon: 7 }),
    ml("/anomalies", { devices: Object.fromEntries(Object.entries(perDevice).map(([k, v]) => [k, v.days])) }),
  ]);
  const last30 = Object.keys(daily).sort().slice(-30);
  const total = last30.reduce((a, d) => a + daily[d], 0);
  const ranking = Object.entries(perDevice)
    .map(([name, v]) => ({ name, room: v.room, kwh: last30.reduce((a, d) => a + (v.days[d] ?? 0), 0) }))
    .sort((a, b) => b.kwh - a.kwh)
    .map((r) => ({ ...r, custo: r.kwh * TARIFA, pct: total ? (r.kwh / total) * 100 : 0 }));
  return {
    total, tarifa: TARIFA, custo: total * TARIFA,
    economiaPotencial: ranking.slice(0, 2).reduce((a, r) => a + r.custo * 0.15, 0),
    series: last30.map((d) => ({ day: d, kwh: daily[d] })),
    ranking, forecast, anomalies,
  };
}

app.get("/api/devices", async (_q, res) => res.json(await prisma.device.findMany()));

app.get("/api/dashboard", async (_q, res) => {
  try { res.json(await buildDashboard()); } catch (e) { res.status(502).json({ error: String(e) }); }
});

app.post("/api/readings", async (req, res) => {
  const { device, room = "Casa", day, kwh } = req.body ?? {};
  if (!device || !day || typeof kwh !== "number") return res.status(400).json({ error: "device, day e kwh são obrigatórios" });
  const d = new Date(day); d.setUTCHours(0, 0, 0, 0);
  const dev = await prisma.device.upsert({ where: { name: device }, update: {}, create: { name: device, room } });
  const reading = await prisma.reading.upsert({
    where: { deviceId_day: { deviceId: dev.id, day: d } }, update: { kwh }, create: { deviceId: dev.id, day: d, kwh },
  });
  res.status(201).json(reading);
});

app.post("/api/chat", async (req, res) => {
  const message = String(req.body?.message ?? "").trim();
  if (!message) return res.status(400).json({ error: "message é obrigatório" });
  try { res.json(await ml("/chat", { message, context: await buildDashboard() })); }
  catch (e) { res.status(502).json({ error: String(e) }); }
});

app.listen(3000, () => console.log("SmartEnergy em http://localhost:3000"));
