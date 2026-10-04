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

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

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


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest, response: Response, db: AsyncSession = Depends(get_db)):
    """Create an account and log the user in immediately."""
    try:
        user = await auth_service.create_user(db, body.email, body.password)
    except auth_service.EmailAlreadyRegistered:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered") from None
    return await _start_session(db, response, user.id)


@router.post("/login", response_model=TokenResponse)
async def login(
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    OAuth2 password flow: send form fields `username` (= your email) and `password`
    as application/x-www-form-urlencoded. This is what Swagger's Authorize button uses.
    """
    user = await auth_service.authenticate_user(db, form.username, form.password)
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
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
