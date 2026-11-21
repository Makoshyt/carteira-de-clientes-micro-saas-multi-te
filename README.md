# Carteira de Clientes (Micro SaaS multi-tenant)

Aplicação local de teste em que cada empresa (tenant) cadastra sua conta, faz login
e gerencia seus clientes, com isolamento total entre empresas. Usa somente a
biblioteca padrão do Python 3 (sem `pip install`). Dados apenas fictícios.

> Estado atual (fase E1, tarefas "estrutura-projeto", "migracao-inicial",
> "executor-migracoes", "hash-senha", "token-assinado", "nucleo-http", "api-cadastro-empresa"
> e "api-login-logout"):
> estrutura do projeto, configuração, migração inicial portável (`migrations/0001_inicial.sql`),
> executor de migrações (`app/db.py`) chamado pelo `run.py`, hash de senha com scrypt e tokens
> assinados com sessões no banco (`app/seguranca.py`), núcleo WSGI com roteador, JSON, erros
> padronizados e exigência de autenticação (`app/web.py`) e as rotas `GET /api/saude`,
> `POST /api/empresas`, `POST /api/login`, `POST /api/logout` e `GET /api/me`
> (`app/servidor.py`, `app/empresas.py`, `app/autenticacao.py`).
> Fase E2 (em andamento): camada de acesso a dados de clientes (`app/clientes.py`) com
> isolamento por empresa; as rotas `/api/clientes` entram nas próximas tarefas.

## Estrutura

```
app/            pacote Python (config.py, db.py, migracoes.py, seguranca.py, web.py, servidor.py, empresas.py, autenticacao.py, clientes.py)
migrations/     migrações versionadas em SQL portável (0001_inicial.sql, ...)
db/             artefatos gerados pela Database Factory (não usados pela aplicação)
static/         frontend HTML/CSS/JS sem dependências
tests/          testes unittest
run.py          ponto de entrada
```

## Como executar

```
python3 run.py
```

Aplica as migrações pendentes no banco e sobe o servidor em `http://127.0.0.1:8000/`.

Variáveis de ambiente:

| Variável | Padrão | Descrição |
|---|---|---|
| `CARTEIRA_DB` | `./carteira.db` | caminho do arquivo SQLite |
| `CARTEIRA_PORTA` | `8000` | porta HTTP (sempre ligada só em `127.0.0.1`) |
| `CARTEIRA_SEGREDO` | gerado | segredo HMAC dos tokens (mín. 32 caracteres) |
| `CARTEIRA_TOKEN_TTL` | `28800` (8h) | validade do token, em segundos |

Se `CARTEIRA_SEGREDO` não estiver definido, um segredo é gerado com
`secrets.token_hex(32)` e gravado em `.carteira_segredo` (permissão 600, ignorado pelo Git),
sendo reaproveitado nas execuções seguintes.

### API disponível

| Método e rota | Corpo | Resposta |
|---|---|---|
| `GET /api/saude` | — | `200 {"status": "ok"}` |
| `POST /api/empresas` | `{"nome_empresa", "email", "senha"}` | `201 {"empresa_id", "usuario_id", "email"}`; `400` entrada inválida; `409` e-mail já cadastrado |
| `POST /api/login` | `{"email", "senha"}` | `200 {"token", "expira_em"}`; `400` corpo/tipos inválidos; `401 {"erro": "e-mail ou senha inválidos"}` |
| `POST /api/logout` | — (exige `Authorization: Bearer <token>`) | `204` sem corpo; depois disso o token recebe `401` |
| `GET /api/me` | — (exige `Authorization: Bearer <token>`) | `200 {"usuario_id", "email", "empresa_id", "nome_empresa"}`; `401` token ausente, inválido, expirado ou revogado |

Exemplo (dados fictícios):

```
curl -X POST http://127.0.0.1:8000/api/empresas -H 'Content-Type: application/json' \
  -d '{"nome_empresa": "Loja Fictícia", "email": "dono@exemplo.test", "senha": "<sua-senha>"}'
```

## Como testar

```
python3 -m unittest discover -s tests -v
```

Os testes usam diretórios temporários (não tocam no banco nem no segredo locais) e não usam rede.
A maioria chama a app WSGI diretamente; `tests/test_fluxo_http.py` sobe o servidor `wsgiref`
real numa porta livre de `127.0.0.1` (numa thread) e percorre o fluxo da fase 1 de ponta a ponta.

