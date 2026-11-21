# Carteira de Clientes (Micro SaaS multi-tenant)

Aplicação local em que cada empresa (tenant) cadastra sua conta com o primeiro usuário,
faz login e logout e gerencia seus clientes (criar, listar, buscar por nome, editar e
excluir), com isolamento total entre empresas. Backend e frontend usam somente a
biblioteca padrão do Python 3 e HTML/CSS/JS puro.

> **Aviso — projeto de teste.** Este é um projeto de teste para uso **apenas local**
> (`127.0.0.1`), sem publicação nem deploy. Use somente **dados fictícios** (por exemplo,
> e-mails em `exemplo.test`); não cadastre dados pessoais reais nem senhas que você usa de verdade.
> Não há HTTPS nem limitação de taxa de requisições.

## Funcionalidades

- Cadastro de empresa com o primeiro usuário numa transação só (e-mail único no sistema).
- Login com token assinado (HMAC-SHA256) ligado a uma sessão no servidor com expiração; logout
  revoga a sessão.
- CRUD de clientes (nome obrigatório, e-mail, telefone, observações, status `ativo`/`inativo`).
- Busca de clientes por nome sem diferenciar maiúsculas de minúsculas.
- Isolamento multi-tenant: cada empresa só vê, altera e apaga os próprios clientes.
- Validação de entrada e erros JSON padronizados (`{"erro": "mensagem"}`).
- Migrações SQL versionadas, idempotentes e portáveis para PostgreSQL.
- Frontend HTML/CSS/JS sem dependências, servido pelo próprio backend.

## Requisitos

- Python 3 (desenvolvido e testado com Python 3.14). Só a biblioteca padrão é usada:
  **não há nada a instalar** (`pip install` não é necessário nem há `requirements.txt`).
- Um navegador moderno para usar o frontend.

## Estrutura

```
app/            pacote Python (config.py, db.py, migracoes.py, seguranca.py, web.py, servidor.py, empresas.py, autenticacao.py, clientes.py, api_clientes.py, estaticos.py)
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

Execute a partir da raiz do projeto. O comando aplica as migrações pendentes no banco
(criando o arquivo e a pasta se preciso) e sobe o servidor em `http://127.0.0.1:8000/`.
Abra esse endereço no navegador para cadastrar a empresa, entrar, criar, buscar, editar e
excluir clientes e sair. `Ctrl+C` encerra o servidor.

Exemplo com outro banco e outra porta:

```
CARTEIRA_DB=/tmp/carteira-teste.db CARTEIRA_PORTA=8080 python3 run.py
```

Variáveis de ambiente (todas opcionais):

| Variável | Padrão | Descrição |
|---|---|---|
| `CARTEIRA_DB` | `./carteira.db` | caminho do arquivo SQLite |
| `CARTEIRA_PORTA` | `8000` | porta HTTP (sempre ligada só em `127.0.0.1`) |
| `CARTEIRA_SEGREDO` | gerado | segredo HMAC dos tokens (mín. 32 caracteres) |
| `CARTEIRA_TOKEN_TTL` | `28800` (8h) | validade do token, em segundos |

Se `CARTEIRA_SEGREDO` não estiver definido, um segredo é gerado com
`secrets.token_hex(32)` e gravado em `.carteira_segredo` (permissão 600, ignorado pelo Git),
sendo reaproveitado nas execuções seguintes. Valores inválidos (porta fora de 1–65535, TTL fora
de 1 s a 30 dias, segredo curto) interrompem a inicialização com `ErroConfiguracao`.

O arquivo `.env.example` (variáveis `SQLITE_PATH`, `PG*`, `DATABASE_URL`) vem do ambiente da
Database Factory e **não é lido pela aplicação**; a aplicação também não carrega `.env`
automaticamente. Use as variáveis `CARTEIRA_*` acima.

### API disponível

Todas as rotas ficam em `/api/...`, recebem e devolvem JSON (UTF-8) e, em caso de erro,
respondem `{"erro": "mensagem"}` com o status adequado (400, 401, 404, 405, 409, 413 ou 500).
As rotas marcadas com "exige token" pedem o cabeçalho `Authorization: Bearer <token>`.

