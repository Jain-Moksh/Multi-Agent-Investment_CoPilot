# Investment Copilot — Project Context

Single source of truth for the project's design and a running log of what has
been implemented. **Update the "Implementation Log" after every task.**

---

## 1. Goal

A multi-agent, LLM-driven personal investment advisory platform. It analyses
financial news, market data, and the user's own portfolio/behaviour to produce
personalised **Buy / Hold / Sell** recommendations with a **confidence score** and
a **plain-English explanation**. It is a *decision-support assistant*, not a
stock predictor.

Team: 3-person final-year CS/DS major project. Priorities: correctness, clarity,
well-commented code, and a genuinely demoable security layer — not
production-scale performance.

## 2. Architecture (5 layers)

1. **Data Sources** — Financial news, market data, company filings, economic
   indicators, user information.
2. **AI Agent Layer** (narrowly scoped specialists):
   - **News Agent** — reads news, extracts sentiment, affected sectors/companies.
   - **Market Agent** — prices, indices, technical indicators (RSI, MAs).
   - **Portfolio Agent** — user holdings, P/L, allocation, exposure.
   - **User Profiling Agent** — risk appetite (conservative/moderate/aggressive)
     and horizon (short/medium/long) from user behaviour.
   - **Fundamental & Economic Agent** — company ratios, macro/policy indicators.
3. **Reasoning & Decision Layer**
   - **Agent Agreement & Confidence Module** — aggregates agent outputs,
     confidence from inter-agent agreement, flags conflicts.
   - **Recommendation Agent** — final Buy/Hold/Sell + natural-language explanation.
4. **Application Layer** — Dashboard, Portfolio Management, AI Insights,
   Market News, AI Assistant (chatbot).
5. **Storage Layer** — PostgreSQL (structured) + ChromaDB (vector store for RAG
   over news/filings).

## 3. Security Layer (mandatory)

1. **Prompt Injection & Agent Hijacking Defense**
   - Scan all incoming text (news, RSS, PDFs, chat) before it reaches any LLM
     prompt: fast regex/keyword filter → LLM classifier for anything not
     obviously clean. Verdicts **SAFE / SUSPICIOUS / BLOCKED**, stored with the
     content.
   - **Permission system**: each agent has an explicit allow-list of
     actions/data (e.g. News Agent may read news + write `news_events`, but not
     read portfolios or write recommendations). Every action is checked by a
     wrapper before executing, regardless of LLM reasoning.
2. **RAG Poisoning Detection** (before embedding)
   - Reuse the injection scanner.
   - Source-trust score (trusted: Reuters, Economic Times, SEC EDGAR, NSE
     announcements; lower: unknown domains).
   - Flag near-duplicate / anomalous clusters via embedding similarity.
   - Flagged content → **quarantine table**, not the main vector store.

## 4. Data Sources (finalised)

- **News**: GDELT DOC 2.0 API (free, no key), Google News RSS (free, no key),
  Marketaux (free ~100 req/day, key).
- **Market data**: yfinance (`SYMBOL.NS` / `SYMBOL.BO`), NSE via nsepython,
  Alpha Vantage (free 25 req/day) for technical indicators.
- **User data**: manual entry (Portfolio page); one-time Tradebook/CAS CSV
  upload; ongoing sync via Zerodha Kite Connect (personal tier, OAuth consent).

## 5. Tech Stack

| Area | Choice |
|---|---|
| Frontend | React.js, Tailwind CSS, Recharts, Axios |
| Backend | Python, FastAPI (async), APScheduler |
| Auth | JWT via FastAPI `OAuth2PasswordBearer` |
| Databases | PostgreSQL, ChromaDB |
| LLM | Google Gemini or OpenAI (TBD — switchable via `LLM_PROVIDER`) |
| Orchestration | LangGraph |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` (local) |
| Explainability | SHAP, LIME (after Recommendation Agent works) |

## 6. Working Conventions

- Hosted services (DB, vector DB, API keys): the user opens the sign-up /
  authorize link and shares the credentials; then setup is done in code.
- All config is read via `app.core.config.settings` — never `os.environ` directly.
- Secrets live in `backend/.env` (git-ignored); `backend/.env.example` documents them.
- Dependencies are uncommented in `requirements.txt` only when the phase that
  needs them is implemented.
- `pending.md` (repo root) lists actions only the user can do (passwords, keys,
  decisions); Claude updates it whenever a task creates or resolves one.
- Git remote: https://github.com/Jain-Moksh/Multi-Agent-Investment_CoPilot.git (branch `main`).

## 7. Open Decisions

- LLM provider: Gemini vs OpenAI — pending.
- PostgreSQL: local vs hosted (Neon/Supabase) — pending.
- ChromaDB: local persistent (proposed) vs Chroma Cloud — pending.
- Single demo user vs multi-user — pending.
- Proposed: agents emit numeric `signal` (−1..+1) + `confidence` (0..1) +
  `rationale`, so the Agreement module is deterministic and SHAP/LIME have
  numeric features — pending confirmation.

---

## 8. Implementation Log

### 2026-10-02 — Git setup
- `git init` (branch `main`), remote `origin` → GitHub repo above. No commits yet.

### 2026-10-02 — Backend scaffolding
- Created `backend/app/` packages: `core/`, `models/`, `routes/`, `services/`,
  `agents/`, `security/` (each with a docstring `__init__.py`).
- `app/core/config.py` — `Settings` (pydantic-settings) loading `backend/.env`.
- `app/main.py` — FastAPI app, CORS for `http://localhost:5173`, includes routers.
- `app/routes/health.py` — `GET /health`.
- `requirements.txt` — fastapi, uvicorn, pydantic-settings, python-dotenv,
  python-multipart; future deps listed as comments.
- `backend/.env.example`, root `.gitignore`, root `README.md` (setup steps).
- No business logic yet.

### 2026-10-02 — PostgreSQL schema + Alembic
- Models in `backend/app/models/` (SQLAlchemy 2.x, typed `Mapped[]`), split by domain:
  `user.py` (users, user_profiles), `portfolio.py` (portfolio_holdings, transactions),
  `news.py` (news_events), `market.py` (market_snapshots), `logs.py` (agent_logs,
  security_logs), `recommendation.py` (recommendations). `enums.py` holds all enums;
  `base.py` holds `Base` with a constraint naming convention.