Cobertura da fase 1:

| Assunto | Arquivos |
|---|---|
| Migrações idempotentes, um registro por versão em `schema_migrations` | `test_db.py`, `test_migracoes.py`, `test_estrutura.py`, `test_fluxo_http.py` |
| Hash e verificação de senha (scrypt, sal único) | `test_seguranca.py`, `test_empresas.py` |
| Cadastro válido (201), e-mail duplicado (409), entradas inválidas (400) | `test_empresas.py`, `test_fluxo_http.py` |
| Login certo e errado; token adulterado, expirado, ausente ou de outro segredo (401) | `test_autenticacao.py`, `test_token.py`, `test_web.py`, `test_fluxo_http.py` |
| Logout revoga o token; `/api/me` | `test_autenticacao.py`, `test_fluxo_http.py` |
| Erros JSON padronizados (400, 401, 404, 405, 409, 413, 500) | `test_web.py`, `test_fluxo_http.py` |

## Decisões técnicas

- **Só biblioteca padrão**: `wsgiref.simple_server` com uma app WSGI própria, `sqlite3`, `hashlib`, `secrets`, `hmac`.
- **Bind só em 127.0.0.1**: o host não é configurável, para que o servidor nunca fique exposto na rede.
- **Configuração por ambiente** com validação (porta 1–65535, TTL positivo, segredo mínimo de 32
  caracteres); valores inválidos geram `ErroConfiguracao` em vez de rodar com padrões silenciosos.
  O `repr` da configuração mascara o segredo.
- **Conexão** (`app/db.py`, `conectar(caminho)`): toda conexão SQLite liga `PRAGMA foreign_keys=ON`
  (o SQLite vem com chaves estrangeiras desligadas) e usa `row_factory=sqlite3.Row`.
- **Migrações**: arquivos `migrations/NNNN_nome.sql`, aplicados em ordem numérica por
  `app/db.py` (`migrar(conexao)`; `app/migracoes.aplicar(caminho)` é um atalho que abre e fecha
  a conexão). Cada um roda numa transação explícita (`BEGIN` ... `COMMIT`; se falhar, `ROLLBACK`
  e nada dele fica aplicado) e é registrado em `schema_migrations` (versão como chave primária,
  sha256 e data UTC). É idempotente: só as versões ainda não registradas são aplicadas, sem
  duplicar registros. Uma migração já aplicada não pode ser alterada (mudanças vão num novo
  `0002_*.sql`); nomes fora do padrão ou números repetidos são recusados. O executor recusa
  conexões com transação aberta e devolve a conexão no mesmo `isolation_level` em que a recebeu.
- **SQL portável (SQLite e PostgreSQL)**: um único conjunto de arquivos, só com `TEXT`, `VARCHAR(n)`,
  `CHECK`, `UNIQUE`, `REFERENCES`, `DEFAULT` literal e `CREATE INDEX`. Sem `AUTOINCREMENT`/`SERIAL`/
  `IDENTITY` e sem funções de data de um banco: **IDs são UUID em texto** gerados em Python e
  **datas são texto ISO-8601 UTC** de tamanho fixo (`2026-01-31T12:00:00Z`), que comparam e ordenam
  corretamente como texto (útil para checar expiração de sessão). Um teste rejeita construções
  específicas de um banco. Não há execução real em PostgreSQL neste projeto (fora do escopo).
- **Esquema (0001)**: `empresas`, `usuarios` (e-mail único no sistema, `CHECK` que só aceita
  `senha_hash` no formato `scrypt$...`), `sessoes` (chave estrangeira composta
  `(usuario_id, empresa_id)` garante que a sessão é da mesma empresa do usuário) e `clientes`
  (`status` com `CHECK IN ('ativo','inativo')`, padrão `ativo`; índice `(empresa_id, nome)`).
- **Artefatos da Database Factory em `db/`**: o esquema gerado lá (IDs inteiros com
  `AUTOINCREMENT`/`IDENTITY`, `strftime`/`now()`, tabela `status_clientes`, e-mail único só por
  empresa, sem tabela de sessões) contradiz a especificação aprovada, então a aplicação usa
  `migrations/`. Os arquivos de `db/` não foram alterados (regra de não reescrever migrações).
  Um banco criado antes com o esquema de `db/` é recusado com uma mensagem clara; como só contém
  dados fictícios, basta apagá-lo.
