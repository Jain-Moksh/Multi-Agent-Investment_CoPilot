# Pending — what is left

How to use: change `[ ]` to `[x]` when a step is done.
**Required steps done: 3 of 3 — the backend is fully set up and running on Supabase.**
(Nothing is required from you right now. Next work is Claude's: the full backend check, then the frontend.)

---

## Next

- [x] Backend audit done: the full report is at the bottom of `test.md` (below the line "---- tell ur test output -----")
- [ ] Give `test.md` to the other Claude and tell me what it says
- [ ] Say "fix the audit findings" → I fix the top issues first (LLM fallback per model, chat SUSPICIOUS handling, News Agent confidence, symbol check) — about 6 items, list is at the end of `test.md`
- [ ] Say "start the frontend" → React app on top of this backend

Good to know from the audit: the free Gemini keys allow only about 20 requests per day per model per key, so the AI parts may stop mid-demo until the fix; adding credit to OpenAI (Optional list) would give a safe backup.

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
