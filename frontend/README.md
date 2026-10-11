# Investment Copilot - Frontend

React 18 + Vite single-page app for the Investment Copilot FastAPI backend.

Stack: React 18, Vite, React Router v6, Tailwind CSS 4, Recharts, Axios, lucide-react, react-markdown. State uses React Context and hooks.

Educational decision support, not financial advice.

## Requirements

- Node.js 20 or newer (tested with Node 22)
- The backend running on http://localhost:8000 (see `../guide.md`)

## Install

```
cd frontend
npm install
copy .env.example .env
```

On macOS or Linux, use `cp .env.example .env`.

## Run

1. Start the backend from `backend/`:

   ```
   venv\Scripts\activate
   uvicorn app.main:app --reload
   ```

2. Start the frontend from `frontend/`:

   ```
   npm run dev
   ```

3. Open http://localhost:5173. Use `localhost`, not `127.0.0.1`: the refresh cookie and CORS are set up for `localhost`.

| Script | What it does |
|---|---|
| `npm run dev` | Development server with hot reload on port 5173 |
| `npm run build` | Production build into `dist/` |
| `npm run preview` | Serves the `dist/` build locally |
| `npm run lint` | oxlint |

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000` | Base URL of the FastAPI backend |

The backend must allow the frontend origin in `CORS_ORIGINS`. The default already includes `http://localhost:5173`.

## How auth works

- Login and signup return an access token, which is kept in memory only, never in localStorage.
- The refresh token is an httpOnly cookie. All requests use `withCredentials`.
- On page load the app calls `POST /auth/refresh` and then `GET /auth/me` to restore the session.
- On a 401 the client refreshes once and retries the request.
- If the refresh fails, the session has expired. The user is sent to `/login?expired=1&next=<page>`, sees "Your session expired, please log in again", and returns to that page after logging in.

## Folder structure

```
src/
  main.jsx, App.jsx    entry point and routes (pages are lazy-loaded)
  api/                 axios client (token, refresh, error messages) and one module per backend area
  context/             AuthContext: session restore, login, signup, logout
  hooks/               useApi: loading / error / reload for one request
  components/          shared UI: Layout (sidebar, header, footer disclaimer), Card, Button, Modal,
                       ErrorBanner, EmptyState, Spinner, DecisionBadge, ConfidenceBar, Toast, ...
    chat/              AI Assistant pieces
    portfolio/         holdings table, add/edit modal, statement import, Zerodha card
    profile/           preferences form, learned profile card
    security/          Security Center tabs
  pages/               one file per page, plus a folder per page for its parts
    dashboard/  insights/  system/
  utils/               formatters (INR in en-IN, percent, dates), profile and asset labels
```

## Pages and the backend endpoints they use

| Page | Route | Backend endpoints |
|---|---|---|
| Login / Signup | `/login`, `/signup` | `POST /auth/login`, `POST /auth/signup`, `POST /auth/refresh`, `GET /auth/me` |
| Dashboard | `/` | `GET /portfolio/summary`, `GET /recommendations`, `GET /news` (portfolio news first, latest news as a fallback) |
| Portfolio | `/portfolio` | `GET /portfolio/summary`, `POST /portfolio/holdings`, `PUT /portfolio/holdings/{id}`, `DELETE /portfolio/holdings/{id}`, `POST /portfolio/import-statement`, `GET /portfolio/zerodha/status`, `GET /portfolio/zerodha/connect`, `POST /portfolio/zerodha/sync`, `DELETE /portfolio/zerodha` |
| AI Insights | `/insights` | `POST /recommendations/{symbol}`, `GET /recommendations`, `GET /recommendations/{id}` |
| Market News | `/news` | `GET /news` (symbol, sector, portfolio_only, limit, offset) |
| AI Assistant | `/assistant` | `POST /chat/message`, `GET /chat/conversations`, `GET /chat/conversations/{id}` |
| Opportunities | `/opportunities` | `GET /opportunities` (not built in the backend; the page shows "not built yet") |
| Notifications | `/notifications` and the header bell | `GET /notifications`, `POST /notifications/{id}/read` (not built in the backend; the bell shows "not enabled yet") |
| Profile | `/profile` | `GET /profile`, `PUT /profile`, `GET /auth/me` |
| Security Center | `/security` | `GET /security/stats`, `GET /security/events`, `GET /security/quarantine`, `GET /security/permissions`, `POST /security/scan-text` |
| System Check | `/system` | `GET /health`, `GET /system/status`, `GET /auth/me`, `GET /security/stats`, `GET /security/permissions`, `GET /portfolio/summary`, `GET /portfolio/zerodha/status`, `GET /opportunities`, `GET /notifications`; on demand `POST /recommendations/{symbol}` and `POST /chat/message` |

## UI conventions

- Money is shown as `₹` in the en-IN format. Buy is green, Hold is amber and Sell is red. Confidence is shown as a percentage with a bar.
- Every page has loading, empty and error states. Errors show a banner with Retry.
- On a 429 the message uses the server's Retry-After seconds.
- A 404 on a feature the backend has not built shows "Not built yet".
- AI calls take 5 to 30 seconds. Their buttons are disabled and show a loading state until the reply arrives.
- The disclaimer is in the footer of every page and on every recommendation card.
- The sidebar collapses to an icon rail below 1024 px. All pages are checked at 1440, 820 and 390 px wide.