- **Senhas** (`app/seguranca.py`): `gerar_hash(senha)` usa `hashlib.scrypt` (n=2^14, r=8, p=1,
  dklen=64) com sal aleatório de 16 bytes de `secrets` por hash e grava
  `scrypt$n$r$p$sal_hex$hash_hex` (a mesma senha gera hashes diferentes; nunca se grava texto
  puro, e o `CHECK` do banco só aceita `scrypt$...`). `verificar_senha(senha, armazenado)` lê os
  parâmetros do próprio valor e compara com `hmac.compare_digest` (tempo constante). Valores
  malformados ou com parâmetros fora de limites seguros (n até 2^20, r até 32, p até 16, hex
  estrito) devolvem `False` em vez de exceção, evitando consumo excessivo de memória se o banco
  for adulterado. O tamanho da senha (8 a 128) é validado na camada da API (`app/empresas.py`).
- **Tokens e sessões** (`app/seguranca.py`): o token tem o formato `<sessao_id>.<assinatura>`, em
  que `sessao_id` é aleatório (`secrets.token_urlsafe(32)`, 256 bits) e a assinatura é
  HMAC-SHA256(segredo, sessao_id) em base64url sem `=`. O token não carrega dados do usuário: ele
  só referencia uma linha de `sessoes`, que guarda `usuario_id`, `empresa_id` e `expira_em`.
  - `criar_sessao(conexao, segredo, usuario_id, empresa_id, ttl)` grava a sessão (expira em `ttl`
    segundos, `CARTEIRA_TOKEN_TTL`) e devolve o token.
  - `validar_token(conexao, segredo, token)` confere formato e tamanho, compara a assinatura com
    `hmac.compare_digest` (tempo constante) **antes** de tocar no banco e então busca a sessão
    ainda não expirada (`expira_em > agora`, comparação de texto ISO-8601 UTC). Devolve
    `(usuario_id, empresa_id)` ou `None` para token malformado, alterado, assinado com outro
    segredo, expirado ou revogado. A empresa usada pela API virá sempre daqui, nunca do cliente.
  - `revogar_sessao(conexao, segredo, token)` (logout) apaga a sessão; um token com assinatura
    inválida não apaga nada. `limpar_sessoes_expiradas(conexao)` remove sessões vencidas.
  - Por que sessão no servidor em vez de um token autocontido: logout invalida o token de
    verdade (basta apagar a linha) e trocar o segredo invalida todos os tokens de uma vez.
- **Núcleo HTTP** (`app/web.py`): aplicação WSGI própria servida por `wsgiref.simple_server`.
  - `Roteador`: rotas por método e padrão de caminho (`/api/clientes/{id}`; um parâmetro não
    atravessa `/`). Caminho sem rota -> 404; caminho existente com outro método -> 405 com `Allow`.
  - Handlers recebem uma `Requisicao` (método, parâmetros do caminho, query string, cabeçalhos,
    `json()`) e devolvem um objeto (200), `(status, corpo)` ou `(status, corpo, cabeçalhos)`;
    corpo `None` gera resposta vazia (ex.: 204). Respostas em JSON UTF-8 com `Content-Length`,
    `X-Content-Type-Options: nosniff` e `Cache-Control: no-store`.
  - Corpo: limitado a 64 KB pelo `Content-Length` **antes** de ler (acima disso, 413). Corpo vazio,
    `Content-Length` inválido ou incompleto, UTF-8 inválido, JSON inválido (inclusive `NaN`/`Infinity`
    e aninhamento excessivo) ou que não seja objeto -> 400.
  - Erros: `ErroHttp(status, mensagem)` vira `{"erro": mensagem}`, só com 400, 401, 404, 405, 409,
    413 ou 500. Exceção inesperada vira 500 com mensagem genérica; o traceback vai só para o log do
    servidor (`wsgi.errors`), nunca para a resposta.
  - Autenticação: o decorador `exigir_autenticacao` lê `Authorization: Bearer <token>` (esquema sem
    diferenciar maiúsculas), valida com `validar_token` e preenche `req.usuario_id`/`req.empresa_id`;
    token ausente, malformado, alterado, expirado ou revogado -> 401 com `WWW-Authenticate: Bearer`.
  - Cada requisição abre a própria conexão SQLite só se precisar e a fecha ao terminar.
