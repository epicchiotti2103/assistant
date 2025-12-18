# Assistente Pessoal com Memória (RAG), Agenda/Radar e Voz — Documentação do Projeto

> Objetivo deste documento: registrar **a ideia**, **decisões de arquitetura** e **o que já foi implementado** até agora, para que você (Elio) possa continuar depois com outra IA ou outra pessoa sem ter que reexplicar tudo.

---

## 1) Visão do Produto

Você quer construir um **Assistente Pessoal** com estas capacidades:

1) **Memória consultável (RAG + “casos reais”)**
- Ao finalizar um projeto/troubleshooting, você pede para a IA gerar um **resumo de aprendizados** em **JSON**.
- Em futuras perguntas, o assistente usa esses registros para responder com **seu contexto real**, por exemplo:
  - “Lembra que aquele erro 403 no GCS era permissão writer na conta correta (VM/service account), não no seu e-mail pessoal?”
- Inicialmente, o RAG roda localmente e usa **chunks** para recuperação.

2) **Agenda/Tarefas**
- Tarefas com:
  - **Data marcada** (one-off)
  - **Recorrência** (ex.: todo dia 13)
  - **Radar** (sem data, mas precisa ficar no radar)
- Visões principais:
  - **Hoje**
  - **Próximos N dias** (7/14/30…)
  - (Opcional) Semana Seg–Dom

3) **Voz (captura de recado)**
- Você grava um recado de voz.
- Um modelo (planejado: `gemini-2.5-flash-native-audio-dialog`) faz:
  - áudio → texto
  - limpeza/organização do texto
  - (opcional) extração de tarefas
- O conteúdo entra na base para consulta via RAG.

4) **Multi-modelo**
- Consultas/texto: DeepSeek (plano)
- Voz/transcrição: Gemini (plano)

5) **Armazenamento e execução**
- No começo: roda localmente no Mac (VSCode) com Docker.
- Depois: roda numa **VM** (cloud), usando cache local + **Drive como “fonte da verdade”** para arquivos.
- Integrações:
  - **Telegram Bot** no início (temporário)
  - depois WhatsApp/app próprio (por isso a arquitetura precisa ter adaptadores de canal)

6) **Controle do usuário sobre “usar contexto ou não”**
- Você quer um “botão”/modo:
  - **Modo Puro** (sem RAG, sem memória)
  - **Modo Contexto** (RAG + memórias)
  - (Opcional) **Modo Contexto com Aprovação** (mostra memórias recuperadas e você aprova antes de responder)

---

## 2) Decisões e Princípios de Arquitetura

### 2.1 Separação de “memórias”
- **Agenda/Radar** fica como “3ª memória” (operacional) e deve ser simples/determinística.
- “Casos reais” vs “conhecimento geral”:
  - não precisa separar na UX final; o ideal é **marcar com metadados** e recuperar de forma unificada.
  - em queries de troubleshooting, “casos reais” ganham **peso maior**.

### 2.2 Multiusuário
- Início: pode ser 1 VM por pessoa (ou só você).
- Mesmo assim, o banco já nasce com `user_id` (no MVP usamos `"default"`), para facilitar evolução.

### 2.3 Drive como fonte da verdade (futuro)
- Usar cache local na VM.
- Sincronização:
  - inicialmente periódica (ex.: a cada 10–15 dias) + botão “sync now”
  - incremental por `modifiedTime/hash`
- Core do app **não deve depender diretamente do Drive**: usar interface `StorageBackend` (LocalFS agora; GDrive depois).

### 2.4 Telegram é temporário
- Criar adaptadores de canal (Telegram, WhatsApp, Web/App) para que o core seja o mesmo.

### 2.5 DevOps e Portabilidade
- Começamos com **Docker Compose** desde o início.
- Isso reduz atrito para migrar para VM (Linux) depois.

---

## 3) Stack Atual (Implementado)

### 3.1 Backend
- **FastAPI** (API HTTP)
- **Uvicorn** (servidor ASGI)
- **SQLite** (persistência local em `./data/app.db`)
- **SQLAlchemy** (ORM)
- **python-dateutil** (rrule para recorrências)

### 3.2 Execução local (Mac)
- Rodando via Docker Compose

---

## 4) O que já foi implementado (MVP)

### 4.1 Estrutura de pastas
```
assistant/
├─ app/
│  ├─ main.py
│  ├─ api/
│  │  ├─ tasks.py
│  │  └─ radar.py
│  └─ db/
│     ├─ session.py
│     └─ models.py
├─ data/                # persistência local (fora do git)
├─ docker-compose.yml
├─ Dockerfile
├─ requirements.txt
├─ .env                 # fora do git
├─ .env.example
└─ .gitignore
```

### 4.2 Banco de dados (SQLite)
Tabelas:
- `tasks`
  - `id`, `user_id`, `title`, `notes`
  - `priority` (1 alta .. 5 baixa)
  - one-off: `due_date`
  - recorrente: `rrule` + `start_date`
  - `is_done` (somente para one-off, por enquanto)
  - `created_at`
- `radar_items`
  - `id`, `user_id`, `title`, `notes`, `priority`, `created_at`

### 4.3 Endpoints implementados

#### Saúde
- `GET /health`
  - retorna `{"status":"ok"}`

#### Radar (itens sem data)
- `POST /radar`
  - body: `{ "title": "...", "notes": "...", "priority": 1..5 }`
  - retorna `{ "ok": true, "id": <int> }`

- `GET /radar`
  - retorna lista ordenada por `priority` (asc) e `created_at` (desc)

#### Tarefas
- `POST /tasks`
  - body (one-off):
    - `{ "title": "...", "due_date": "YYYY-MM-DD", "priority": 1..5 }`
  - body (recorrente):
    - `{ "title": "...", "rrule": "FREQ=...;...", "start_date": "YYYY-MM-DD", "priority": 1..5 }`

