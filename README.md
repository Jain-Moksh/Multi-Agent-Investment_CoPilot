# Investment Copilot

A multi-agent, LLM-driven personal investment **decision-support** assistant.
It analyses financial news, market data, company fundamentals and the user's own
portfolio to produce Buy / Hold / Sell recommendations with a confidence score and
a plain-English explanation.

> ⚠️ Educational project — not investment advice.

See [context.md](context.md) for the full architecture and a log of what has been built.

## Repository layout

```
Investment_CoPilot/
├── backend/            FastAPI app (agents, security layer, APIs)
│   ├── app/
│   │   ├── main.py     FastAPI entry point
│   │   ├── core/       config, DB session, auth helpers
│   │   ├── models/     ORM models & schemas
│   │   ├── routes/     API routers
│   │   ├── services/   data-source clients, LLM, vector store
│   │   ├── agents/     specialist agents + recommendation layer
│   │   └── security/   injection scanner, permissions, RAG poisoning
│   ├── alembic/        database migrations (see alembic/README)
│   ├── requirements.txt
│   └── .env.example
└── frontend/           React + Tailwind (added later)
```

## Backend setup

Requires **Python 3.11+** (developed on 3.12).

```bash
cd backend

# 1. Create and activate a virtual environment
python -m venv venv
# Windows (PowerShell):
venv\Scripts\Activate.ps1
# macOS / Linux:
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your local env file and fill in the keys
cp .env.example .env        # Windows: copy .env.example .env

# 4. Create the database (once) and apply migrations
#    (create an empty "investment_copilot" DB in PostgreSQL first, e.g. via pgAdmin)
alembic upgrade head

# 5. Run the dev server
uvicorn app.main:app --reload
```

Run the tests (no database needed):
```bash
pytest -v
```

Then open:
- http://127.0.0.1:8000/health — health check
- http://127.0.0.1:8000/docs — interactive API docs (Swagger UI)

Docs: [docs/auth.md](docs/auth.md) — auth design + curl examples.
