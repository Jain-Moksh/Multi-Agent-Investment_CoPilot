# Pending — what is left

How to use: change `[ ]` to `[x]` when a step is done.
**Required steps done: 3 of 3 — the backend is fully set up and running on Supabase.**
(Nothing is required from you right now. Next work is Claude's: the full backend check, then the frontend.)

---

## Next

- [x] Backend audit done (findings summary in `context.md`)
- [x] The 6 audit fixes done (AI fallback per model, attack filter, chat refusal when the safety check is down, News Agent confidence, unknown tickers + prices for any stock, login limits + trusted news list) — 605 tests pass
- [ ] Run through `guide.md` once yourself (how to start, demo steps, troubleshooting)
- [x] Backend endpoints for the frontend added (news, portfolio summary, profile, security, agent logs, system status) — 636 tests pass
- [ ] Restart the backend server (if it is running) so the new endpoints are loaded
- [x] Dashboard page built and checked in a browser
- [ ] Open the Dashboard yourself with your own account (commands in Claude's reply)
- [x] AI Insights page built and checked in a browser (held + not-held stock, history re-open)
- [ ] Restart the backend so the new `details` field and `GET /recommendations/{id}` are loaded
- [x] Opportunities, Notifications and System Check pages built and checked in a browser
- [ ] Decide if/when to build the backend Opportunity Scanner and Notifications (the pages already handle "not built")
- [x] Frontend final pass done (session expiry message, phone layout fixes, README, clean build, full smoke test)
- [ ] Run the frontend once yourself: `npm install` then `npm run dev` in `frontend/`, open http://localhost:5173
- [ ] Optional: see the "session expired" message yourself. Log in, open DevTools → Application → Cookies → `http://localhost:8000`, delete `refresh_token`, wait 30 minutes, then click any page
- [ ] Connect a real Zerodha account once (could not be tested without your login)

Good to know: the free Gemini keys allow only about 20 AI requests per day per model per key (the app now uses the other models automatically when one runs out); adding credit to OpenAI (Optional list) would give a safe backup for demos.

---

## Optional — the backend works without these

- [ ] Commit and push to GitHub (phases 7–8, key fallback, Supabase lock migration are not saved yet; `.env` and the keys document are ignored, so no keys get pushed)
- [ ] Move `API_KEYSS.docx` out of the project folder (git ignores it, but it now holds every key AND the database password)
- [ ] Add credits to the OpenAI account (key is valid but has $0; only used if all Gemini keys and models fail)
- [ ] Zerodha: in the Kite developer console check Redirect URL = `http://127.0.0.1:8000/portfolio/zerodha/callback`, then try "Connect Zerodha" once
- [ ] Send Claude a real Zerodha Tradebook CSV (a few rows is enough) to test the import on a real file
- [ ] Review the default settings when you have time (they all work as they are): trusted news sites, agent weights, Buy/Sell thresholds, risk rule

---

## How to run the backend

- In the `backend` folder: `venv\Scripts\activate` then `uvicorn app.main:app --reload`
- Open http://127.0.0.1:8000/docs (try every API) or http://127.0.0.1:8000/debug/trace (watch news ingestion)

## Good to know

- Your Supabase tables are locked against Supabase's public web API; only the backend can read them
- If a key hits its limit, the next key is used by itself (Gemini keys → other Gemini models → OpenAI)
- The first server start takes about 1 extra minute (it loads a small embedding model)
- A full news run takes ~6 minutes, mostly because GDELT keeps answering "429"; Google News and Marketaux still work
- The server runs news (every 10 min) and price (every 30 min) jobs by itself; to pause them set `SCHEDULER_ENABLED=false` in `.env`
- Recommendations get better once you have 5+ trades (the User Profiling Agent needs them)

---