- `GET /tasks/today`
  - tarefas (one-off + ocorrências recorrentes) para uma data (default hoje)
  - params: `date_ref=YYYY-MM-DD` (opcional)

- `GET /tasks/next?days=14`
  - próximas tarefas em janela rolling (ex.: 7/14/30 dias), com recorrências inclusas
  - params:
    - `days=1..365` (default 14)
    - `date_ref=YYYY-MM-DD` (opcional)

- `GET /tasks/week`
  - mantém visão “Semana Seg–Dom”
  - params: `date_ref=YYYY-MM-DD` (opcional)

### 4.4 Ordenação do “o que fazer primeiro”
Atualmente ordena por:
1) data
2) priority (1 primeiro)
3) título

---

## 5) Como rodar (Dev Local)

### 5.1 Subir
Na raiz do projeto:
```bash
docker compose up --build
```

Deixe o terminal rodando. Em outro terminal, faça testes com `curl`.

### 5.2 Rodar em background
```bash
docker compose up -d
docker compose logs -f
```

Parar:
```bash
docker compose down
```

### 5.3 Reset do banco (DEV)
Quando mudar o schema (ex.: adicionar coluna), o mais fácil em DEV:
```bash
docker compose down
rm -f data/app.db
docker compose up --build
```

---

## 6) Exemplos de uso (curl)

### 6.1 Health
```bash
curl http://localhost:8000/health
```

### 6.2 Criar item de radar
```bash
curl -X POST http://localhost:8000/radar \
  -H "Content-Type: application/json" \
  -d '{"title":"Aprofundar HubSpot","notes":"rever módulos e anotar dúvidas","priority":2}'
```

### 6.3 Listar radar
```bash
curl http://localhost:8000/radar
```

### 6.4 Criar tarefa one-off (com data)
```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"title":"Enviar relatório","due_date":"2025-12-18","priority":1}'
```

### 6.5 Criar tarefa recorrente mensal (todo dia 13)
```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"title":"Fazer fechamento","priority":1,"rrule":"FREQ=MONTHLY;BYMONTHDAY=13","start_date":"2025-12-16"}'
```

### 6.6 Ver hoje / próximos 14 dias
```bash
curl "http://localhost:8000/tasks/today?date_ref=2025-12-16"
curl "http://localhost:8000/tasks/next?days=14&date_ref=2025-12-16"
```

> Observação: recorrências só aparecem se existir ocorrência dentro da janela solicitada.

---

## 7) Controle de versão (GitHub)

Repositório:
- `https://github.com/epicchiotti2103/assistant`

Regras adotadas:
- `.env` **não** vai para o GitHub (segredos).
- `data/` não vai para o GitHub.
- `.DS_Store` e `__pycache__/` não vão para o GitHub.

Comandos:
```bash
git status
git add .
git commit -m "feat: agenda + radar"
git push
```

---

## 8) Limitações atuais (conhecidas)

1) **Recorrentes não têm “concluído por ocorrência”**  
   Ex.: “fechamento de 13/12 feito, mas 13/01 ainda não”.  
   Hoje não controlamos isso. Próxima evolução: tabela `task_completions`.

2) **Sem autenticação / multiusuário real**  
   Hoje usamos `user_id="default"`.  
   Próxima evolução: auth (token/OAuth), separar dados por usuário.

3) **Sem UI**  
   Ainda é via API/curl. Próxima evolução: UI local (Streamlit/NiceGUI ou web).

4) **Sem RAG e sem Drive sync ainda**  
   Implementado só o módulo operacional (agenda/radar) como base.

---

## 9) Roadmap sugerido (próximos passos)

### 9.1 V1 — Qualidade da agenda
- `task_completions` para recorrentes (marcar ocorrência como concluída)
- `GET /agenda/overview`:
  - hoje + próximos 7/14 dias + radar
- regras de priorização (ex.: “vence hoje sempre sobe”)

### 9.2 V2 — UI local
- Página Agenda (hoje/próximos N + radar)
- Página Chat
- Página Memórias (casos reais/notes) e “modo puro vs contexto”

### 9.3 V3 — Memória/RAG local
- Ingestão do JSON de aprendizados
- Chunking + embeddings + vector store (Chroma/FAISS/Qdrant)
- Recuperação com metadados (tags/signals)
- “modo contexto com aprovação”

### 9.4 V4 — Drive como fonte
- `StorageBackend`:
  - LocalFS (agora)
  - GoogleDrive (futuro)
- Sync incremental + cache local
- Indexação automática após sync

### 9.5 V5 — Voz
- Capturar áudio (Telegram inicialmente)
- Gemini transcreve + sumariza + extrai tarefas
- Salvar como documento na base e indexar

### 9.6 V6 — Produto
- Multi-tenant (amigos)
- Hardening de segurança (segredos, logs, rate-limit)
- WhatsApp/app

---

## 10) Checklist para “handoff” (outra pessoa/IA continuar)

- [ ] Rodar `docker compose up --build` e testar `GET /health`
- [ ] Entender endpoints:
  - `/tasks/today`, `/tasks/next`, `/radar`
- [ ] Confirmar persistência em `./data/app.db`
- [ ] Guardar `.env` fora do GitHub
- [ ] Implementar próxima prioridade:
  - `task_completions` + visão única da agenda
- [ ] Depois: RAG + Drive sync

---

## Apêndice A — Observações sobre custo de embeddings (planejamento)
Embeddings via API normalmente é “barato” comparado ao uso de LLM de chat, pois é pago principalmente na ingestão e pode ser cacheado.
(Escolha final ficará para a fase RAG, considerando modelo, custo e privacidade.)

---

**Fim do documento.**
