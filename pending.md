# Pending — Actions for Moksh

Things **you** need to do (Claude can't do them: they need your passwords,
accounts, or decisions). When you finish one, tell Claude
"done: <task number>", and Claude will run the follow-up step listed under it.

Status: ⬜ to do · ✅ done

---

## 🧭 Suggested order when you sit down (about 1–2 hours in total)

1. **L5** — say "commit and push" first, so all the work so far is safe on GitHub
   and your teammates can see it.
2. **P1 + P2** — create the database and `backend/.env`, then tell Claude "done: P1, P2".
3. **Decisions D1–D10** — answer them in one message (short answers are fine,
   e.g. "D1 Gemini, D2 local, D3 local, D4 multi-user, D5 yes, …").
4. **L1** (LLM key) — the most important key: the security layer and all agents use it.
5. **L2, L3** (Marketaux, Alpha Vantage) — 5 minutes each, free sign-ups.
6. **L4, L6** (Zerodha app, Tradebook CSV) — only if you want live Zerodha in the demo.

After each step, tell Claude "done: <ids>"; every item below says what Claude
will check next.

---

## 🔴 Do now (blocks testing of finished work)

### P1 ⬜ Create the PostgreSQL database
Your PostgreSQL 18 service is running on **port 5433** (not the default 5432).

Option A: pgAdmin
1. Open pgAdmin → connect to "PostgreSQL 18" (enter your postgres password).
2. Right-click **Databases** → Create → Database… → name: `investment_copilot` → Save.

Option B: PowerShell (asks for your postgres password)
```powershell
& "C:\Program Files\PostgreSQL\18\bin\createdb.exe" -U postgres -p 5433 investment_copilot
```

### P2 ⬜ Create `backend/.env`
1. In `backend/`, copy `.env.example` → `.env`
   (PowerShell: `Copy-Item backend\.env.example backend\.env`).
2. Edit `DATABASE_URL`. Use your real postgres password and port **5433**:
   ```
   DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@localhost:5433/investment_copilot
   ```
   If the password has special characters (`@ : / # %`), URL-encode them
   (e.g. `@` → `%40`).
