# Authentication — How It Works & How to Test It

## Token strategy

| | Access token | Refresh token |
|---|---|---|
| Format | JWT (HS256, signed with `JWT_SECRET_KEY`) | Random 256-bit string (opaque) |
| Lifetime | 30 min (`ACCESS_TOKEN_EXPIRE_MINUTES`) | 7 days (`REFRESH_TOKEN_EXPIRE_DAYS`) |
| Where it lives | JSON response body → frontend memory | `httpOnly` cookie, path `/auth` |
| Sent as | `Authorization: Bearer <token>` | Cookie, automatically, only to `/auth/*` |
| Stored in DB? | No (stateless) | Yes, as a SHA-256 hash in `refresh_tokens` |

**Why this design**
- Short access tokens limit the damage if one leaks. Long access tokens (e.g. 24 h) can't be revoked.
- The refresh token is in an httpOnly cookie, so JavaScript (and therefore XSS) can't read it.
- **Rotation:** each refresh token works once. `/auth/refresh` revokes it and issues a new one.
- **Reuse detection:** if a revoked refresh token is presented again, it was probably stolen,
  so every session for that user is revoked.
- **Logout** revokes the refresh token server-side.

**Frontend flow (Axios):** keep the access token in memory. When a call returns 401, call
`POST /auth/refresh` with `withCredentials: true`, then retry the original call.

## Endpoints

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/auth/signup` | JSON `{"email", "password"}` (8–72 chars) | 201 + access token, sets cookie |
| POST | `/auth/login` | **form** `username=<email>&password=...` | 200 + access token, sets cookie |
| POST | `/auth/refresh` | refresh cookie | 200 + new access token, rotates cookie |
| POST | `/auth/logout` | refresh cookie | 204, clears cookie |
| GET | `/auth/me` | `Authorization: Bearer ...` | current user (protected test route) |

Protecting any new route:
```python
from app.core.dependencies import get_current_user

@router.get("/something")
async def something(user: User = Depends(get_current_user)): ...
```

## Automated tests (no database needed)

```bash
cd backend
pytest -v
```
Uses an in-memory SQLite DB. Covers signup, login, `/auth/me`, wrong password,
expired/forged tokens, refresh rotation, reuse detection, and logout.

## Manual test against the running server

Prerequisite: PostgreSQL set up and `alembic upgrade head` done (see pending.md P1/P2).
Start the server: `uvicorn app.main:app --reload`.

### Git Bash (curl)
```bash
API=http://127.0.0.1:8000

# 1. Sign up (saves the refresh cookie to cookies.txt)
curl -s -c cookies.txt -X POST $API/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@example.com","password":"demo-pass-123"}'

# 2. Log in (form-encoded; the email goes in "username")
TOKEN=$(curl -s -c cookies.txt -X POST $API/auth/login \
  -d "username=demo@example.com&password=demo-pass-123" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 3. Call the protected endpoint
curl -s $API/auth/me -H "Authorization: Bearer $TOKEN"

# 4. Without a token -> 401
curl -s -w "\n%{http_code}\n" $API/auth/me

# 5. Refresh (uses + updates the cookie)
curl -s -b cookies.txt -c cookies.txt -X POST $API/auth/refresh

# 6. Logout
curl -s -b cookies.txt -c cookies.txt -X POST $API/auth/logout -w "%{http_code}\n"
```

### PowerShell
```powershell
$API = "http://127.0.0.1:8000"
$s = New-Object Microsoft.PowerShell.Commands.WebRequestSession   # keeps the cookie

# 1. Sign up
Invoke-RestMethod "$API/auth/signup" -Method Post -WebSession $s `
  -ContentType "application/json" -Body '{"email":"demo@example.com","password":"demo-pass-123"}'

# 2. Log in
$login = Invoke-RestMethod "$API/auth/login" -Method Post -WebSession $s `
  -Body @{ username = "demo@example.com"; password = "demo-pass-123" }

# 3. Protected endpoint
Invoke-RestMethod "$API/auth/me" -Headers @{ Authorization = "Bearer $($login.access_token)" }

# 4. Refresh
Invoke-RestMethod "$API/auth/refresh" -Method Post -WebSession $s

# 5. Logout
Invoke-RestMethod "$API/auth/logout" -Method Post -WebSession $s
```

### Swagger UI
Open http://127.0.0.1:8000/docs, click **Authorize**, enter your email as *username* plus your
password, then try `GET /auth/me`.