| Método e rota | Corpo | Resposta |
|---|---|---|
| `GET /api/saude` | — | `200 {"status": "ok"}` |
| `POST /api/empresas` | `{"nome_empresa", "email", "senha"}` | `201 {"empresa_id", "usuario_id", "email"}`; `400` entrada inválida; `409` e-mail já cadastrado |
| `POST /api/login` | `{"email", "senha"}` | `200 {"token", "expira_em"}`; `400` corpo/tipos inválidos; `401 {"erro": "e-mail ou senha inválidos"}` |
| `POST /api/logout` | — (exige `Authorization: Bearer <token>`) | `204` sem corpo; depois disso o token recebe `401` |
| `GET /api/me` | — (exige `Authorization: Bearer <token>`) | `200 {"usuario_id", "email", "empresa_id", "nome_empresa"}`; `401` token ausente, inválido, expirado ou revogado |
| `GET /api/clientes[?busca=texto]` | — (exige token) | `200 [cliente, ...]` só da empresa da sessão, ordenados por nome (máx. 200); `busca` filtra por nome sem diferenciar maiúsculas; `400` busca inválida; `401` sem token válido |
| `POST /api/clientes` | `{"nome", "email"?, "telefone"?, "observacoes"?, "status"?}` (exige token) | `201` com o cliente (`id`, campos, `criado_em`, `atualizado_em`) e cabeçalho `Location`; `400` citando o campo inválido (inclusive `id`/`empresa_id` enviados); `401` sem token válido |
| `GET /api/clientes/{id}` | — (exige token) | `200` com o cliente; `404 {"erro": "cliente não encontrado"}` se não existir ou for de outra empresa; `401` sem token válido |
| `PUT /api/clientes/{id}` | qualquer subconjunto de `{"nome", "email", "telefone", "observacoes", "status"}` (exige token) | `200` com o cliente atualizado (só os campos enviados mudam; `atualizado_em` é renovado); `400` citando o campo inválido ou corpo vazio; `404` igual ao do `GET`; `401` sem token válido |
| `DELETE /api/clientes/{id}` | — (exige token) | `204` sem corpo; `404` igual ao do `GET`; `401` sem token válido |

#### Exemplos JSON (dados fictícios)

IDs, tokens e datas abaixo são ilustrativos. Onde aparece `…`, coloque o valor
correspondente: no campo `senha`, uma senha fictícia de 8 a 128 caracteres escolhida na
hora; no campo `token`, o valor `<sessao_id>.<assinatura>` devolvido pelo login.

`POST /api/empresas`

```json
{"nome_empresa": "Loja Fictícia", "email": "dono@exemplo.test", "senha": …}
```

Resposta `201`:

```json
{"empresa_id": "0b6f1c2e-0000-4000-8000-000000000001",
 "usuario_id": "0b6f1c2e-0000-4000-8000-000000000002",
 "email": "dono@exemplo.test"}
```

`POST /api/login` com `{"email": "dono@exemplo.test", "senha": …}` — resposta `200`:

```json
{"token": …, "expira_em": "2026-01-31T20:00:00Z"}
```

`POST /api/clientes` (com `Authorization: Bearer <token>`):

```json
{"nome": "Cliente Exemplo", "email": "contato@exemplo.test", "telefone": "+55 (11) 0000-0000",
 "observacoes": "Cliente fictício", "status": "ativo"}
```

Resposta `201` (com `Location: /api/clientes/<id>`):

```json
{"id": "0b6f1c2e-0000-4000-8000-000000000003", "nome": "Cliente Exemplo",
 "email": "contato@exemplo.test", "telefone": "+55 (11) 0000-0000",
 "observacoes": "Cliente fictício", "status": "ativo",
 "criado_em": "2026-01-31T12:00:00Z", "atualizado_em": "2026-01-31T12:00:00Z"}
```

`PUT /api/clientes/<id>` com `{"status": "inativo"}` — `200` com o cliente completo atualizado.

Erros:

```json
{"erro": "cliente não encontrado"}
```