3. Generate a JWT secret and paste it into `JWT_SECRET_KEY=`:
   ```powershell
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
4. Leave the other keys empty for now.
5. Never commit `.env` (it is already git-ignored).

➡️ **After P1 + P2, tell Claude "done: P1, P2".** Claude will then:
- run `alembic upgrade head` (creates all 15 tables, migrations 0001 → 0009),
- run `alembic check` (confirms the migrations exactly match the models),
- start the server and confirm `GET /health` → **200** with `"database": "connected"`,
- run the live auth demo (signup → login → `/auth/me` → refresh → logout) from
  `docs/auth.md` against your real Postgres.

Optional: after that, try it yourself in the browser at http://127.0.0.1:8000/docs
(click **Authorize**, then use your email as the username).

---

## 🟡 Decisions needed (answer anytime, the sooner the better)

### D1 ⬜ LLM provider: Gemini or OpenAI?  ← now needed
The injection classifier (Phase 4.2) is built and works with either; it just
needs a key (see L1). Until then, any article the rules flag stays SUSPICIOUS
(safe default: agents never read it). Gemini has a free tier, which makes it
the cheaper option for a student project.

### D2 ⬜ Postgres: keep local, or move to hosted (Neon / Supabase)?
Local works for you alone. A free hosted DB lets all 3 teammates share the same
data. If hosted, Claude will give you a sign-up link.

### D3 ⬜ ChromaDB: local folder (proposed) or Chroma Cloud?
Built as a **local folder** (`backend/chroma_data`, no account needed). Just
confirm; switching to Chroma Cloud later would be a small change, and Claude would
send you the sign-up link.

### D4 ⬜ Multi-user (sign-up/login, each user sees own data) or single demo user?
The schema and JWT already support multi-user. Confirm this is wanted.

### D5 ⬜ Agent output format (proposed — now in use from the News Agent onwards)
Each agent returns `signal` (−1..+1), `confidence` (0..1), and `rationale` (text).
The Agreement module computes the decision deterministically, the LLM only
writes the explanation, and SHAP/LIME get numeric features. Agree?
(Changing it later means touching every agent, so the earlier you object, the cheaper.)

### D6 ⬜ Stocks to track
Proposed: NIFTY 50 + whatever the user holds (to stay within API free quotas).
Right now the scheduler tracks only stocks users hold. RSI and moving averages are
already computed locally from yfinance daily closes (Market Agent); Alpha Vantage's
RSI is used only when fresh, so the Alpha Vantage key (L3) is optional.

### D7 ⬜ Zerodha Kite
Kite sync is now built. Its token expires daily at 6 AM, so the frontend needs a
"Reconnect Zerodha" button. Suggest CSV upload as the primary path in the demo
(works without a live Zerodha login). OK?

### D8 ⬜ Should a Tradebook upload also update your holdings?  ← recommended: yes
Right now it only fills the `transactions` table (as specified). Claude can also
compute current holdings from those trades (net quantity + average buy price) and
save them as `source = tradebook_upload`. Want that?
Why it matters now: the Portfolio Agent judges P/L and concentration from
holdings, so shares bought via an uploaded tradebook are invisible to it (it adds
a note saying so, but the numbers ignore them).

### D10 ⬜ When the user's stated profile and their behaviour disagree
The User Profiling Agent keeps what the user SAID (profile form) separate from what
their trades SHOW. Current rules for the profile the other agents use:
- **Risk appetite:** the more conservative of the two (e.g. says "aggressive" but
  only buys and holds → "conservative"), so advice never takes more risk than the
  user agreed to or actually takes.
- **Horizon:** the stated one wins (it reflects their goals).
- Fewer than 5 trades → the stated profile is used as-is (or moderate / medium-term
  if they stated nothing).
OK, or would you prefer behaviour (or the stated value) to always win?

### D9 ⬜ Trusted news sources list (RAG poisoning defence)
`backend/app/security/rag_poisoning.py` → `TRUSTED_DOMAINS`. Articles from these
sites are never quarantined by the duplicate check; articles from other sites are
quarantined only if near-identical copies appear on 2+ other untrusted sites (and
no trusted site carries the story). Current list:
reuters.com, bloomberg.com, apnews.com, ft.com, wsj.com, cnbc.com,
economictimes.indiatimes.com, economictimes.com, moneycontrol.com, livemint.com,
business-standard.com, thehindubusinessline.com, financialexpress.com, cnbctv18.com,
ndtvprofit.com, businesstoday.in, thehindu.com, indianexpress.com,
timesofindia.indiatimes.com, hindustantimes.com, ndtv.com, zeebiz.com,
nseindia.com, bseindia.com, sebi.gov.in, rbi.org.in, pib.gov.in, sec.gov.
Add or remove any? Candidates seen in our real news data: ptinews.com (PTI, India's
main news agency; recommended), telegraphindia.com, deccanherald.com,
finance.yahoo.com (aggregator), dailyhunt.in (aggregator).
(Trust also shows up in search results given to the agents as `source_trust`.)

---

## 🔵 Good to know (no action unless you want to)

### K1 GDELT is rate-limiting your network
Almost every GDELT call from your connection gets HTTP 429, even after waiting 10+
minutes. The code handles it (retries, then continues with the other sources).
Keywords are now batched (one GDELT call per 10 keywords per run), but the
scheduler's first live run still got 429. Try from another network (e.g. college
Wi-Fi) to see whether it's your IP.

### K2 NSE website blocks automated quotes from your network
`nsepython` returned empty data. yfinance (the primary source) works fine, so this
only affects the fallback.

### K3 The scheduler starts with the server
Every `uvicorn` start begins polling news (every 10 min) and prices (every 30 min),
with the first run 60 s after startup. To pause it while you're coding, set
`SCHEDULER_ENABLED=false` in `backend/.env`. Watch it at
http://127.0.0.1:8000/health/scheduler (log in first) or in the server log lines
starting with `[news_ingestion]` / `[market_update]`.

### K5 First run downloads the embedding model (and installs are big)
`pip install -r requirements.txt` now includes PyTorch (via sentence-transformers),
a large download, so teammates should expect a slow first install. The first time
the app embeds news it also downloads the all-MiniLM-L6-v2 model (~90 MB, about
a minute); after that it's cached on the machine.

### K4 Debug trace page for news ingestion
With the server running, open http://127.0.0.1:8000/debug/trace, type a keyword
(e.g. `RBI repo rate` or a ticker like `INFY.NS`) and press Run. You get, as plain
text: the raw articles from each source, the rows saved to `news_events`, and any
errors. No login is needed, but it only works from your own machine and only
while `ENVIRONMENT=development`. Each run really calls the APIs (Marketaux quota)
and really saves rows.

---

## 🟢 Later (only when the matching phase starts; Claude will remind you)

### L1 ⬜ Gemini or OpenAI API key → `GEMINI_API_KEY` / `OPENAI_API_KEY`  ← now needed
- Gemini: https://aistudio.google.com/apikey (sign in → **Create API key**)
- OpenAI: https://platform.openai.com/api-keys
Put it in `backend/.env` and set `LLM_PROVIDER=gemini` (or `openai`).
➡️ Then say "done: L1". Claude will: confirm the model name still exists, run the
injection classifier on real attack examples and real news, and run the News Agent
on a few real stocks to check its sentiment/severity/summary make sense (until
then every agent that needs the LLM returns "llm_unavailable", neutral, confidence 0).

### L2 ⬜ Marketaux key (news) → `MARKETAUX_API_KEY`
https://www.marketaux.com/register (free tier ~100 requests/day)
➡️ Then say "done: L2". Claude will make ONE live call to confirm Marketaux accepts
NSE symbols like `INFY.NS` (the code assumes it does; currently unverified).

### L3 ⬜ Alpha Vantage key (indicators) → `ALPHAVANTAGE_API_KEY`
https://www.alphavantage.co/support/#api-key (free, 25 requests/day)
➡️ Then say "done: L3". Claude will make ONE live call each to confirm RSI and
company OVERVIEW work for Indian stocks via the `.BSE` suffix (e.g. `RELIANCE.BSE`);
currently unverified. Optional key: RSI is already computed locally and fundamentals
come from yfinance; Alpha Vantage is only a cross-check / fallback.

### L4 ⬜ Zerodha Kite Connect app → `ZERODHA_API_KEY`, `ZERODHA_API_SECRET`
1. https://developers.kite.trade → sign up → **Create new app** → type **Personal** (free).
2. **Redirect URL:** `http://127.0.0.1:8000/portfolio/zerodha/callback`
   (Postback URL: leave empty.)
3. Copy the **API key** and **API secret** into `backend/.env`.
➡️ Then say "done: L4". Claude will walk you through one real connect + sync and
check the holdings that come back.

### L6 ⬜ Send a real Zerodha Tradebook CSV (optional but recommended)
Console → Reports → Tradebook → choose a date range → Download **CSV**.
The importer follows Zerodha's documented column layout, but it hasn't been
tested on a real export yet. Put the file in the project folder (or delete rows
you'd rather not share; a few rows is enough) and tell Claude the file name.
Claude will run it through the importer and fix any format differences.

### L5 ⬜ Approve first Git commit + push to GitHub  ← recommended soon
Nothing has been committed yet, so all the work exists only on this laptop.
Say "commit and push" when you want the current work on
https://github.com/Jain-Moksh/Multi-Agent-Investment_CoPilot.
(`.env`, `venv/` and other secrets/large folders are already git-ignored.)

---

## ✅ Completed
(Claude moves items here once you confirm them.)