- **Cadastro de empresa** (`app/empresas.py`, `POST /api/empresas`): valida `nome_empresa`
  (texto, 1 a 120 caracteres após aparar espaços, sem caracteres de controle), `email` (texto,
  aparado e convertido para minúsculas, até 254 caracteres, formato básico `local@dominio.tld`
  sem espaços nem `@` extra) e `senha` (texto de 8 a 128 caracteres, sem aparar). O hash scrypt é
  calculado **antes** de abrir a transação (scrypt é lento de propósito) e os dois `INSERT`
  (empresa e usuário) rodam numa única transação: se o segundo falhar, nada fica gravado. Os IDs
  são UUID gerados no servidor; ids enviados no corpo são ignorados. E-mail repetido -> 409
  (checado antes; se outro cadastro gravar o mesmo e-mail no meio, o `UNIQUE` do banco gera
  `IntegrityError`, convertido também em 409). A resposta nunca contém senha nem hash.
- **Login, logout e /api/me** (`app/autenticacao.py`): o login normaliza o e-mail (aparado e em
  minúsculas, igual ao cadastro) e responde sempre a mesma mensagem genérica no 401, sem revelar
  se o erro está no e-mail ou na senha. Quando o e-mail não existe, uma verificação scrypt contra
  um hash fictício é feita mesmo assim, para que o tempo de resposta não denuncie e-mails
  cadastrados. Campos ausentes ou que não são texto -> 400 (erro de formato, não de credencial).
  Cada login cria uma sessão própria; `expira_em` (ISO-8601 UTC) = agora + `CARTEIRA_TOKEN_TTL`.
  O logout apaga só a sessão do token usado (outras sessões do mesmo usuário continuam válidas) e
  responde 204. `/api/me` consulta usuário e empresa pelos ids da sessão, nunca por dados do cliente.
- **Repositório de clientes** (`app/clientes.py`): `listar(conexao, empresa_id, busca=None)`,
  `obter(conexao, empresa_id, id)`, `criar(conexao, empresa_id, dados)`,
  `atualizar(conexao, empresa_id, id, dados)` e `excluir(conexao, empresa_id, id)`. A conexão é
  o primeiro argumento (na API, `req.conexao`). Todo SQL é fixo, parametrizado e tem
  `WHERE empresa_id = ?`; sem `empresa_id` a função recusa (`ValueError`) em vez de consultar
  tudo. Cliente de outra empresa é tratado como inexistente (`None`/`False`, que a API
  transformará em 404) e nada é alterado. A busca usa `LOWER(nome) LIKE LOWER(?) ESCAPE '\'`
  com `%`, `_` e `\` escapados (são buscados literalmente), ordena por `LOWER(nome)` e devolve
  no máximo 200 clientes. Validação em `validar_cliente(dados, parcial)` (erro 400 citando o
  campo): `nome` obrigatório na criação (1 a 120 depois de aparar), `email` opcional em formato
  básico (até 254, normalizado em minúsculas), `telefone` opcional até 30 só com dígitos,
  espaços e `+ ( ) -`, `observacoes` até 2000 (permite quebra de linha), `status`
  `ativo`/`inativo` (padrão `ativo`), `busca` até 200. Texto vazio em campo opcional vira
  `null`; tipo errado é rejeitado. Campos desconhecidos — inclusive `id` e `empresa_id` — são
  rejeitados com 400 (a empresa vem só da sessão). `atualizar` é parcial: só os campos
  enviados mudam, e uma entrada inválida não altera nada no banco.
- **Multi-tenant**: as tabelas de dados têm `empresa_id`; toda consulta é filtrada pela empresa da sessão.
- **Limitações**: servidor de desenvolvimento single-thread, sem HTTPS e sem rate limiting (fora do escopo).
  No SQLite, `LOWER` só converte letras ASCII, então a busca ignora maiúsculas/minúsculas em
  letras sem acento, mas não em letras acentuadas (`Á` x `á`); no PostgreSQL `LOWER` trata Unicode.
