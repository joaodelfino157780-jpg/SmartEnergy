const $ = (id: string) => document.getElementById(id)!;
const val = (id: string) => (document.getElementById(id) as HTMLInputElement).value.trim();
let modo: "cadastro" | "login" = "cadastro";

function setModo(m: "cadastro" | "login") {
  modo = m;
  document.querySelectorAll<HTMLElement>(".so-cadastro").forEach((e) => (e.hidden = m !== "cadastro"));
  $("tab-cadastro").classList.toggle("on", m === "cadastro");
  $("tab-login").classList.toggle("on", m === "login");
  $("enviar").textContent = m === "cadastro" ? "Criar conta" : "Entrar";
  $("erro").textContent = "";
}

$("tab-cadastro").addEventListener("click", () => setModo("cadastro"));
$("tab-login").addEventListener("click", () => setModo("login"));

$("form").addEventListener("submit", async (e) => {
  e.preventDefault();

  const body =
    modo === "cadastro"
      ? { nome: val("nome"), email: val("email"), cpfCnpj: val("cpf"), senha: val("senha") }
      : { email: val("email"), senha: val("senha") };

  try {
    const r = await (
      await fetch("/api/auth/" + modo, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
    ).json();

    if (!r.token) {
      $("erro").textContent = r.error ?? "Erro inesperado.";
      return;
    }

    localStorage.setItem("token", r.token);
    location.href = "index.html";
  } catch {
    $("erro").textContent = "Não consegui falar com o servidor.";
  }
});
