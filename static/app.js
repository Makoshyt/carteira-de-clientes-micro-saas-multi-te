// Carteira de Clientes — cadastro de empresa, login/logout e gestão de clientes
// (lista com busca por nome, criar, editar e excluir).
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
  el("titulo-empresa").textContent = "Sua empresa";
  // Não deixa dados da empresa anterior na página depois de sair.
  limparTelaClientes();
}

function mostrarPrincipal(usuario) {
  el("tela-entrada").hidden = true;
  el("tela-principal").hidden = false;
  el("area-usuario").hidden = false;
  el("usuario-logado").textContent = usuario.email;
  el("titulo-empresa").textContent = usuario.nome_empresa;
}

// Sessão inválida/expirada/revogada: descarta o token e volta para o login.
function sessaoPerdida() {
  limparSessao();
  mostrarEntrada();
  mostrarMensagem("sua sessão expirou; entre novamente");
}

// Chamada a rota protegida: devolve null (e volta ao login) se a API responder 401.
async function chamarApiProtegida(metodo, caminho, corpo) {
  const r = await chamarApi(metodo, caminho, corpo);
  if (r.status === 401) {
    sessaoPerdida();
    return null;
  }
  return r;
}

// ---------------------------------------------------------------- clientes

function caminhoCliente(id) {
  return "/api/clientes/" + encodeURIComponent(id);
}

let sequenciaListagem = 0;
let temporizadorBusca = null;

function limparTelaClientes() {
  sequenciaListagem += 1; // invalida respostas de listagens ainda em andamento
  if (temporizadorBusca !== null) {
    clearTimeout(temporizadorBusca);
    temporizadorBusca = null;
  }
  el("lista-clientes").replaceChildren();
  el("tabela-clientes").hidden = true;
  el("estado-lista").textContent = "";
  el("campo-busca").value = "";
  novoCliente();
}

function celula(texto) {
  const td = document.createElement("td");
  td.textContent = texto || "—";
  return td;
}

function botao(texto, classe, acao) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = texto;
  if (classe) {
    b.className = classe;
  }
  b.addEventListener("click", acao);
  return b;
}

function linhaCliente(cliente) {
  const tr = document.createElement("tr");
  tr.appendChild(celula(cliente.nome));
  tr.appendChild(celula(cliente.email));
  tr.appendChild(celula(cliente.telefone));

  const tdStatus = document.createElement("td");
  const etiqueta = document.createElement("span");
  etiqueta.className = "etiqueta " + (cliente.status === "inativo" ? "inativo" : "ativo");
  etiqueta.textContent = cliente.status;
  tdStatus.appendChild(etiqueta);
  tr.appendChild(tdStatus);

  const tdAcoes = document.createElement("td");
  tdAcoes.className = "acoes";
  tdAcoes.appendChild(botao("Editar", "secundario", function () {
    editarCliente(cliente.id);
  }));
  tdAcoes.appendChild(botao("Excluir", "perigo", function () {
    excluirCliente(cliente);
  }));
  tr.appendChild(tdAcoes);
  return tr;
}

// GET /api/clientes[?busca=...]: redesenha a tabela com os clientes da empresa logada.
async function carregarClientes() {
  const minhaVez = ++sequenciaListagem;
  const busca = el("campo-busca").value.trim();
  let caminho = "/api/clientes";
  if (busca) {
    caminho += "?busca=" + encodeURIComponent(busca);
  }
  el("estado-lista").textContent = "carregando…";
  const r = await chamarApiProtegida("GET", caminho);
  if (r === null || minhaVez !== sequenciaListagem) {
    return; // sessão perdida ou já existe uma listagem mais recente
  }
  if (r.status !== 200 || !Array.isArray(r.dados)) {
    el("estado-lista").textContent = mensagemDeErro(r);
    return;
  }
  const corpo = el("lista-clientes");
  corpo.replaceChildren();
  for (const cliente of r.dados) {
    corpo.appendChild(linhaCliente(cliente));
  }
  el("tabela-clientes").hidden = r.dados.length === 0;
  if (r.dados.length === 0) {
    el("estado-lista").textContent = busca
      ? "nenhum cliente encontrado para essa busca"
      : "nenhum cliente cadastrado ainda";
  } else {
    el("estado-lista").textContent =
      r.dados.length === 1 ? "1 cliente" : r.dados.length + " clientes";
  }
}

function buscar(evento) {
  evento.preventDefault();
  if (temporizadorBusca !== null) {
    clearTimeout(temporizadorBusca);
    temporizadorBusca = null;
  }
  carregarClientes();
}

// Busca enquanto digita, com uma pequena espera para não chamar a API a cada tecla.
function buscaDigitada() {
  if (temporizadorBusca !== null) {
    clearTimeout(temporizadorBusca);
  }
  temporizadorBusca = setTimeout(function () {
    temporizadorBusca = null;
    carregarClientes();
  }, 300);
}