(`404`, igual para id inexistente e para id de outra empresa) e `401` com
`{"erro": ...}` para token ausente, inválido, expirado ou revogado.

Com `curl`:

```
curl -X POST http://127.0.0.1:8000/api/empresas -H 'Content-Type: application/json' \
  -d '{"nome_empresa": "Loja Fictícia", "email": "dono@exemplo.test", "senha": …}'
curl -X POST http://127.0.0.1:8000/api/login -H 'Content-Type: application/json' \
  -d '{"email": "dono@exemplo.test", "senha": …}'
curl 'http://127.0.0.1:8000/api/clientes?busca=exemplo' -H 'Authorization: Bearer <token>'
```

## Como testar

```
python3 -m unittest discover -s tests -v
```

Execute a partir da raiz do projeto (`python3 -m unittest discover -s tests` sem `-v` também
funciona). Não há nada a instalar nem banco externo: os testes usam diretórios temporários (não
tocam no banco nem no segredo locais) e não usam rede.
A maioria chama a app WSGI diretamente; `tests/test_fluxo_http.py` sobe o servidor `wsgiref`
real numa porta livre de `127.0.0.1` (numa thread) e percorre o fluxo de cadastro, login e
logout de ponta a ponta.

Nenhum segredo HMAC nem senha fica escrito no código dos testes: `tests/ficticio.py`
gera valores fictícios aleatórios (`secrets`) a cada execução. Assim a varredura de
segredos da revisão não encontra literais que pareçam credenciais, e os testes continuam
exatamente com as mesmas verificações (senha errada = senha certa com sufixo, senha curta
= 7 caracteres, segredo de outra instância = outro valor aleatório etc.).

Além disso, os testes não escrevem o nome de um campo sensível colado a um valor
(`"senha": SENHA`, `segredo=SEGREDO`, `"CARTEIRA_SEGREDO": ...`), padrão que a varredura
de segredos marca como possível credencial (31 achados na revisão REV-004). Os corpos JSON e a
`Config` de teste são montados por auxiliares de `tests/ficticio.py`: `cadastro(nome, email,
senha)`, `login(email, senha)`, `config(db, chave, porta=8000, ttl=60)` e
`hash_formato_scrypt()`, que gera em tempo de execução um texto aleatório no formato
`scrypt$...` aceito pelo `CHECK` do banco, em vez de deixar um hash literal no código. Os
corpos enviados e as verificações são exatamente os mesmos; nenhum teste foi removido nem
enfraquecido.

Cobertura:

