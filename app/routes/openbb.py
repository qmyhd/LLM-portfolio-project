"""
OpenBB Insights API routes.

Endpoints:
- GET /stocks/{ticker}/transcript   - Earnings call transcripts
- GET /stocks/{ticker}/management   - Key executives
- GET /stocks/{ticker}/fundamentals - Financial metrics
- GET /stocks/{ticker}/filings      - SEC filings
- GET /stocks/{ticker}/news         - Company news
"""

import asyncio
import logging
import re

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Ticker validation
# ---------------------------------------------------------------------------
_TICKER_RE = re.compile(r"^[A-Z]{1,6}(\.[A-Z]+)?$")


def _validate_ticker(raw: str) -> str:
    symbol = raw.strip().upper()
    if not _TICKER_RE.match(symbol):
        raise HTTPException(status_code=400, detail=f"Invalid ticker: {raw}")
    return symbol


# ---------------------------------------------------------------------------
# Response models (camelCase, matches frontend types)
# ---------------------------------------------------------------------------

class TranscriptItem(BaseModel):
    date: str | None = None
    content: str
    quarter: int | None = None
    year: int | None = None
    symbol: str


class TranscriptResponse(BaseModel):
    ticker: str
    transcripts: list[TranscriptItem]


class ExecutiveItem(BaseModel):
    name: str
    title: str
    pay: int | None = None
    currency: str | None = None
    gender: str | None = None
    yearBorn: int | None = None
    titleSince: str | None = None


class ManagementResponse(BaseModel):
    ticker: str
    executives: list[ExecutiveItem]


class FundamentalsResponse(BaseModel):
    ticker: str
    marketCap: float | None = None
    peRatio: float | None = None
    pegRatio: float | None = None
    epsActual: float | None = None
    revenuePerShare: float | None = None
    debtToEquity: float | None = None
    currentRatio: float | None = None
    returnOnEquity: float | None = None
    returnOnAssets: float | None = None
    dividendYield: float | None = None
    priceToBook: float | None = None
    priceToSales: float | None = None
    bookValuePerShare: float | None = None
    freeCashFlowPerShare: float | None = None


class FilingItem(BaseModel):
    filingDate: str | None = None
    formType: str
    reportUrl: str | None = None
    description: str | None = None
    acceptedDate: str | None = None


class FilingsResponse(BaseModel):
    ticker: str
    filings: list[FilingItem]
    total: int


class NewsItem(BaseModel):
    date: str | None = None
    title: str
    text: str | None = None
    url: str | None = None
    source: str | None = None
    images: list[str] = Field(default_factory=list)


class NewsResponse(BaseModel):
    ticker: str
    articles: list[NewsItem]
    total: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{ticker}/transcript", response_model=TranscriptResponse)
async def get_transcript(
    ticker: str = Path(...),
    year: int | None = Query(None, description="Year (defaults to current)"),
    quarter: int | None = Query(None, ge=1, le=4, description="Quarter (1-4)"),
):
    """Get earnings call transcripts for a stock (FMP provider)."""
    symbol = _validate_ticker(ticker)
    try:
        from src.openbb_service import get_earnings_transcript

        data = await asyncio.to_thread(get_earnings_transcript, symbol, year, quarter)

        transcripts = []
        for item in data or []:
            transcripts.append(TranscriptItem(**item))

        return TranscriptResponse(ticker=symbol, transcripts=transcripts)
    except Exception as e:
        logger.error("Transcript error for %s: %s", symbol, e)
        return TranscriptResponse(ticker=symbol, transcripts=[])


@router.get("/{ticker}/management", response_model=ManagementResponse)
async def get_management_team(ticker: str = Path(...)):
    """Get key executives for a stock (FMP provider)."""
    symbol = _validate_ticker(ticker)
    try:
        from src.openbb_service import get_management

        data = await asyncio.to_thread(get_management, symbol)

        executives = []
        for item in data or []:
            executives.append(ExecutiveItem(**item))

        return ManagementResponse(ticker=symbol, executives=executives)
    except Exception as e:
        logger.error("Management error for %s: %s", symbol, e)
        return ManagementResponse(ticker=symbol, executives=[])


@router.get("/{ticker}/fundamentals", response_model=FundamentalsResponse)
async def get_fundamental_metrics(ticker: str = Path(...)):
    """Get fundamental financial metrics for a stock (FMP provider)."""
    symbol = _validate_ticker(ticker)
    try:
        from src.openbb_service import get_fundamentals

        data = await asyncio.to_thread(get_fundamentals, symbol)

        if data:
            return FundamentalsResponse(ticker=symbol, **data)
        return FundamentalsResponse(ticker=symbol)
    except Exception as e:
        logger.error("Fundamentals error for %s: %s", symbol, e)
        return FundamentalsResponse(ticker=symbol)


@router.get("/{ticker}/filings", response_model=FilingsResponse)
async def get_sec_filings(
    ticker: str = Path(...),
    form_type: str | None = Query(None, description="SEC form type (10-K, 10-Q, 8-K)"),
    limit: int = Query(10, ge=1, le=50),
):
    """Get SEC filings for a stock (SEC provider, free)."""
    symbol = _validate_ticker(ticker)
    try:
        from src.openbb_service import get_filings

        data = await asyncio.to_thread(get_filings, symbol, form_type, limit)

        filings = []
        for item in data or []:
            filings.append(FilingItem(**item))

        payload = FilingsResponse(ticker=symbol, filings=filings, total=len(filings))
        return JSONResponse(
            content=payload.model_dump(),
            headers={"Cache-Control": "public, max-age=3600, stale-while-revalidate=300"},
        )
    except Exception as e:
        logger.error("Filings error for %s: %s", symbol, e)
        return FilingsResponse(ticker=symbol, filings=[], total=0)


@router.get("/{ticker}/news", response_model=NewsResponse)
async def get_stock_news(
    ticker: str = Path(...),
    limit: int = Query(10, ge=1, le=50),
):
    """Get company news for a stock (FMP provider)."""
    symbol = _validate_ticker(ticker)
    try:
        from src.openbb_service import get_company_news

        data = await asyncio.to_thread(get_company_news, symbol, limit)

        articles = []
        for item in data or []:
            articles.append(NewsItem(**item))

        return NewsResponse(ticker=symbol, articles=articles, total=len(articles))
    except Exception as e:
        logger.error("News error for %s: %s", symbol, e)
        return NewsResponse(ticker=symbol, articles=[], total=0)


# (per-stock notes routes removed — the stock_notes feature was cut.)
