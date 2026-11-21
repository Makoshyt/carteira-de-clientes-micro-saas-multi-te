// Carteira de Clientes — telas de cadastro de empresa, login e logout.
// Sem bibliotecas. Todo texto vindo da API ou do usuário entra no DOM via textContent.
"use strict";

// Nome do item no sessionStorage onde fica a credencial da sessão (não é um segredo).
const ITEM_SESSAO = "carteira-clientes.sessao";

function lerSessao() {
  return sessionStorage.getItem(ITEM_SESSAO);
}

function gravarSessao(valor) {
  sessionStorage.setItem(ITEM_SESSAO, valor);
}

function limparSessao() {
  sessionStorage.removeItem(ITEM_SESSAO);
}

function el(id) {
  return document.getElementById(id);
}

function mostrarMensagem(texto, tipo) {
  const caixa = el("mensagem");
  caixa.textContent = texto;
  caixa.className = "mensagem " + (tipo || "erro");
  caixa.hidden = false;
}

function limparMensagem() {
  const caixa = el("mensagem");
  caixa.textContent = "";
  caixa.hidden = true;
}

// Chama a API com JSON. Devolve {status, dados}; dados é null quando não há corpo JSON.
async function chamarApi(metodo, caminho, corpo) {
  const cabecalhos = { "Accept": "application/json" };
  const credencial = lerSessao();
  if (credencial) {
    cabecalhos.Authorization = ["Bearer", credencial].join(" ");
  }
  const opcoes = { method: metodo, headers: cabecalhos };
  if (corpo !== undefined) {
    cabecalhos["Content-Type"] = "application/json";
    opcoes.body = JSON.stringify(corpo);
  }
  let resposta;
  try {
    resposta = await fetch(caminho, opcoes);
  } catch (e) {
    return { status: 0, dados: { erro: "não foi possível falar com o servidor" } };
  }
  let dados = null;
  const tipo = resposta.headers.get("Content-Type") || "";
  if (resposta.status !== 204 && tipo.indexOf("application/json") === 0) {
    try {
      dados = await resposta.json();
    } catch (e) {
      dados = null;
    }
  }
  return { status: resposta.status, dados: dados };
}

function mensagemDeErro(resultado) {
  if (resultado.dados && typeof resultado.dados.erro === "string") {
    return resultado.dados.erro;
  }
  return "erro inesperado (HTTP " + resultado.status + ")";
}

function mostrarEntrada() {
  el("tela-entrada").hidden = false;
  el("tela-principal").hidden = true;
  el("area-usuario").hidden = true;
  el("usuario-logado").textContent = "";
}

function mostrarPrincipal(usuario) {
  el("tela-entrada").hidden = true;
  el("tela-principal").hidden = false;
  el("area-usuario").hidden = false;
  el("usuario-logado").textContent = usuario.email;
  el("titulo-empresa").textContent = usuario.nome_empresa;
}

// Confere a sessão guardada com GET /api/me e mostra a tela adequada.
async function carregarUsuario() {
  if (!lerSessao()) {
    mostrarEntrada();
    return;
  }
  const r = await chamarApi("GET", "/api/me");
  if (r.status === 200 && r.dados) {
    mostrarPrincipal(r.dados);
    return;
  }
  if (r.status === 401) {
    limparSessao();
    mostrarMensagem("sua sessão expirou; entre novamente");
  } else {
    mostrarMensagem(mensagemDeErro(r));
  }
  mostrarEntrada();
}

async function comBotaoTravado(form, acao) {
  const botao = form.querySelector("button[type=submit]");
  botao.disabled = true;
  try {
    await acao();
  } finally {
    botao.disabled = false;
  }
}

async function entrar(evento) {
  evento.preventDefault();
  const form = evento.currentTarget;
  limparMensagem();
  await comBotaoTravado(form, async function () {
    const r = await chamarApi("POST", "/api/login", {
      email: form.elements.email.value,
      senha: form.elements.senha.value,
    });
    if (r.status === 200 && r.dados && typeof r.dados.token === "string") {
      gravarSessao(r.dados.token);
      form.reset();
      await carregarUsuario();
    } else {
      mostrarMensagem(mensagemDeErro(r));
    }
  });
}

async function cadastrar(evento) {
  evento.preventDefault();
  const form = evento.currentTarget;
  limparMensagem();
  await comBotaoTravado(form, async function () {
    const r = await chamarApi("POST", "/api/empresas", {
      nome_empresa: form.elements.nome_empresa.value,
      email: form.elements.email.value,
      senha: form.elements.senha.value,
    });
    if (r.status === 201) {
      const loginForm = el("form-login");
      loginForm.elements.email.value = (r.dados && r.dados.email) || form.elements.email.value;
      form.reset();
      mostrarMensagem("empresa cadastrada; agora entre com seu e-mail e senha", "sucesso");
      loginForm.elements.senha.focus();
    } else {
      mostrarMensagem(mensagemDeErro(r));
    }
  });
}

async function sair() {
  limparMensagem();
  if (lerSessao()) {
    // Mesmo se a API falhar (ex.: sessão já expirada), a credencial local é descartada.
    await chamarApi("POST", "/api/logout");
  }
  limparSessao();
  mostrarEntrada();
  mostrarMensagem("você saiu", "sucesso");
}

document.addEventListener("DOMContentLoaded", function () {
  el("form-login").addEventListener("submit", entrar);
  el("form-cadastro").addEventListener("submit", cadastrar);
  el("botao-sair").addEventListener("click", sair);
  carregarUsuario();
});