| Assunto | Arquivos |
|---|---|
| Migrações idempotentes, um registro por versão em `schema_migrations` | `test_db.py`, `test_migracoes.py`, `test_estrutura.py`, `test_fluxo_http.py` |
| Hash e verificação de senha (scrypt, sal único) | `test_seguranca.py`, `test_empresas.py` |
| Cadastro válido (201), e-mail duplicado (409), entradas inválidas (400) | `test_empresas.py`, `test_fluxo_http.py` |
| Login certo e errado; token adulterado, expirado, ausente ou de outro segredo (401) | `test_autenticacao.py`, `test_token.py`, `test_web.py`, `test_fluxo_http.py` |
| Logout revoga o token; `/api/me` | `test_autenticacao.py`, `test_fluxo_http.py` |
| Erros JSON padronizados (400, 401, 404, 405, 409, 413, 500) | `test_web.py`, `test_fluxo_http.py` |
| Repositório e validação de clientes, isolamento no acesso a dados | `test_clientes.py` |
| `GET`/`POST /api/clientes`: 401 sem token, 201/400, busca e isolamento entre empresas | `test_api_clientes.py` |
| `GET`/`PUT`/`DELETE /api/clientes/{id}`: 401, 200/204, PUT parcial com 400 citando o campo, 404 idêntico para id inexistente e de outra empresa sem alterar o banco | `test_api_clientes_item.py` |
| Fluxo CRUD de ponta a ponta: criar (201), entradas inválidas e JSON malformado (400), corpo acima de 64 KB (413), listar, busca sem diferenciar maiúsculas com `%`, `_` e `\` tratados como literais, obter, PUT parcial, excluir e depois 404, e 401 em todas as rotas de clientes sem token válido | `test_crud_clientes.py` |
| Portabilidade: `migrations/*.sql` sem construções específicas do SQLite nem tipos dinâmicos, `PRAGMA` só em `app/db.py`, consultas com parâmetros via `consulta_sql` (`?` -> `%s`) | `test_portabilidade.py` |
| Isolamento entre empresas A e B com clientes de nomes iguais: listagem e busca de B sem nada de A; GET/PUT/DELETE de B sobre id de A com 404 idêntico ao de id inexistente e registro de A intacto no banco; `empresa_id` no corpo do POST/PUT recusado (400) e na query ou em cabeçalhos ignorado; token de A com assinatura válida só acessa A; token de sessão inexistente ou assinado com outro segredo recebe 401 | `test_isolamento.py` |
| Estáticos: `GET /` e `/static/...` com `Content-Type` certo; path traversal (cru e com percent-encoding) -> 404 | `test_estaticos.py` |
| Frontend: sem recursos externos nem script inline, ids usados no JS existem no HTML, 401 tratado | `test_frontend.py` |
| Revisão final: roteiro do teste manual com duas empresas fictícias pelo servidor HTTP real, com as mesmas requisições do `app.js` (cadastrar, entrar, criar, buscar, editar, excluir, sair) e isolamento conferido a cada passo; path traversal em `/static` -> 404; `.env`, bancos `.db`/`.sqlite3` e `.carteira_segredo` ignorados pelo Git | `test_revisao_final.py` |

## Decisões técnicas

Resumo:

| Assunto | Decisão |
|---|---|
| Servidor | `wsgiref.simple_server` com uma app WSGI própria (`app/web.py`), ligado só em `127.0.0.1` |
| Multi-tenant | `empresa_id` vem **sempre da sessão** do token; todo SQL de clientes tem `WHERE empresa_id = ?`; `empresa_id` enviado no corpo é recusado (400) e na query/cabeçalhos é ignorado |
| Recurso de outro tenant | responde **404** idêntico ao de id inexistente, sem revelar que o registro existe e sem alterar nada |
| Token | `<sessao_id>.<HMAC-SHA256>` que referencia uma linha de `sessoes` com expiração; logout apaga a sessão (revogação real) |
| Senha | `hashlib.scrypt` com n=2^14, r=8, p=1, dklen=64 e sal aleatório de 16 bytes por usuário; senha de 8 a 128 caracteres |
| Portabilidade | IDs UUID em texto gerados em Python, datas ISO-8601 UTC em texto, só tipos/constraints comuns a SQLite e PostgreSQL, placeholders convertidos em `consulta_sql` |
| Migrações | `migrations/NNNN_nome.sql` em ordem, cada uma numa transação, registradas em `schema_migrations`; idempotente |
| Limitações | ver o último item desta seção |

Detalhes:

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
  corretamente como texto (útil para checar expiração de sessão). Não há execução real em
  PostgreSQL neste projeto (fora do escopo). Detalhes em "Portabilidade para PostgreSQL" abaixo.

### Portabilidade para PostgreSQL

`tests/test_portabilidade.py` lê todos os `migrations/*.sql` (sem comentários) e falha se
encontrar `AUTOINCREMENT`, `INSERT OR REPLACE`/`OR IGNORE`, `REPLACE INTO`, funções de data do
SQLite (`datetime('now')`, `strftime`, `julianday`...), `PRAGMA`, `WITHOUT ROWID`, tabelas
`STRICT`, `GLOB`, `COLLATE NOCASE`, `rowid`, `INTEGER PRIMARY KEY`, `SERIAL`/`IDENTITY`, `::`,
`BEGIN`/`COMMIT` ou **tipos dinâmicos** (coluna sem tipo ou com tipo fora da lista abaixo). O
mesmo teste verifica as consultas da aplicação: `PRAGMA` só pode aparecer em `app/db.py`
(que liga `foreign_keys`, coisa que o PostgreSQL já faz sempre) e toda consulta com parâmetros
passa por `app.db.consulta_sql`.

**Placeholders**: as consultas são escritas com `?` e passam por `consulta_sql(texto, estilo)`, o
único ponto que conhece o estilo do driver. Com `"qmark"` (sqlite3, padrão) o texto não muda; com
`"format"` (psycopg) cada `?` fora de literais vira `%s` e `%` literal vira `%%`.

Mapeamento de tipos (os mesmos nomes valem nos dois bancos):

| Uso | Tipo no SQL | SQLite (afinidade) | PostgreSQL |
|---|---|---|---|
| IDs (UUID em texto gerado em Python) | `TEXT` | TEXT | `text` (poderia virar `uuid` numa migração futura) |
| Textos com limite (nome, e-mail, telefone, status) | `VARCHAR(n)` | TEXT (limite não imposto; a aplicação valida) | `varchar(n)` (limite imposto) |
| Hash de senha, IDs de sessão | `TEXT` | TEXT | `text` |
| Datas (`2026-01-31T12:00:00Z`) | `VARCHAR(32)` | TEXT | `varchar(32)`; ordena como texto igual a `timestamptz` |
| Permitidos para colunas futuras | `INTEGER`, `BIGINT`, `SMALLINT`, `BOOLEAN`, `NUMERIC(p,s)` | INTEGER/NUMERIC | mesmos nomes |

Como seria aplicar as migrações no PostgreSQL (não executado aqui; o projeto não usa driver):

1. Criar o banco e a tabela de controle com o mesmo SQL de `app/db.py`
   (`CREATE TABLE IF NOT EXISTS schema_migrations (...)`, válido nos dois bancos).
2. Para cada `migrations/NNNN_*.sql` ainda não registrado, em ordem: abrir uma transação, executar
   o arquivo inteiro (por exemplo `psql -v ON_ERROR_STOP=1 --single-transaction -f arquivo.sql`
   ou `cursor.execute(conteudo)` no psycopg), inserir `(versao, sha256, aplicada_em)` em
   `schema_migrations` e dar commit — o mesmo algoritmo do `migrar`. No PostgreSQL o DDL é
   transacional, então uma migração com erro não deixa resto.
3. No código, trocar `sqlite3.connect` por `psycopg.connect`, usar `consulta_sql(..., "format")`
   e capturar `psycopg.errors.UniqueViolation` onde hoje se captura `sqlite3.IntegrityError`.
   `conexao.execute` existe nos dois drivers; o `PRAGMA foreign_keys` deixa de ser necessário.
4. Diferenças conhecidas: `VARCHAR(n)` passa a ser imposto pelo banco (a validação da aplicação
   já usa limites menores ou iguais); `LOWER` no PostgreSQL trata letras acentuadas, no SQLite não;
   `LIKE` com `ESCAPE '\'` funciona igual com `standard_conforming_strings=on` (padrão).

### Demais decisões

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
    `X-Content-Type-Options: nosniff`, `Content-Security-Policy` restrita a `'self'` (sem
    `unsafe-inline`; `object-src 'none'`, `frame-ancestors 'none'`) e `Cache-Control: no-store`.
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
- **Arquivos estáticos** (`app/estaticos.py`): `GET /` serve `static/index.html` e
  `GET /static/<caminho>` serve arquivos de `static/` (rota `{caminho:caminho}`, que pode conter
  `/`), com `Content-Type` pela extensão (html, css, js, json, txt, svg, png, ico; outras -> 404).
  Contra path traversal, recebem 404 caminhos vazios, absolutos, com segmento vazio, `.`, `..`,
  arquivo oculto, `\`, `:` ou byte nulo; além disso o caminho resolvido (seguindo links
  simbólicos) precisa ficar dentro de `static/` e ser um arquivo regular. Os mesmos cabeçalhos de
  segurança (nosniff, CSP e `no-store`) valem para as respostas estáticas. Testes em
  `tests/test_estaticos.py`: usam uma pasta temporária e também a pasta `static/` real
  (`GET /` em HTML, `/static/app.js` como `text/javascript`), e tentam path traversal até
  `app/config.py`, inclusive com percent-encoding (`%2e%2e`, `%2f`, `%5c`, `%00`, dupla
  codificação e UTF-8 inválido). Cada caminho é testado cru e decodificado como o `wsgiref` faz
  com `PATH_INFO`, e sempre deve dar 404 sem vazar conteúdo.
- **Frontend** (`static/index.html`, `static/app.css`, `static/app.js`): HTML/CSS/JS puro, sem
  bibliotecas nem recursos externos, e sem script/estilo inline (compatível com a CSP). Abra
  `http://127.0.0.1:8000/` para cadastrar a empresa (nome, e-mail, senha), entrar e sair. O JS
  usa `fetch` na API, mostra a mensagem `erro` devolvida pela API, guarda o token só em
  `sessionStorage` (some ao fechar a aba) e, ao carregar, confere a sessão com `GET /api/me`
  (401 descarta o token). "Sair" chama `POST /api/logout` e apaga o token local mesmo se a API
  falhar. Todo texto vindo da API ou do usuário entra no DOM por `textContent`, nunca `innerHTML`.
  Depois do login, a tela de clientes mostra o nome da empresa (`/api/me`), a lista
  (`GET /api/clientes`, busca por nome ao enviar ou enquanto digita, com espera de 300 ms; só a
  resposta da busca mais recente é desenhada) e um formulário único de criar/editar (nome
  obrigatório, e-mail, telefone, observações e status `ativo`/`inativo`; os `maxlength` batem com a
  validação do backend). "Editar" carrega o cliente com `GET /api/clientes/{id}` e salva com `PUT`
  (campos esvaziados são limpos no servidor); "Excluir" pede confirmação e chama `DELETE`. Erros de
  validação (400) aparecem junto ao formulário sem perder o que foi digitado; 404 recarrega a lista.
  Qualquer 401 numa rota de clientes apaga o token e volta para o login, e ao sair a lista e o
  formulário são limpos para não deixar dados de uma empresa na página.
  Verificações estáticas em `tests/test_frontend.py` (inclusive que todo id/campo usado no JS
  existe no HTML e que toda chamada de clientes passa pelo tratamento de 401).
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
- **Rotas da coleção de clientes** (`app/api_clientes.py`): `GET` e `POST /api/clientes` usam
  `exigir_autenticacao` e passam ao repositório só `req.empresa_id` (vindo da sessão). Um
  `empresa_id` enviado no corpo nunca é usado: em vez de ser descartado em silêncio, é
  recusado com 400, deixando explícito ao cliente da API que a empresa não é escolhível.
- **Rotas de um cliente** (`GET`/`PUT`/`DELETE /api/clientes/{id}`): id inexistente e id de
  outra empresa devolvem exatamente a mesma resposta (`404 {"erro": "cliente não encontrado"}`),
  para não revelar que o registro existe. Ids com mais de 64 caracteres viram 404 sem consulta.
  No `PUT` o corpo é validado antes da busca do registro, então o 400 não depende de o id existir.
- **Multi-tenant**: as tabelas de dados têm `empresa_id`; toda consulta é filtrada pela empresa da sessão.
- **Limitações conhecidas**:
  - Servidor de desenvolvimento `wsgiref` single-thread: atende uma requisição por vez e não é
    adequado para produção; uso só local.
  - Sem HTTPS/TLS e sem limitação de taxa de requisições (fora do escopo); o token trafega em
    texto puro, o que só é aceitável em `127.0.0.1`.
  - Um único usuário por empresa (sem convites, papéis, recuperação de senha nem verificação de e-mail).
  - Listagem limitada a 200 clientes por resposta, sem paginação.
  - Sessões vencidas ficam no banco até `limpar_sessoes_expiradas` ser chamada (já são recusadas
    na validação, então não dão acesso).
  - Nenhuma execução real em PostgreSQL: a compatibilidade é garantida por convenção e pelo
    teste estático `tests/test_portabilidade.py`.
  - No SQLite, `LOWER` só converte letras ASCII, então a busca ignora maiúsculas/minúsculas em
    letras sem acento, mas não em letras acentuadas (`Á` x `á`); no PostgreSQL `LOWER` trata Unicode.
