"""
Portfolio endpoints: manual holdings, Tradebook CSV import, Zerodha Kite.

Everything requires a logged-in user (Bearer token), except the Zerodha
callback: that request comes from Zerodha's redirect in the browser, so the
user is identified by the signed `state` token instead.
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models import User
from app.schemas.portfolio import (
    HoldingCreate,
    HoldingOut,
    HoldingUpdate,
    ImportReport,
    PortfolioSummary,
    ZerodhaLoginUrl,
    ZerodhaStatus,
    ZerodhaSyncReport,
)
from app.services import portfolio_service, tradebook_import, zerodha

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

NOT_FOUND = HTTPException(status.HTTP_404_NOT_FOUND, "Holding not found")
MANAGED_BY_SYNC = HTTPException(
    status.HTTP_409_CONFLICT,
    "This holding is synced from Zerodha and is updated automatically. Disconnect Zerodha to remove it.",
)


# ======================================================================
# 1. Manual holdings
# ======================================================================

@router.get("/holdings", response_model=list[HoldingOut])
async def list_holdings(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """All holdings of the current user (manual and Zerodha-synced)."""
    return await portfolio_service.list_holdings(db, user.id)


@router.get("/summary", response_model=PortfolioSummary)
async def portfolio_summary(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """
    Every holding valued at its latest market price (stocks) or at cost (no price / other
    assets, flagged price_missing), with P/L, weights, totals, today's P/L and the
    allocation by asset type.
    """
    return await portfolio_service.portfolio_summary(db, user.id)


@router.post("/holdings", response_model=HoldingOut, status_code=status.HTTP_201_CREATED)
async def add_holding(
    body: HoldingCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Add a holding. Stock symbols without an exchange suffix default to NSE (".NS")."""
    try:
        return await portfolio_service.add_holding(db, user.id, body)
    except portfolio_service.HoldingAlreadyExists:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"You already have a manual holding for {body.symbol}; edit it instead."
        ) from None


@router.put("/holdings/{holding_id}", response_model=HoldingOut)
async def update_holding(
    holding_id: int,
    body: HoldingUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await portfolio_service.update_holding(db, user.id, holding_id, body)
    except portfolio_service.HoldingNotFound:
        raise NOT_FOUND from None
    except portfolio_service.HoldingManagedBySync:
        raise MANAGED_BY_SYNC from None


@router.delete("/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holding(
    holding_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    try:
        await portfolio_service.delete_holding(db, user.id, holding_id)
    except portfolio_service.HoldingNotFound:
        raise NOT_FOUND from None
    except portfolio_service.HoldingManagedBySync:
        raise MANAGED_BY_SYNC from None


# ======================================================================
# 2. Tradebook CSV import
# ======================================================================

@router.post("/import-statement", response_model=ImportReport)
async def import_statement(
    file: UploadFile = File(description="Zerodha Console Tradebook CSV"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Import a Zerodha Tradebook CSV into your transactions.
    All-or-nothing: any invalid row -> 422 listing every problem, nothing saved.
    Uploading the same file twice is safe (trades are matched by trade_id).
    """
    if file.filename and not file.filename.lower().endswith(".csv"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Please upload a .csv file.")
    # Read one byte past the limit so oversized files are detected without reading them fully.
    content = await file.read(tradebook_import.MAX_FILE_BYTES + 1)
    try:
        return await tradebook_import.import_tradebook(db, user.id, content)
    except tradebook_import.StatementError as exc:
        raise HTTPException(
            422,  # plain number: Starlette renamed this constant between versions
            {"message": exc.message, "row_errors": exc.row_errors},
        ) from None


# ======================================================================
# 3. Zerodha Kite Connect
# ======================================================================

def _zerodha_http_error(exc: zerodha.ZerodhaError) -> HTTPException:
    if isinstance(exc, zerodha.ZerodhaNotConfigured):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    if isinstance(exc, zerodha.ZerodhaNotConnected | zerodha.ZerodhaTokenExpired):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@router.get("/zerodha/connect", response_model=ZerodhaLoginUrl)
async def zerodha_connect(user: User = Depends(get_current_user)):
    """
    Returns the Zerodha login URL. The frontend sends the browser there with
    `window.location.href = login_url`. (A plain redirect can't be used: a
    browser navigation would not carry the user's Bearer token.)
    """
    try:
        return ZerodhaLoginUrl(login_url=zerodha.build_login_url(user.id))
    except zerodha.ZerodhaError as exc:
        raise _zerodha_http_error(exc) from None


@router.get("/zerodha/callback", include_in_schema=False)
async def zerodha_callback(
    request_token: str | None = None,
    status_: str | None = Query(default=None, alias="status"),
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Zerodha redirects the browser here after login. We finish the connection,
    run a first sync, and send the browser back to the frontend with
    ?zerodha=connected | cancelled | invalid_state | error.
    """

    def back_to_frontend(result: str) -> RedirectResponse:
        return RedirectResponse(f"{settings.FRONTEND_URL}/portfolio?zerodha={result}", status_code=303)

    user_id = zerodha.user_id_from_state(state)
    if user_id is None:  # missing, forged or expired (> 10 min) state
        logger.warning("Zerodha callback with invalid state")
        return back_to_frontend("invalid_state")
    if status_ != "success" or not request_token:
        return back_to_frontend("cancelled")

    try:
        await zerodha.complete_login(db, user_id, request_token)
    except zerodha.ZerodhaError:
        return back_to_frontend("error")

    try:
        await zerodha.sync_with_session(db, user_id)
    except zerodha.ZerodhaError as exc:  # connected fine; the user can retry the sync
        logger.warning("Initial Zerodha sync failed for user %s: %s", user_id, exc)
    return back_to_frontend("connected")


@router.get("/zerodha/status", response_model=ZerodhaStatus)
async def zerodha_status(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    connection = await zerodha.get_connection(db, user.id)
    if not zerodha.is_active(connection):
        return ZerodhaStatus(connected=False)
    return ZerodhaStatus(
        connected=True,
        broker_user_id=connection.broker_user_id,
        expires_at=connection.expires_at,
        last_synced_at=connection.last_synced_at,
    )


@router.post("/zerodha/sync", response_model=ZerodhaSyncReport)
async def zerodha_sync(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Re-read holdings from Zerodha now."""
    try:
        return await zerodha.sync_with_session(db, user.id)
    except zerodha.ZerodhaError as exc:
        raise _zerodha_http_error(exc) from None


@router.delete("/zerodha", status_code=status.HTTP_204_NO_CONTENT)
async def zerodha_disconnect(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Forget the Zerodha token and remove Zerodha-synced holdings."""
    await zerodha.disconnect(db, user.id)