- Design choices:
  - Enums stored as VARCHAR + CHECK (not native PG ENUM) → simpler migrations.
  - User-owned tables FK → `users.id` with `ON DELETE CASCADE`; `user_profiles`
    uses `user_id` as PK (one-to-one).
  - Money/quantity = `NUMERIC(18,4)` (fractional MF units / gold grams).
  - `news_events.url` UNIQUE (dedup); `security_status` NOT NULL (content must be
    scanned before storage); `affected_symbols` is `VARCHAR[]`; `sentiment` is a
    float in [-1, 1].
  - `security_logs.details` is JSONB; `recommendations.confidence_score` CHECK 0..1.
  - CHECKs: quantity > 0, prices ≥ 0. Composite indexes for common lookups.
- `app/core/database.py` — async engine, `AsyncSessionLocal`, `get_db` dependency.
- Alembic (async template) in `backend/alembic/`; `env.py` reads `DATABASE_URL` from
  settings (not `alembic.ini`). Initial migration: `versions/2026_10_02_0001_initial_schema.py`
  (revision `0001`, hand-written to mirror the models).
- requirements: + `sqlalchemy[asyncio]`, `asyncpg`, `alembic`.
- Not yet: RAG-poisoning `quarantine` table (comes with the security-layer task).
- (Later verified on real PostgreSQL 18: upgrade, `alembic check` clean, downgrade round trip.)

### 2026-10-02 — Core wiring (config, DB, health)
- `config.py`: `.env` path resolved absolutely (`backend/.env`), works from any cwd;
  added `CORS_ORIGINS` (comma-separated, default Vite 5173 + CRA 3000) →
  `settings.cors_origins_list`; `DATABASE_URL` has a local default so the app boots
  without `.env`.
