declare const Chart: any;
const $ = (id: string) => document.getElementById(id)!;
const brl = (n: number) => n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

const token = localStorage.getItem("token");
if (!token) location.href = "cadastro.html";

async function api(path: string, method = "GET", body?: unknown) {
  try {
    const r = await fetch(path, {
      method,
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (r.status === 401) { localStorage.removeItem("token"); location.href = "cadastro.html"; return {}; }
    const text = await r.text();
    try { return JSON.parse(text); } catch { return { error: text || "Resposta inválida do servidor." }; }
  } catch {
    return { error: "Não foi possível conectar ao servidor." };
  }
}

async function load() {
  const me = await api("/api/me");
  const premium = me.plano === "PREMIUM";
  $("plano").textContent = premium ? "⭐ Premium" : "Plano Normal";

  const d = await api("/api/dashboard");
  if (d.error) { $("ranking").textContent = "Erro ao carregar: " + d.error; return; }

  $("kpi-kwh").textContent = d.total.toFixed(1) + " kWh";
  $("kpi-custo").textContent = brl(d.custo);
  $("kpi-eco").textContent = brl(d.economiaPotencial);
  $("kpi-prev").textContent = d.forecast ? d.forecast.kwh_total.toFixed(1) + " kWh" : "–";

  const hist = d.series as { day: string; kwh: number }[];
  const prev = (d.forecast?.previsao ?? []) as { day: string; kwh: number }[];
  const datasets: any[] = [
    { label: "Histórico", data: [...hist.map((p) => p.kwh), ...prev.map(() => null)], borderColor: "#0f9d58", tension: 0.3 },
  ];
  if (prev.length) {
    datasets.push({
      label: "Previsão (IA)",
      data: [...hist.map((_, i) => (i === hist.length - 1 ? hist[i].kwh : null)), ...prev.map((p) => p.kwh)],
      borderColor: "#f29900",
      borderDash: [6, 4],
      tension: 0.3,
    });
  }
  new Chart($("chart"), { type: "line", data: { labels: [...hist, ...prev].map((p) => p.day.slice(5)), datasets } });

  $("ranking").innerHTML = d.ranking
    .map((r: any) => `<div class="bar"><span><b>${esc(r.name)}</b><em>${r.kwh.toFixed(1)} kWh · ${brl(r.custo)}</em></span><div><i style="width:${r.pct}%"></i></div></div>`)
    .join("");

  // Anomalias
  if (d.anomalies) {
    $("anomalies").innerHTML = d.anomalies.length
      ? `<ul>${d.anomalies.map((a: any) => `<li class="warn"><b>${esc(a.device)}</b> em ${esc(a.day)}: ${a.kwh} kWh (esperado ~${a.esperado})</li>`).join("")}</ul>`
      : `<p class="muted">Nenhum consumo anormal nos últimos 7 dias.</p>`;
  } else {
    $("anomalies").innerHTML = `<p class="muted">Nenhum consumo anormal nos últimos 7 dias.</p>`;
  }

  // Relatório avançado — apenas Premium
  if (premium) {
    const rel = await api("/api/relatorio");
    if (Array.isArray(rel)) {
      $("relatorio").innerHTML = `<table>
        <tr><th>Aparelho</th><th>Últimos 30 dias</th><th>30 dias anteriores</th><th>Variação</th><th>Custo</th></tr>
        ${rel.map((r: any) => `<tr>
          <td>${esc(r.name)}</td>
          <td>${r.atual.toFixed(1)} kWh</td>
          <td>${r.anterior.toFixed(1)} kWh</td>
          <td class="${r.variacao > 0 ? "up" : "down"}">${r.variacao.toFixed(0)}%</td>
          <td>${brl(r.custo)}</td>
        </tr>`).join("")}
      </table>`;
    }
  } else {
    $("relatorio").innerHTML = `<p class="muted">Relatório comparativo disponível no plano Premium.</p>`;
  }

  // Assistente virtual — disponível para todos os planos
  say("Olá! Pergunte sobre seu consumo, ranking de aparelhos, custo ou dicas de economia.", "b");
}

function say(text: string, who: "u" | "b") {
  const el = document.createElement("div");
  el.className = "m " + who;
  el.textContent = text;
  $("log").appendChild(el);
  $("log").scrollTop = $("log").scrollHeight;
}

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("msg") as HTMLInputElement;
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  say(message, "u");
  const r = await api("/api/chat", "POST", { message });
  say(r.resposta ?? r.error ?? "Sem resposta.", "b");
});

$("sair").addEventListener("click", () => {
  localStorage.removeItem("token");
  location.href = "cadastro.html";
});

load();
