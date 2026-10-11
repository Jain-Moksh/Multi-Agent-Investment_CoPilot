"""
Authentication endpoints.

Token strategy:
  - Access token: JWT, 30 min, returned in the JSON body. The frontend keeps it
    in memory and sends it as "Authorization: Bearer <token>".
  - Refresh token: random string, 7 days, set as an httpOnly cookie (JavaScript
    can't read it, so XSS can't steal it). The cookie is only sent to /auth/*.
    POST /auth/refresh swaps it for a new access token and a new refresh token
    (rotation).
"""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rate_limit
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import create_access_token
from app.models import User
from app.schemas.auth import SignupRequest, TokenResponse, UserOut
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/auth"


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=not settings.is_development,  # HTTPS-only outside local dev
        samesite="lax",
    )


def _token_response(user_id: int) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


async def _start_session(db: AsyncSession, response: Response, user_id: int) -> TokenResponse:
    """Issue both tokens for a freshly authenticated user and commit."""
    _set_refresh_cookie(response, await auth_service.issue_refresh_token(db, user_id))
    await db.commit()
    return _token_response(user_id)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _too_many(seconds: int, what: str) -> HTTPException:
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Too many {what}; try again in {seconds} s.",
                         headers={"Retry-After": str(seconds)})


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Create an account and log the user in immediately. Limited to 10 accounts per IP per hour."""
    ip_key = _client_ip(request)
    if wait := rate_limit.SIGNUPS_PER_IP.retry_after(ip_key):
        raise _too_many(wait, "sign-ups from this address")
    try:
        user = await auth_service.create_user(db, body.email, body.password)
    except auth_service.EmailAlreadyRegistered:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered") from None
    rate_limit.SIGNUPS_PER_IP.hit(ip_key)
    return await _start_session(db, response, user.id)


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    OAuth2 password flow: send form fields `username` (= your email) and `password`
    as application/x-www-form-urlencoded. This is what Swagger's Authorize button uses.
    After 5 failed attempts for one email (or 20 from one IP) within 15 minutes, further
    attempts get 429 until the window passes; a successful login clears the email's count.
    """
    email_key, ip_key = form.username.strip().lower(), _client_ip(request)
    wait = max(rate_limit.LOGIN_FAILURES_PER_EMAIL.retry_after(email_key),
               rate_limit.LOGIN_FAILURES_PER_IP.retry_after(ip_key))
    if wait:
        raise _too_many(wait, "failed login attempts")
    user = await auth_service.authenticate_user(db, form.username, form.password)
    if user is None:
        rate_limit.LOGIN_FAILURES_PER_EMAIL.hit(email_key)
        rate_limit.LOGIN_FAILURES_PER_IP.hit(ip_key)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    rate_limit.LOGIN_FAILURES_PER_EMAIL.reset(email_key)
    return await _start_session(db, response, user.id)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Exchange the refresh-token cookie for a new access token (and a rotated cookie)."""
    if refresh_token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing refresh token")
    try:
        user, new_refresh_token = await auth_service.rotate_refresh_token(db, refresh_token)
    except auth_service.InvalidRefreshToken:
        response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token") from None

    _set_refresh_cookie(response, new_refresh_token)
    await db.commit()
    return _token_response(user.id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Revoke the refresh token. The (short-lived) access token simply expires."""
    if refresh_token:
        await auth_service.revoke_refresh_token(db, refresh_token)
        await db.commit()
    response.delete_cookie(REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    """Protected test endpoint: returns the logged-in user."""
    return current_user