- `database.py`: asyncpg connect timeout 5s, `check_db_connection()` (`SELECT 1`).
- `main.py`: `lifespan` checks the DB at startup (warns, doesn't crash) and disposes
  the engine on shutdown; CORS from settings.
- `GET /health` → 200 `{"database": "connected"}` or **503** `"unreachable (<Error>)"`.
- Tested with `uvicorn app.main:app --reload`: starts cleanly, CORS preflight OK,
  `/health` = 503 because the DB isn't configured yet (pending P1/P2).
- Found: local PostgreSQL 18 listens on **port 5433**.
- Added `pending.md`: user-side actions (DB setup, decisions, API keys).

### 2026-10-02 — Authentication (JWT + rotating refresh tokens)
- Strategy (details in `docs/auth.md`): **access token** = JWT HS256, 30 min, in
  JSON body, sent as Bearer; **refresh token** = opaque random 256-bit string,
  7 days, **httpOnly cookie** (path `/auth`, SameSite=Lax, Secure outside dev),
  stored as SHA-256 hash in new `refresh_tokens` table. Rotation on every refresh;
  **reuse of a revoked token revokes all of the user's sessions**; logout revokes.
- Endpoints (`app/routes/auth.py`): `POST /auth/signup` (JSON, 201), `POST /auth/login`
  (OAuth2 form: `username`=email), `POST /auth/refresh`, `POST /auth/logout` (204),
  `GET /auth/me` (protected test route).
- `app/core/security.py`: bcrypt via passlib, JWT encode/decode (python-jose,
  `type: "access"` claim checked), refresh-token generate/hash. Constant-time
  login (dummy hash for unknown emails).
- `app/core/dependencies.py`: **`get_current_user`** (OAuth2PasswordBearer) → use
  `Depends(get_current_user)` on every protected route.
- `app/services/auth_service.py`: create/authenticate user, issue/rotate/revoke tokens.
- `app/schemas/` (new package for Pydantic API schemas): `auth.py`.
- Emails stored lowercase; password 8–72 bytes (bcrypt limit).
- Config: `ACCESS_TOKEN_EXPIRE_MINUTES=30`, `REFRESH_TOKEN_EXPIRE_DAYS=7`; blank
  `JWT_SECRET_KEY` refuses to start; default `change-me` logs a warning.
- Migration `0002` (`refresh_tokens`).
- **Gotcha:** passlib 1.7.4 crashes with bcrypt ≥ 4.1 → `bcrypt==4.0.1` pinned.
- Tests: `backend/tests/` (pytest + pytest-asyncio, httpx ASGITransport,
  in-memory SQLite via `get_db` override; only SQLite-compatible tables created).
  `pytest` → 11 passed. Live-Postgres run pending P1/P2.

### 2026-10-02 — News ingestion (`app/services/news_ingestion.py`)
- `fetch_gdelt(keyword, timespan="1h")` → `[{title, url, seendate, domain, sourcecountry}]`;
  adds `sourcelang:english`, quotes multi-word phrases, 75 records, newest first.
- `fetch_google_news_rss(keyword, when="1d")` → `[{title, link, published, source, source_url}]`;
  fetched with httpx (timeouts), parsed with feedparser; strips Google's " - Publisher" title suffix.
- `fetch_marketaux(symbol)` → `[{title, url, description, published_at, source, symbols,
  industry, sentiment_score}]`; sentiment = mean of entity scores for the requested symbol.
  No key → warning + `[]`, no request made.
- `ingest_news_for_watchlist(keywords)` → `IngestionReport(fetched, inserted, duplicates)`.
  Ticker entries (`INFY.NS`) → all 3 sources (text search uses `INFY`); free-text
  (`RBI repo rate`) → GDELT + Google only. Bulk `INSERT … ON CONFLICT (url) DO NOTHING`,
  chunked by 500 rows (PG 32,767-parameter limit).
- Fetchers never raise (timeouts / non-200 / bad JSON → logged, `[]`); `asyncio.gather(
  return_exceptions=True)` so one source's bug can't lose the others.
- **Schema change (migration 0003):** `news_events.security_status` now NULLABLE
  (NULL = "not scanned yet"); added `source_name`, `source_domain` (indexed; needed for
  the Phase-4 source-trust score because Google links are redirects).
  **RULE: agents/RAG must only read rows with `security_status = 'safe'`.**
- **Security fix:** httpx logs full request URLs at INFO → leaked `api_token`. httpx logger
  set to WARNING (now in `http_utils.py`); test asserts keys never appear in logs.
- GDELT throttling: 10 s between calls, 30 s timeout, 2 retries on 429 (15 s / 30 s backoff).
- **Known issue:** GDELT returned 429 for almost every call from this network, even
  after 10+ min idle (one call succeeded). Pipeline degrades gracefully. Idea if it
  persists: batch keywords into one OR-query per call (`(Infosys OR TCS OR …)`).
- **Known limitation:** ticker-based text search is noisy ("INFY" matches unrelated
  articles). Prefer company names, or map ticker → name (e.g. yfinance `shortName`) later.
- Live-verified: Google RSS → 85+ rows inserted into Postgres, re-run skipped duplicates.

### 2026-10-03 — Market data (`app/services/market_data.py`)
- `fetch_yfinance_quote(symbol)` → `Quote(price, change_pct, volume, source="yfinance",
  history=DataFrame[Open,High,Low,Close,Volume] ~22 trading days)`; price from `fast_info`,
  falls back to last closes. Runs in `asyncio.to_thread` (yfinance is sync).
- `fetch_nse_quote(symbol)` → `{"priceInfo": {...}, "industry": ...}` via `nse_eq(base)`;
  20 s timeout; empty response → None.
- `fetch_alphavantage_rsi(symbol)` → `RSIReading(value, as_of, fetched_at, from_cache, stale)`.
  RSI-14 daily. **Cache = DB table `technical_indicators`** (one row per symbol+indicator,
  upserted), so it survives restarts; fresh if < 6 h. Rate limit (`Note`/`Information`
  body) → `AlphaVantageRateLimitError` caught explicitly → 1 h in-process cooldown,
  return stale cached value (`stale=True`) or None. No key → no request.
  Symbol mapping: `RELIANCE.NS` → `RELIANCE.BSE` (Alpha Vantage only lists BSE). **Unverified
  live until a key exists.**
- `update_market_snapshot(symbol)` → `MarketUpdate(quote, rsi, snapshot_id)`: yfinance →
  NSE fallback → writes `market_snapshots` row; RSI failure/crash never blocks the price write.
- **Migration 0004:** `technical_indicators` table; `market_snapshots.source` column.
- Refactor: shared `app/services/http_utils.py` (`http_client`, `safe_get` with 429 retry,
  httpx log silencing) used by news + market services.
- Live-verified: RELIANCE.NS / TCS.NS via yfinance (22-day history) saved to Postgres.
  **NSE returned empty from this network (blocked)**; fallback verified with mocks only.
  `.BO` symbols have thin Yahoo history (1 row) → prefer `.NS`.
- requirements: + httpx, feedparser, yfinance, nsepython, pandas.

### 2026-10-03 — Portfolio: manual holdings, Tradebook import, Zerodha Kite
- **Routes** (`app/routes/portfolio.py`, all need Bearer auth except the callback):
  `GET/POST /portfolio/holdings`, `PUT/DELETE /portfolio/holdings/{id}`,
  `POST /portfolio/import-statement`, `GET /portfolio/zerodha/connect`,
  `GET /portfolio/zerodha/callback`, `GET /portfolio/zerodha/status`,
  `POST /portfolio/zerodha/sync`, `DELETE /portfolio/zerodha`.
- **Holdings** (`services/portfolio_service.py`, `schemas/portfolio.py`): other users'
  ids → 404 (not 403, ids can't be probed); stock symbols upper-cased, default `.NS`;
  quantity > 0, price ≥ 0, max 4 decimals; PUT edits quantity/avg_buy_price only;
  **kite_sync rows are read-only (409)**.
- **Tradebook import** (`services/tradebook_import.py`): Zerodha Console Tradebook CSV
  (`symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,
  trade_id,order_id,order_execution_time`); required: symbol, trade_type, quantity,
  price, trade_date. NSE→`.NS`, BSE→`.BO`; non-EQ segments (F&O etc.) skipped;
  exact `order_execution_time` preferred, times treated as IST; tolerates BOM, header
  case/spaces, Excel day-first dates, "1,250.50". **All-or-nothing**: any bad row →
  422 with every row error, nothing saved. Re-upload safe: dedup on `trade_id`
  (`transactions.external_id`, unique per user+source). 5 MB / 50k-row limits.
  Inserts transactions only (holdings are NOT derived from trades yet).
- **Zerodha** (`services/zerodha.py`): `/connect` returns `{login_url}` (JSON, not a
  redirect: browser navigation can't carry the Bearer token). OAuth `state` = signed
  10-min JWT (`type: kite_oauth_state`) sent via Kite's `redirect_params`; identifies
  the user in the callback and blocks forged callbacks. Callback exchanges
  request_token → access_token (`generate_session`), stores it **Fernet-encrypted**
  (`app/core/crypto.py`, key = HKDF(JWT_SECRET_KEY)), runs a first sync, redirects to
  `FRONTEND_URL/portfolio?zerodha=connected|cancelled|invalid_state|error`.
  Token expiry = next 06:00 IST. `sync_zerodha_holdings(user_id)`: holdings
  (quantity + T1) + today's CNC delivery positions, weighted avg price; skips
  MIS/NRML/F&O/short/zero; upserts `source=kite_sync`; deletes synced rows no longer
  held; manual rows never touched. Kite `TokenException` → connection deleted
  ("reconnect"); network errors keep it. Disconnect removes token + synced rows.
- **Migration 0005:** `portfolio_holdings.source` (+ CHECK) and unique key now
  `(user_id, asset_type, symbol, source)`; `transactions.external_id` + unique
  `(user_id, source, external_id)`; `broker_connections` table.
- **Bug fixed in migrations 0001/0005:** explicit CHECK names were double-prefixed by
  the naming convention in the DB (`ck_x_ck_x_...`, one even truncated). Fixed with
  `op.f()`; verified all 16 CHECK names in the DB == model names. `alembic check`
  does NOT compare CHECK constraints, so this went unnoticed. **Rule: always wrap
  explicit constraint names in migrations with `op.f()`.**
- Config: `FRONTEND_URL`. requirements: + kiteconnect, tzdata.
- Live smoke test on uvicorn + migrated Postgres: `/health` 200 connected, holding added,
  CSV imported then re-upload deduped, `/zerodha/connect` 503 (no key yet).
- Not built: CAS statements (they are PDFs, would need e.g. `casparser`); deriving
  holdings from imported transactions; same-day sells of Kite holdings.

### 2026-10-04 — Background scheduler (`app/core/scheduler.py`)
- APScheduler 3.x `AsyncIOScheduler` on FastAPI's event loop, tz Asia/Kolkata.
  Started in `main.py` lifespan (`start_scheduler()`), stopped on shutdown
  (`stop_scheduler()`: shutdown + cancel in-flight runs) **before** `engine.dispose()`.
- Jobs: `news_ingestion` every 10 min → `ingest_news_for_watchlist(MACRO_SHOCK_KEYWORDS
  ["war","recession","RBI repo rate","crude oil"] + distinct held stock symbols)`;
  `market_update` every 30 min → `update_market_snapshot()` per distinct held stock
  (sequential). Watchlist query = `SELECT DISTINCT symbol FROM portfolio_holdings WHERE
  asset_type='stock'` (FD/gold/property/MF excluded; manual + kite_sync both count).
- Safety: `max_instances=1` (overlapping run skipped), `coalesce=True`,
  `misfire_grace_time=300`; job wrapper (`_logged_job`) never raises, logs start /
  end (status ok|partial|failed, items, succeeded, errors, duration, details) and
  keeps the last run per job in memory. First run after
  `SCHEDULER_FIRST_RUN_DELAY_SECONDS` (60) so `--reload` restarts don't hammer APIs.
- `GET /health/scheduler` (login required: the watchlist reveals what users hold) →
  running, next run times, last-run summaries.
- Config: `SCHEDULER_ENABLED`, `NEWS_INGEST_INTERVAL_MINUTES`,
  `MARKET_UPDATE_INTERVAL_MINUTES`, `SCHEDULER_FIRST_RUN_DELAY_SECONDS`.
  **Run uvicorn with one worker** (each process starts its own scheduler).
- Ingestion changes needed for unattended runs:
  - **GDELT batching:** `fetch_gdelt_many()` / `build_gdelt_query()` → one
    `(a OR "b c" OR d)` query per 10 keywords (`GDELT_BATCH_SIZE`); terms < 3 chars or
    with `&` are skipped (one bad term would fail the batch). `fetch_gdelt(keyword)` kept.
  - **Marketaux rationing:** `MARKETAUX_DAILY_BUDGET=90`/UTC day (enforced inside
    `fetch_marketaux`) + each ticker at most once per `MARKETAUX_SYMBOL_REFRESH=4h`
    (in `ingest_news_for_watchlist`). In-memory counters (reset on restart).
- Live run (uvicorn + migrated PG, real APIs): news job 80 s, 259 articles inserted
  (Google), GDELT 1 batched call → still 429; market job INFY.NS via yfinance in 5 s;
  graceful shutdown logged "Scheduler stopped" before "Application shutdown complete".
- Known gap: a news run is "ok" even if GDELT failed (fetchers return [] on failure,
  indistinguishable from "no articles"); the ERROR lines are in the log.
- requirements: + `apscheduler>=3.10,<4`.

### 2026-10-04 — Debug trace page (dev only, not product UI)
- `GET /debug/trace` → static `app/static/debug_trace.html` (keyword + GDELT timespan
  form, `<pre>` output, no styling). `POST /debug/trace/run?keyword=&timespan=` →
  plain text: STEP 1 raw articles per source (all fields, max 50 shown per call),
  STEP 2 rows written to news_events (re-read from DB by id; shows
  `security_status=NULL (not scanned yet)`), STEP 3 WARNING/ERROR log lines captured
  from `app.services.*` during the run, plus duration.
- No login, so two guards instead: router registered **only when
  `ENVIRONMENT=development`** (`main.py`), and every request must come from
  127.0.0.1 / ::1 (else 403). Runs are real (APIs called, rows written).
- `ingest_news_for_watchlist(..., trace=hook)`: new optional `TraceHook(source, label,
  raw_result | exception)`, so the page shows raw results without fetching twice;
  Marketaux skips are reported with a reason. `IngestionReport.inserted_ids` added.
- `routes/debug.get_session_factory` dependency so tests can redirect the run to the
  test DB.
- Live-verified on uvicorn: page 200, "RBI repo rate" trace 159 lines, 28 Google
  articles shown, all reported as duplicates (already stored by the scheduler run).

### 2026-10-04 — Security 4.1: rule-based injection scan (`app/security/injection_filter.py`)
- `scan_text_rules(text) -> {"verdict": "SAFE"|"SUSPICIOUS", "matched_patterns": [rule
  names, sorted], "evidence": [{"pattern", "text"}]}`. **Never returns BLOCKED** (reserved
  for the LLM stage 4.2); SUSPICIOUS = escalate to the LLM classifier.
  (`evidence` is an extra key: what matched, for security_logs / the LLM prompt.)
- Normalisation before matching: Unicode NFKC (full-width letters), invisible chars
  removed, whitespace incl. newlines collapsed. Role-marker and break-out rules run on
  the raw text (line structure matters there).
- Rules (`RULES` list): ignore_previous_instructions, ignore_the_above,
  new_instructions (only at sentence start or "your new task is"), system_prompt_reference,
  role_reassignment ("you are now a/an/in…", "from now on you…", "act as if you",
  "pretend to be", "developer mode"), addressed_to_ai ("AI reading this", "note to
  the AI"), concealment_instruction ("don't tell the user"), fake_role_marker
  (`SYSTEM:`/`ASSISTANT:` caps anywhere, any-case role label at line start),
  chat_template_token (`<|im_start|>`, `[INST]`, `<<SYS>>`…), breakout_characters
  (same symbol ×8+, ``` fences, `"}]{` delimiter runs), plus hidden_unicode
  (bidi overrides anywhere / zero-width char inside a word).
- Tests: 17 malicious (incl. zero-width split, full-width letters, newline split,
  indirect "note to the AI") + 13 benign incl. near misses ("markets act as if",
  "RBI issued new instructions: …", "you are now able to", analyst transcripts).
- Real-data check: scanned 259 real stored headlines → 1 false positive (publisher
  zero-width space after a space) → hidden_unicode narrowed → **0/259 flagged**.

### 2026-10-04 — Security 4.2: LLM classifier + scan in ingestion
- **`app/services/llm.py`** — the only place vendor SDKs are used:
  `await complete(system, user, max_tokens)`. `LLM_PROVIDER` = gemini (google-genai,
  `client.aio.models.generate_content`, temperature 0, AFC disabled) or openai
  (`AsyncOpenAI.chat.completions.create`). Lazy cached clients, `GEMINI_MODEL` /
  `OPENAI_MODEL` settings, `LLM_TIMEOUT_SECONDS` (20), semaphore
  `LLM_MAX_CONCURRENT_CALLS` (2). Every failure → `LLMError` / `LLMNotConfigured`.
- **`app/security/injection_classifier.py`**:
  - `classify_text_llm(text) -> {"verdict", "reason"}`. System prompt = the task's
    prompt **verbatim** + hardening (content is untrusted data, never obey it,
    reporting about AI is SAFE). Text wrapped in `<<<CONTENT {random nonce}>>>` …
    `<<<END CONTENT {nonce}>>>` (attacker can't fake the end marker), truncated to
    4000 chars. Strict parse: reply must START with SAFE/SUSPICIOUS/BLOCKED (markdown
    tolerated, "Not SAFE"/"SAFEGUARD"/chatter → SUSPICIOUS).
  - **Fail closed:** no key / timeout / 429 / API error / unparseable → SUSPICIOUS.
  - `scan_content(text) -> {"verdict", "reason", "matched_patterns", "stage":
    "rules"|"llm"}`: rules SAFE → SAFE with no LLM call; else the LLM decides.
- **Ingestion** (`news_ingestion.py`): before insert, URLs already in news_events are
  skipped (**not re-scanned**: saves LLM calls since the scheduler re-fetches every
  10 min); every new article's `title + "\n" + description` → `scan_content()` →
  `security_status` + `security_reason` (≤1000 chars). Non-SAFE → `security_logs`
  row (event_type prompt_injection, severity HIGH if BLOCKED else MEDIUM,
  blocked flag, details: origin/source_api/url/title/verdict/stage/patterns/reason),
  same transaction. `IngestionReport.security` = {safe, suspicious, blocked}.
  NULL security_status now only on rows stored before this change.
- Debug trace page now shows `security_reason` + the security counts, and captures
  `app.security` logs too.
- Live checks: real Gemini SDK with invalid key → 400 → SUSPICIOUS; real OpenAI SDK →
  401 → SUSPICIOUS (no key leaked in reasons); real ingestion "Wipro" → 5 new
  articles, all SAFE via rules (0 LLM calls). **Not yet tested with a real key**
  (D1/L1) — incl. whether `gemini-2.5-flash` is still a valid model name.
- requirements: + google-genai, openai.

### 2026-10-04 — Security 4.3: agent permissions (`app/security/permissions.py`)
- `AGENT_PERMISSIONS`: the task's allow-list, **plus `technical_indicators`** for
  market_agent read/write (the market service caches RSI there). Stored as
  `MappingProxyType` + `frozenset` → immutable at runtime. Validated at import
  (unknown table/operation → ValueError).
- `check_permission(agent, "read"|"write", table) -> bool`: default deny (unknown
  agent/op/table → False).
- `@enforce_permission(agent, op, table)`: names validated at decoration time (typos
  fail at import); permission checked at call time BEFORE the function runs. Agent
  identity is fixed in code, never taken from LLM output. Works for async (await
  audit log, then raise) and sync functions (raise; audit written as a background
  task if a loop is running, else `asyncio.run`).
- On denial: `AgentPermissionError` (subclass of built-in `PermissionError`) +
  `security_logs` row in its **own transaction** (`audit_session_factory`):
  `event_type=agent_hijack` (existing enum value; the task's "agent_hijack_attempt"
  is stored as `details.kind`), severity HIGH for writes or reads of user-private
  tables (users, user_profiles, portfolio_holdings, transactions,
  broker_connections, recommendations), else MEDIUM; `blocked=true`; details:
  kind/agent/operation/table/function/allowed. Audit-write failure → still blocked.
- Tests (29): allow-list table, default deny, immutability, typo detection, the
  **hijacked news_agent → recommendations** scenario (raises, body never runs, 0
  recommendation rows, HIGH log), private read, DB-down audit, sync functions, and an
  exhaustive agent × op × table sweep. Demo on the migrated DB produced a valid
  `agent_hijack` row.
- Not yet applied to real agent code: agents don't exist yet (Phase 5). Every agent DB
  function must be decorated when written.

### 2026-10-04 — Phase 5.1: vector store (`app/services/vector_store.py`)
- **Local ChromaDB** `PersistentClient` at `CHROMA_PERSIST_DIR` (default
  `backend/chroma_data`, git-ignored), telemetry off, collection `financial_news`
  (`CHROMA_COLLECTION`), cosine distance, Chroma's built-in embedding function
  disabled (we always pass our own vectors). D3 answered by default: local, no account.
- **Embeddings:** `all-MiniLM-L6-v2` via sentence-transformers on CPU, 384-d,
  L2-normalised. Loaded **once per process** (`get_embedding_model()`, double-checked
  `threading.Lock`), lazily on first use. First load downloads ~90 MB (~45–60 s);
  later embeds ~0.07 s. Inference + Chroma calls run in `asyncio.to_thread`.
- `embed_and_store(news_event_id) -> EmbedResult` (embedded | skipped_not_safe |
  not_found). **SAFE check is inside the function** (defence in depth):
  SUSPICIOUS / BLOCKED / NULL are never embedded, not even sent to the model.
  `embed_many(ids) -> EmbedReport` does the same with one batched encode.
- Chroma id `news-<id>`, upsert (re-embed replaces). Document = title + "\n" +
  description. Metadata: `news_event_id, symbol` (first affected symbol or ""),
  `symbols` (full list, only if any), `source` (source_api), `source_domain`,
  `security_status` ("safe"), `seen_at` (unix seconds, for recency filters).
- Helpers for later phases: `search_similar(text, n, where)` (RAG + Phase 5.2
  near-duplicate detection), `remove_from_store(ids)`, `stored_ids(ids)`, `count()`.
- **Not wired into ingestion/scheduler yet** — deliberately: Phase 5.2's quarantine
  logic must sit between the injection scan and embedding.
- Live check (real model, migrated test DB): 264 rows → 5 SAFE embedded, 259 legacy
  NULL skipped; semantic search works ("software services company employees" → IT
  hiring article first). Legacy NULL rows exist only in Claude's test DB (stored
  before the scanner existed); a fresh DB won't have them.
- requirements: + chromadb, sentence-transformers (PyTorch ~ large install).
- Tests (11): fake hashing model + real Chroma in tmp dir; metadata, non-safe skip,
  upsert, batching, load-once under 8 concurrent threads, search + filter, remove,
  persistence across client restart.

### 2026-10-04 — Phase 5.2: RAG poisoning defence (`app/security/rag_poisoning.py`)
- `TRUSTED_DOMAINS` (frozenset, ~28): wires (reuters, bloomberg, apnews, ft, wsj, cnbc),
  Indian financial/general press (economictimes.indiatimes.com + economictimes.com,
  moneycontrol, livemint, business-standard, thehindubusinessline, financialexpress,
  cnbctv18, ndtvprofit, businesstoday, thehindu, indianexpress, timesofindia,
  hindustantimes, ndtv, zeebiz), official (nseindia, bseindia, sebi.gov.in,
  rbi.org.in, pib.gov.in, sec.gov). User asked to be asked before extending → pending.md D9.
- `check_source_trust(domain)`: normalises (lowercase, strips scheme/www/port/path,
  accepts URLs); trusted = exact match or subdomain (`m.economictimes…`);
  look-alikes (`reuters.com.evil.io`, `fakereuters.com`, `reuters.co`) untrusted.
- `check_duplicate_cluster(new, existing, threshold=0.95, min_matches=2)`: pure cosine.
- `scan_before_embedding(id) -> "proceed"|"quarantine"` (read-only decision;
  `evaluate_before_embedding()` returns the full `PreEmbedVerdict` with reason and the
  embedding, reused by the vector store):
  1. stored Phase-4 verdict must be SAFE (NULL legacy rows are scanned now with
     `scan_content()` and saved) → else quarantine (kind `injection`);
  2. trusted domain → proceed;
  3. untrusted → candidates = last **72 h**, same symbol via PG array overlap `&&` (no
     symbol → all recent), both news_events and news_quarantine, max 200/table,
     **other domains only**. If near-identical (≥0.95) to a **trusted** article →
     proceed (syndication). If near-identical to articles on **≥2 other untrusted
     sites** → quarantine (kind `duplicate_cluster`).
  The last two refinements came from real data: 11/35k real headline pairs were
  ≥0.95 (Bloomberg→Yahoo Finance, ET→m.economictimes.com, PTI/AFP wire copies, a
  site under two URLs). Refined rule: 0 false positives on 264 real articles.
- **news_quarantine** table (migration 0006): shared `NewsColumns` mixin (exactly
  news_events' columns) + `original_news_event_id`, `quarantine_reason`,
  `quarantined_at`. Quarantine = **move** (insert + delete from news_events). No
  agent permission includes it.
- **Pipeline:** `vector_store.embed_many()` / `embed_and_store()` now run the check
  first: proceed → embed (reusing the check's embedding); quarantine → move.
  On a cluster: the other untrusted members still in news_events are also moved and
  removed from Chroma (the first copy of a campaign got embedded before the cluster
  existed), plus a `security_logs` row (event_type `rag_poison`, HIGH, details incl.
  cluster ids + max similarity). `EmbedResult`: embedded | quarantined | not_found.
  Scheduler news job now calls `embed_many(report.inserted_ids)` after ingestion
  (details: embedded / quarantined; embedding failure → run "partial", ingestion kept).
- Ingestion: `_existing_urls` also checks news_quarantine (quarantined URLs aren't
  re-ingested). Google rows are tagged `affected_symbols=[ticker]` when found via a
  ticker (needed for per-symbol clusters); GDELT batched rows stay [].
- Live (real MiniLM): 3 lightly edited copies of a fake XYZ story on cheap sites
  (pairwise 0.97/0.97/0.947) → all quarantined; 2 independent real-style reports of
  the same event (0.64/0.51) → embedded. Note 0.947: heavier paraphrasing can fall
  under 0.95; threshold is a tunable trade-off (`SIMILARITY_THRESHOLD`).
- Gotcha: PowerShell 5.1 `Get-Content | Set-Content` re-encodes UTF-8 files (mojibake);
  edit files with the editor tools instead.

### 2026-10-04 — Phase 5.3: RAG retrieval (`app/services/rag_retrieval.py`)
- `retrieve_relevant_news(query, symbol=None, top_k=5, *, max_age_days=None,
  min_similarity=None, symbol_fallback=True, session_factory) -> list[dict]`.
  Query embedded with the same MiniLM model → Chroma `financial_news` →
  rows joined from PostgreSQL by `news_event_id`, relevance order.
- Result dict: news_event_id, title, description, url, source_api, source_name,
  source_domain, **source_trust**, seen_at (ISO), sentiment, affected_symbols,
  affected_sector, **similarity** (1 − cosine distance), **symbol_match**.
- Symbol filter = Chroma `{"symbols": {"$contains": SYM}}` (verified on Chroma 1.5: finds
  articles where the stock isn't the first symbol; plain `symbol ==` missed them).
  `symbol` normalised like holdings ("infy" → "INFY.NS"). `max_age_days` → `seen_at $gte`.
- **Symbol fallback (default on):** most articles have no symbol tag (GDELT batches,
  macro keywords, pre-tagging rows), so if tagged results < top_k the rest are filled
  by plain semantic search; tagged matches come first (`symbol_match` True/False).
  Without it, live "What is happening with Infosys?" + INFY.NS returned nothing.
- **Safety:** only rows still in news_events with status `safe` are returned; Chroma
  entries whose row is gone/re-flagged are skipped AND removed from Chroma
  (self-healing). `EXTRA_CANDIDATES=5` over-fetch keeps top_k filled.
- **De-dup:** same story (normalised title) returned once, preferring the trusted copy.
- No permission check inside (shared service); agents must call it from their own
  `@enforce_permission(agent, "read", "news_events")` functions.
- **Perf fix to Phase 5.2:** `vector_store.embed_texts_cached()` (thread-safe LRU, 5,000
  texts) used by the RAG-poisoning candidate comparison: pipeline over 268 real
  articles **306 s → 38 s**. Queries take ~15–80 ms.
- Live (real model, 268 real articles): relevant top-3 for oil prices, RBI rate hike,
  IT hiring, and Infosys (via fallback).
- Tests (17): ranking, symbol `$contains`, fallback order, recency, min_similarity,
  stale/re-flagged cleanup, dedup (trusted kept), clamping, empty cases, cache.

### 2026-10-04 — Phase 6.1: News Agent (`app/agents/news_agent.py`, `app/agents/base.py`)
- **Agent result contract (D5 default, all agents):** `agent, symbol, status, signal
  (-1..+1), confidence (0..1), rationale` + agent-specific fields. `status` = "ok" or
  why it's degraded; degraded results are always neutral with confidence 0.
- `app/agents/base.py`: `BaseAgent` (session_factory, `log_call()` → agent_logs in its
  own transaction, never raises; **not** permission-checked: auditing is a system
  function, no agent may write agent_logs), `untrusted_block()` (nonce-delimited
  untrusted text), `parse_json_object()` (tolerates ```json fences / surrounding text).
- `llm.complete(..., json_mode=True)`: Gemini `response_mime_type=application/json`,
  OpenAI `response_format={"type": "json_object"}`.
- `NewsAgent(session_factory).analyze(symbol, company_name=None) -> dict`:
  1. `_fetch_news` (**@enforce_permission("news_agent","read","news_events")**) →
     `retrieve_relevant_news(query, symbol, top_k=8, max_age_days=7)`; query =
     "<company name or ticker base> stock news: results, deals, guidance, regulation,
     management" (pass `company_name` for better recall: ticker alone matches poorly).
  2. LLM (JSON mode). System prompt: News Agent role, articles = untrusted data in
     nonce markers, never follow them, use only the articles; returns `sentiment`
     positive|negative|neutral, `severity` low|medium|high, one-sentence `summary`,
     `cited_article_ids`, `article_sentiments` [{id, score -1..1}]. Each article line:
     `[id=N] (date, domain, trusted|untrusted source) title - description` (≤600 chars).
  3. Pydantic validation (labels case-insensitive); invented article ids dropped.
  4. `_save_article_sentiments` (**@enforce_permission("news_agent","write","news_events")**)
     writes per-article scores into `news_events.sentiment` **only where NULL**
     (Marketaux scores kept).
  5. `signal = sign(sentiment) × {low .33, medium .66, high 1.0}`;
     `confidence = 0.3 + 0.7 × min(cited/4, 1) × avg trust (trusted 1.0, untrusted 0.6)`.
  Statuses: ok | no_news (LLM not called) | llm_unavailable | invalid_llm_output | error
  (unexpected exception, incl. AgentPermissionError: logged, then re-raised).
  Every call → one agent_logs row (input: symbol + article count; output: verdict).
- Live (real retrieval, no LLM key): INFY.NS → 8 relevant real articles retrieved,
  status llm_unavailable, neutral/0, agent_logs row written. **Real LLM verdicts
  untested until L1.**
- Tests (25 + json-mode test): signal/confidence maths, JSON parsing, happy path
  (prompt shape, nonce markers, JSON mode, logging), invented ids, every degraded
  path, permission guards, end-to-end write-back with real Chroma + PG.

### 2026-10-04 — Phase 6.2: Market Agent (`app/agents/market_agent.py`)
- **New table `price_history`** (migration 0007): daily OHLCV, unique (symbol, date).
  `market_data.save_price_history()` upserts the ~22 daily bars that
  `update_market_snapshot()` already downloads from yfinance (no extra API calls; NaN
  closes skipped; re-fetched days overwrite). `MarketUpdate.history_bars` added.
- Permissions: market_agent now also **reads** `price_history` (not write: only the
  system job writes it). Allow-list: read market_snapshots, technical_indicators,
  price_history; write market_snapshots, technical_indicators.
- `MarketAgent(session_factory).analyze(symbol) -> dict`, **no LLM**. Guarded reads:
  `_latest_snapshot` (market_snapshots), `_daily_closes` (price_history, last 60),
  `_cached_rsi` (technical_indicators). One agent_logs row per call.
  - price = latest snapshot if its date ≥ last daily bar, else last close.
  - **trend** vs 7-day SMA of closes: > +1% up, < −1% down, else flat.
  - **RSI-14** (Wilder; SMA seed then (prev×13+cur)/14): Alpha Vantage cached value if
    as_of ≤ 4 days old, else computed locally (needs 15 closes). ≥70 overbought,
    ≤30 oversold. Verified vs an independent pandas-ewm implementation; StockCharts'
    textbook example gives 70.46 exact (their table shows 70.53 from rounding).
  - `signal = 0.7 × clamp(%vs MA7 / 5) + 0.3 × (−1 overbought | +1 oversold | 0)`.
  - `confidence = 0.3 + 0.2 (≥15 days history) + 0.2 (RSI available) + 0.1 (data ≤ 4 days
    old)`, max **0.8** (technicals alone never give full confidence).
  - Output: trend, rsi_signal, summary (+ signal, confidence, rationale, price,
    price_source, price_as_of, change_pct, ma7, pct_vs_ma7, rsi, rsi_source,
    history_days). Statuses: ok | insufficient_history (<7 closes → neutral, conf 0) |
    no_data | error.
- Live (real yfinance, 4 stocks): e.g. RELIANCE.NS 3.0% below MA7 → down, RSI 23 oversold,
  signal −0.12; INFY.NS up, RSI 38; TCS/HDFCBANK flat.
- Tests (43): RSI textbook + 10 cross-checks vs reference, edge cases, MA, classifiers,
  signal/confidence, agent end-to-end on PG (up/down/flat, AV fresh vs stale, stale
  snapshot, insufficient history, no data, symbol isolation), history upsert, permissions.

### 2026-10-04 — Phase 6.3: Portfolio Agent (`app/agents/portfolio_agent.py`)
- **Permissions changed:** portfolio_agent now reads `portfolio_holdings, transactions,
  market_snapshots, price_history` (prices needed for P/L; public data), writes nothing.
  Table-level permissions can't express "own rows only", so **every query filters by
  `user_id`** (tested: another user's huge position never leaks in).
- `PortfolioAgent(session_factory).analyze(user_id, symbol) -> dict`, **no LLM**:
  - Manual + Zerodha rows for the symbol are combined (qty sum, weighted avg cost).
  - Current price = newer of latest snapshot / latest daily close.
  - Unrealised P/L (₹, %); **realised P/L via FIFO** over the user's trades in the
    symbol; holding period from the oldest open FIFO lot → `tax_term`
    long_term (> 365 days) / short_term (Indian capital-gains rule).
  - Total portfolio value: stocks at market price, FD/gold/property/MF (and stocks
    with no price) at cost → counted in `valued_at_cost_assets`.
  - `position_weight_pct` → `concentration_risk`: none | low < 10% | medium 10–25% |
    high > 25%. `signal` ("should the user add more?"): +0.1 not held/low, −0.2 medium,
    −0.6 high, −0.9 > 40%. `confidence = 0.4 + 0.6 × share of stock holdings priced`,
    −0.3 if this held stock has no price, −0.1 if its price is > 4 days old.
  - `notes` (also appended to the summary): trades show open shares not in holdings
    (tradebook uploads don't update holdings — D8), holdings ≠ trades quantity,
    history starts mid-way (partial realised P/L).
  - Statuses: ok | not_held | no_portfolio | error. One agent_logs row per call.
- Live (migrated test DB, real prices): smoke user's INFY 12.5 @ ₹1,480.25 vs ₹1,035 →
  −₹5,565.62 (−30.1%), 100% weight, high risk, signal −0.9; HDFCBANK (bought only via
  tradebook upload) → not_held + note about 7 open shares missing from holdings.
- Tests (24): FIFO (realised, open lots, date order, incomplete), risk/signal table,
  combined rows, user isolation, tax term, not held, no portfolio, missing/stale/newer
  price, notes, logging, permissions.

### 2026-10-04 — Phase 6.4: User Profiling Agent (`app/agents/user_profiling_agent.py`)
- **Migration 0008 (user_profiles):** + `stated_risk_appetite`, `stated_investment_horizon`
  (CHECKs, `op.f` names), `profile_basis` JSONB, `behavior_metrics` JSONB,
  `classified_at`. Existing risk/horizon copied into stated_* on upgrade.
  **Two layers:** `stated_*` = what the user chose (agent never writes them; enforced
  with a ValueError, not assert); `risk_appetite`/`investment_horizon` = EFFECTIVE profile
  other agents use. Without this split the agent would read its own output back as the
  user's choice next run (tested: re-running doesn't drift).
- Permissions: user_profiling_agent now also **reads** `user_profiles` (stated prefs).
- `UserProfilingAgent(session_factory).analyze(user_id) -> dict`, **no LLM**, every
  query filtered by user_id:
  - Metrics: `avg_holding_days` (value-weighted FIFO per symbol: sold lots buy→sell, open
    lots buy→today), `trades_per_month` (≥1-month window), `quick_flip_pct` (% of sold
    qty held < 30 days), `equity_share_pct` & `max_position_pct` (holdings at cost; this
    agent has no price access), transactions_count, distinct_stocks.
  - Horizon: > 365 days long_term, ≥ 90 medium_term, else short_term.
  - Risk points: trades/month > 8 +2, ≥ 3 +1, < 1 −1; quick flips > 30% +1; equity
    > 80% +1, < 40% −1; one stock > 40% +1 → ≥ 2 aggressive, ≤ −1 conservative, else
    moderate. `risk_reasons` lists every rule that fired (plain English).
  - Behaviour used only with ≥ 5 trades (`MIN_TRADES`), else status
    `insufficient_history`.
  - **Combine (D10):** risk = more conservative of stated vs behaviour ("blended");
    horizon = stated wins; nothing → moderate / medium_term ("default").
  - Upserts user_profiles (effective values, basis, metrics, classified_at; other fields
    like goals kept). Returns risk_appetite, investment_horizon, basis, behaviour,
    stated, risk_reasons, summary; `signal` always 0 (not a buy/sell view);
    confidence = min(trades/20, 1), 0.5 if only stated, 0 if defaults. Logged.
- Not yet: an API/form for users to SET their stated preferences (Phase 8 app layer).
- Live (migrated DB): smoke user with 1 trade + stated aggressive/long-term →
  insufficient_history, effective = stated, all new columns stored correctly.
- Tests (33): metrics maths, horizon/risk tables, combine matrix, active trader,
  buy-and-hold, blended conflict, few trades, new user defaults, no drift, user
  isolation, logging, stated-write guard, permissions.

### 2026-10-04 — Phase 6.5: Fundamental & Economic Agent
- Phase 3.2 never had an Alpha Vantage OVERVIEW call (only RSI). Probe: **yfinance
  `Ticker.info` returns full NSE fundamentals with no key** (P/E, sector, ROE, D/E,
  growth, margins, 52-week range); AV OVERVIEW format checked with the demo key (IBM),
  Indian coverage unverified.
- **New table `company_fundamentals`** (migration 0009): one row per symbol, cached
  7 days. **`app/services/fundamentals.py`** (system service): `refresh_if_stale(symbol)`
  → yfinance first, AV OVERVIEW fallback (key + shared cooldown), stale row kept if all
  sources fail. Units normalised: debt_to_equity ratio (yfinance gives %),
  dividend_yield_pct % (AV gives a fraction), roe/margins/growth as fractions.
- `market_data` refactor: `alphavantage_available()`, `start_alphavantage_cooldown()`,
  `alphavantage_query()` shared by RSI + OVERVIEW (one cooldown for both).
- Scheduler market job also calls `refresh_if_stale` per held stock
  (`details.with_fundamentals`); fetches at most weekly.
- Permissions: fundamental_economic_agent reads news_events, market_snapshots,
  **company_fundamentals**; writes nothing (the cache is refreshed by the system service,
  called from the agent's guarded read method when missing/stale).
- `FundamentalEconomicAgent(session_factory).analyze(symbol) -> dict`, no LLM:
  - Macro news = SAFE news_events from the last 7 days matching macro keywords (PG `~*`
    pre-filter, Python word-boundary themes): interest_rates, inflation, oil_energy,
    fiscal_policy, growth, **currency**, **geopolitics** (split from one "global_risk"
    theme after the live run showed IT stocks getting war headlines).
    `SECTOR_THEMES` maps yfinance sectors to relevant themes (banks → rates/inflation/
    growth; Technology → currency/growth; Energy → oil/geopolitics/fiscal; …).
    Headlines: relevant themes first, then newest (8 shown).
  - Fundamental points: loss-making −0.5 | P/E < 15 +0.4, 30–50 −0.2, > 50 −0.5 |
    ROE ≥ 15% +0.3, < 8% −0.2 | D/E > 2 −0.3 (not for Financial Services) | revenue
    growth > 10% +0.2, < 0 −0.2. `valuation`: cheap / fair / expensive / loss_making / unknown.
  - `signal = 0.7 × clamp(points) + 0.3 × avg sentiment of relevant macro articles (if ≥ 3
    scored, else 0)`; `confidence = 0.2 + 0.4 fundamentals + 0.2 (≥ 3 relevant articles)
    + 0.2 (≥ 3 scored)`. Statuses: ok | no_data | error. Logged.
  - Output: company {name, sector, industry, pe_ratio, forward_pe, price_to_book, eps,
    roe_pct, debt_to_equity, dividend_yield_pct, revenue_growth_pct, profit_margin_pct,
    market_cap_crore, week52_high/low, source, fetched_at}, valuation,
    fundamental_reasons, macro {article_count, themes, relevant_themes,
    relevant_article_count, avg_sentiment, relevant_avg_sentiment, headlines}, summary.
- Live (real yfinance + 268 real articles): HDFCBANK fair (P/E 15.8, 17% growth), rate
  headlines first; INFY cheap (P/E 13.3, ROE 32%) → signal 0.49; RELIANCE fair, oil/war
  headlines. Macro sentiment is None until news sentiment exists (needs the LLM key).
  Known coarseness: any "war" headline counts as geopolitics (e.g. a WWII shipwreck story).
- Tests (40 incl. scheduler): theme matching (no partial words), points table, banks'
  D/E exemption, normalisation, AV parsing, cache/refresh/stale/fallback/nothing,
  agent end-to-end (SAFE/recent/macro filtering, sector relevance, sentiment avg,
  ordering), logging, permissions.

### Testing setup (as of 2026-10-04)
- `pytest` → 440 tests.
- Note: Claude's Bash tool lost its Unix utilities (head/grep/sed) on 2026-10-04;
  PowerShell is used for commands since then. Postgres-only tests (ON CONFLICT, ARRAY, JSONB) need
  `TEST_DATABASE_URL` pointing at an **empty, disposable** DB (tables dropped after);
  otherwise skipped.
- Claude verifies migrations with a throwaway PG 18 cluster (scratchpad, port 55432, trust
  auth) created with the locally installed PostgreSQL binaries: `alembic upgrade head`,
  `alembic check` ("No new upgrade operations detected"), downgrade/upgrade round trip.
  All 4 migrations verified this way.

