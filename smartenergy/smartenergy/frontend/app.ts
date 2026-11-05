declare const Chart: any;
const $ = (id: string) => document.getElementById(id)!;
const brl = (n: number) => n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

async function load() {
  const d = await (await fetch("/api/dashboard")).json();
  if (d.error) { $("ranking").textContent = "Erro ao carregar: " + d.error; return; }

  $("kpi-kwh").textContent = d.total.toFixed(1) + " kWh";
  $("kpi-custo").textContent = brl(d.custo);
  $("kpi-prev").textContent = d.forecast.kwh_total.toFixed(1) + " kWh";
  $("kpi-eco").textContent = brl(d.economiaPotencial);

  const hist = d.series as { day: string; kwh: number }[];
  const prev = d.forecast.previsao as { day: string; kwh: number }[];
  const labels = [...hist, ...prev].map((p) => p.day.slice(5));
  const histData = [...hist.map((p) => p.kwh), ...prev.map(() => null)];
  const prevData = [...hist.map((_, i) => (i === hist.length - 1 ? hist[i].kwh : null)), ...prev.map((p) => p.kwh)];
  new Chart($("chart"), {
    type: "line",
    data: { labels, datasets: [
      { label: "Histórico", data: histData, borderColor: "#0f9d58", tension: .3 },
      { label: "Previsão", data: prevData, borderColor: "#f29900", borderDash: [6, 4], tension: .3 },
    ] },
  });

  $("ranking").innerHTML = d.ranking.map((r: any) =>
    `<div class="bar"><span><b>${esc(r.name)}</b><em>${r.kwh.toFixed(1)} kWh · ${brl(r.custo)}</em></span><div><i style="width:${r.pct}%"></i></div></div>`).join("");

  $("anomalies").innerHTML = d.anomalies.length
    ? d.anomalies.map((a: any) => `<li class="warn"><b>${esc(a.device)}</b> em ${esc(a.day)}: ${a.kwh} kWh (esperado ~${a.esperado})</li>`).join("")
    : `<li class="ok">Nenhum consumo anormal nos últimos 7 dias.</li>`;
}

function say(text: string, who: "u" | "b") {
  const el = document.createElement("div");
  el.className = "m " + who; el.textContent = text;
  $("log").appendChild(el); $("log").scrollTop = $("log").scrollHeight;
}

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("msg") as HTMLInputElement;
  const message = input.value.trim(); if (!message) return;
  input.value = ""; say(message, "u");
  try {
    const r = await (await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message }) })).json();
    say(r.resposta ?? r.error, "b");
  } catch { say("Não consegui falar com o servidor.", "b"); }
});

say("Olá! Pergunte sobre seu consumo, previsão, anomalias ou como economizar.", "b");
load();
