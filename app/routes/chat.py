"""
Chat API routes for AI-powered stock analysis.

Endpoints:
- POST /stocks/{ticker}/chat - Chat with AI about a stock
"""

import logging
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel
from openai import OpenAI

from src.db import execute_sql
from src.price_service import get_latest_close

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    """Chat request body."""

    message: str
    context: Optional[str] = None


class ChatResponse(BaseModel):
    """Chat response."""

    response: str
    sources: list[str]


@router.post("/{ticker}/chat", response_model=ChatResponse)
async def chat_about_stock(
    ticker: str = Path(..., description="Stock ticker symbol"),
    request: ChatRequest = ...,
):
    """
    Chat with AI about a stock using OpenAI.

    The AI has access to:
    - Recent trading ideas from Discord
    - Current price and change data
    - Position information if owned

    Args:
        ticker: Stock ticker symbol
        request: Chat message and optional context

    Returns:
        AI response with sources used
    """
    symbol = ticker.upper()

    try:
        # Gather context about the stock
        context_parts = []
        sources = []

        # Get current price
        current_price = get_latest_close(symbol)
        if current_price:
            context_parts.append(f"Current price of {symbol}: ${current_price:.2f}")
            sources.append("OHLCV data")

        # Get recent ideas
        ideas_data = execute_sql(
            """
            SELECT
                dpi.direction,
                dpi.labels,
                dpi.raw_chunk,
                dm.created_at,
                dm.author_name
            FROM discord_parsed_ideas dpi
            LEFT JOIN discord_messages dm ON dpi.message_id = dm.message_id
            WHERE UPPER(dpi.primary_symbol) = :symbol
            ORDER BY dm.created_at DESC
            LIMIT 5
            """,
            params={"symbol": symbol},
            fetch_results=True,
        )

        if ideas_data:
            ideas_context = f"\n\nRecent trading ideas for {symbol}:\n"
            for idea in ideas_data:
                direction = idea.get("direction", "neutral")
                labels = idea.get("labels", [])
                raw_text = idea.get("raw_chunk", "")[:200]
                author = idea.get("author_name", "Unknown")
                ideas_context += f"- [{direction.upper()}] {', '.join(labels) if labels else 'No labels'}: \"{raw_text}\" - {author}\n"
            context_parts.append(ideas_context)
            sources.append("Discord trading ideas")

        # Get position if owned
        position_data = execute_sql(
            """
            SELECT
                p.quantity,
                p.average_cost
            FROM positions p
            WHERE UPPER(p.symbol) = :symbol
              AND p.quantity > 0
            LIMIT 1
            """,
            params={"symbol": symbol},
            fetch_results=True,
        )

        if position_data:
            pos = position_data[0]
            qty = pos["quantity"]
            avg_cost = pos["average_cost"]
            context_parts.append(
                f"\nYou own {qty} shares of {symbol} at avg cost ${avg_cost:.2f}"
            )
            sources.append("Portfolio positions")

        # Build system prompt
        system_prompt = f"""You are an expert stock analyst assistant for the LLM Portfolio Journal.
You help analyze stocks and provide insights based on available data.

Available context:
{chr(10).join(context_parts)}

Guidelines:
- Be concise but thorough
- Cite the sources when referencing data
- Acknowledge uncertainty when appropriate
- Do not provide specific buy/sell recommendations
- Focus on analysis and education
"""

        # Additional context from user
        if request.context:
            system_prompt += f"\n\nAdditional context from user: {request.context}"

        # Call OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        completion = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL_CHAT", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.message},
            ],
            max_tokens=1000,
            temperature=0.7,
        )

        response_text = (
            completion.choices[0].message.content or "I couldn't generate a response."
        )

        return ChatResponse(
            response=response_text,
            sources=sources,
        )

    except Exception as e:
        logger.error(f"Error in chat for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")