function limparBusca() {
  el("campo-busca").value = "";
  carregarClientes();
}

function mostrarErroFormulario(texto) {
  const caixa = el("erro-form-cliente");
  caixa.textContent = texto;
  caixa.hidden = false;
}

function limparErroFormulario() {
  const caixa = el("erro-form-cliente");
  caixa.textContent = "";
  caixa.hidden = true;
}

// Deixa o formulário no modo "criar".
function novoCliente() {
  const form = el("form-cliente");
  form.reset();
  form.elements.cliente_id.value = "";
  form.elements.cliente_status.value = "ativo";
  el("titulo-form-cliente").textContent = "Novo cliente";
  el("botao-salvar-cliente").textContent = "Criar cliente";
  el("botao-cancelar-edicao").hidden = true;
  limparErroFormulario();
}

// Carrega o cliente (GET /api/clientes/{id}) e põe o formulário no modo "editar".
async function editarCliente(id) {
  limparMensagem();
  const r = await chamarApiProtegida("GET", caminhoCliente(id));
  if (r === null) {
    return;
  }
  if (r.status !== 200 || !r.dados) {
    mostrarMensagem(mensagemDeErro(r));
    if (r.status === 404) {
      carregarClientes();
    }
    return;
  }
  const c = r.dados;
  const form = el("form-cliente");
  novoCliente();
  form.elements.cliente_id.value = c.id;
  form.elements.cliente_nome.value = c.nome || "";
  form.elements.cliente_email.value = c.email || "";
  form.elements.cliente_telefone.value = c.telefone || "";
  form.elements.cliente_observacoes.value = c.observacoes || "";
  form.elements.cliente_status.value = c.status === "inativo" ? "inativo" : "ativo";
  el("titulo-form-cliente").textContent = "Editar cliente";
  el("botao-salvar-cliente").textContent = "Salvar alterações";
  el("botao-cancelar-edicao").hidden = false;
  form.elements.cliente_nome.focus();
}

// POST /api/clientes (novo) ou PUT /api/clientes/{id} (edição). Campos vazios viram null.
async function salvarCliente(evento) {
  evento.preventDefault();
  const form = evento.currentTarget;
  limparMensagem();
  limparErroFormulario();
  const nome = form.elements.cliente_nome.value.trim();
  if (!nome) {
    mostrarErroFormulario("nome é obrigatório");
    form.elements.cliente_nome.focus();
    return;
  }
  const corpo = {
    nome: nome,
    email: form.elements.cliente_email.value.trim(),
    telefone: form.elements.cliente_telefone.value.trim(),
    observacoes: form.elements.cliente_observacoes.value.trim(),
    status: form.elements.cliente_status.value,
  };
  const id = form.elements.cliente_id.value;
  await comBotaoTravado(form, async function () {
    const r = id
      ? await chamarApiProtegida("PUT", caminhoCliente(id), corpo)
      : await chamarApiProtegida("POST", "/api/clientes", corpo);
    if (r === null) {
      return;
    }
    if (r.status === 200 || r.status === 201) {
      novoCliente();
      mostrarMensagem(id ? "cliente atualizado" : "cliente criado", "sucesso");
      await carregarClientes();
    } else if (r.status === 404) {
      novoCliente();
      mostrarMensagem(mensagemDeErro(r));
      await carregarClientes();
    } else {
      // Erros de validação (400 etc.) aparecem junto ao formulário, sem perder o que foi digitado.
      mostrarErroFormulario(mensagemDeErro(r));
    }
  });
}

// DELETE /api/clientes/{id}, depois de confirmar com o usuário.
async function excluirCliente(cliente) {
  limparMensagem();
  if (!window.confirm("Excluir o cliente \"" + cliente.nome + "\"? Esta ação não pode ser desfeita.")) {
    return;
  }
  const r = await chamarApiProtegida("DELETE", caminhoCliente(cliente.id));
  if (r === null) {
    return;
  }
  if (r.status === 204) {
    if (el("form-cliente").elements.cliente_id.value === cliente.id) {
      novoCliente();
    }
    mostrarMensagem("cliente excluído", "sucesso");
  } else {
    mostrarMensagem(mensagemDeErro(r));
  }
  await carregarClientes();
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
    await carregarClientes();
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
  el("form-busca").addEventListener("submit", buscar);
  el("campo-busca").addEventListener("input", buscaDigitada);
  el("botao-limpar-busca").addEventListener("click", limparBusca);
  el("form-cliente").addEventListener("submit", salvarCliente);
  el("botao-cancelar-edicao").addEventListener("click", function () {
    limparMensagem();
    novoCliente();
  });
  carregarUsuario();
});
