import os
import pandas as pd
import json
import re
import textwrap
import logging
import functools
import time
import argparse
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import functools

#############################################################
# CONFIGURATION
#############################################################

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Define directories using Path objects
BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# File paths using Path objects
DISCORD_CSV = RAW_DIR / "discord_msgs.csv"
POSITIONS_CSV = RAW_DIR / "positions.csv"
ORDERS_CSV = RAW_DIR / "orders.csv"
PRICES_CSV = RAW_DIR / "prices.csv"

#############################################################
# UTILITY FUNCTIONS
#############################################################

def retry_decorator(max_retries=3, delay=1):
    """Decorator to retry API calls in case of transient failures
    
    Args:
        max_retries: Maximum number of retries before giving up
        delay: Initial delay between retries in seconds (doubles after each retry)
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            current_delay = delay
            
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    if retries >= max_retries:
                        logger.error(f"Failed after {max_retries} retries: {e}")
                        raise
                    
                    logger.warning(f"Retry {retries}/{max_retries} after error: {e}")
                    time.sleep(current_delay)
                    current_delay *= 2
        
        return wrapper
    return decorator

def get_api_key():
    """Get API key from environment variables, trying multiple options
    
    Returns:
        API key from environment variables, prioritizing OPENAI_API_KEY, then GEMINI_API_KEY
    """
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("GEMINI_API_KEY")
    
    if not api_key:
        logger.error("No API key found. Please set OPENAI_API_KEY or GEMINI_API_KEY in .env file")
        raise ValueError("Missing API key in environment variables")
    
    return api_key

#############################################################
# DATA LOADING FUNCTIONS
#############################################################

def load_positions(file_path=None):
    """Load position data from CSV file
    
    Args:
        file_path: Path to the positions CSV file
        
    Returns:
        DataFrame containing position data, or empty DataFrame if file not found
    """
    file_path = file_path or POSITIONS_CSV
    
    try:
        positions_df = pd.read_csv(file_path)
        logger.info(f"✅ Loaded positions data with {len(positions_df)} records")
        
        # Sort positions by equity descending
        if 'equity' in positions_df.columns:
            positions_df = positions_df.sort_values('equity', ascending=False)
            
        return positions_df
    except FileNotFoundError:
        logger.warning(f"⚠️ {file_path} not found")
        return pd.DataFrame()

def load_discord_messages(file_path=None):
    """Load Discord messages from CSV file
    
    Args:
        file_path: Path to the Discord messages CSV file
        
    Returns:
        DataFrame containing Discord messages, or empty DataFrame if file not found
    """
    file_path = file_path or DISCORD_CSV
    
    try:
        messages_df = pd.read_csv(file_path)
        logger.info(f"✅ Loaded Discord messages data with {len(messages_df)} records")
        return messages_df
    except FileNotFoundError:
        logger.warning(f"⚠️ {file_path} not found")
        return pd.DataFrame()

def load_prices(file_path=None):
    """Load price data from CSV file
    
    Args:
        file_path: Path to the prices CSV file
        
    Returns:
        DataFrame containing price data, or empty DataFrame if file not found
    """
    file_path = file_path or PRICES_CSV
    
    try:
        prices_df = pd.read_csv(file_path)
        logger.info(f"✅ Loaded price data with {len(prices_df)} records")
        return prices_df
    except FileNotFoundError:
        logger.warning(f"⚠️ {file_path} not found")
        return pd.DataFrame()

#############################################################
# DATA FORMATTING FUNCTIONS
#############################################################

def format_holdings_as_json(positions_df):
    """Format holdings data as JSON for better LLM parsing
    
    Args:
        positions_df: DataFrame containing position data
        
    Returns:
        JSON string representing holdings data
    """
    if positions_df.empty:
        return json.dumps({"holdings": []})
    
    # Convert DataFrame to list of dictionaries
    holdings = []
    for _, row in positions_df.iterrows():
        holding = {
            "symbol": row.get("symbol", "Unknown"),
            "quantity": row.get("quantity", 0),
            "equity": row.get("equity", 0),
            "price": row.get("price", 0),
            "avg_price": row.get("average_buy_price", 0),
        }
        holdings.append(holding)
    
    return json.dumps({"holdings": holdings}, indent=2)

def format_prices_as_json(prices_df):
    """Format price data as JSON for better LLM parsing
    
    Args:
        prices_df: DataFrame containing price data
        
    Returns:
        JSON string representing price data with net change included
    """
    if prices_df.empty:
        return json.dumps({"prices": []})
    
    # Convert DataFrame to list of dictionaries with net change
    price_data = []
    for _, row in prices_df.iterrows():
        price = {
            "symbol": row.get("symbol", "Unknown"),
            "price": row.get("price", 0),
            "previous_close": row.get("previous_close", 0),
            "net_change": row.get("price", 0) - row.get("previous_close", 0),
            "percent_change": (row.get("price", 0) / row.get("previous_close", 1) - 1) * 100 if row.get("previous_close", 0) > 0 else 0,
            "timestamp": row.get("timestamp", "")
        }
        price_data.append(price)
    
    return json.dumps({"prices": price_data}, indent=2)

#############################################################
# TEXT ANALYSIS FUNCTIONS
#############################################################

def extract_ticker_and_text_pairs(thread_text):
    """Extract ticker and text pairs from a thread containing multiple ticker analyses
    
    This function splits a multi-ticker post into individual ticker-text pairs,
    allowing us to process each ticker analysis separately.
    
    Args:
        thread_text: Text containing multiple ticker analyses
        
    Returns:
        List of (ticker, text) pairs
    """
    if not thread_text:
        return []
    
    pairs = []
    # Find all ticker symbols with their positions
    ticker_matches = list(re.finditer(r'\$[A-Z]{1,6}\b', thread_text))
    
    for i, match in enumerate(ticker_matches):
        # Extract the ticker symbol
        ticker = match.group(0)
        # Get the start position of this ticker
        start_pos = match.start()
        
        # Get the end position (either the start of the next ticker or the end of the text)
        end_pos = ticker_matches[i+1].start() if i < len(ticker_matches) - 1 else len(thread_text)
        
        # Extract the text for this ticker
        text = thread_text[start_pos:end_pos].strip()
        
        # Only add if we have meaningful text
        if text:
            pairs.append((ticker, text))
    
    return pairs

#############################################################
# LLM INTEGRATION FUNCTIONS
#############################################################

@retry_decorator(max_retries=3, delay=2)
def generate_journal_entry(prompt, max_tokens=160):
    """Generate journal entry using LLM API with retry capability
    
    This function handles the actual API call to Google's Gemini API,
    applying retries for resilience against transient errors.
    
    Args:
        prompt: The prompt to send to the LLM
        max_tokens: Maximum number of tokens to generate (default: 160)
        
    Returns:
        Generated journal entry text
    """
    try:
        # Try to use Google's Gemini API first (free tier)
        import google.generativeai as genai
        
        # Set API key
        api_key = os.getenv("GEMINI_API_KEY")
        
        if not api_key:
            logger.warning("No GEMINI_API_KEY found in environment variables. Falling back to OpenAI.")
            return generate_with_openai(prompt, max_tokens)
        
        genai.configure(api_key=api_key)
        
        logger.info("🔄 Generating journal entry with Gemini...")
        
        # Configure the model
        generation_config = {
            "temperature": 0.2,
            "top_p": 0.95,
            "top_k": 0,
            "max_output_tokens": max_tokens,
        }
        
        # Get default (latest) text model
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config=generation_config
        )
        
        # Create the system instruction + user prompt format
        system_instruction = "You are a financial writing assistant."
        formatted_prompt = f"{system_instruction}\n\n{prompt}"
        
        # Generate content
        response = model.generate_content(formatted_prompt)
        
        # Check if the response has text
        if hasattr(response, 'text'):
            return response.text
        else:
            # Different response structure - try to get the content
            try:
                return response.candidates[0].content.parts[0].text
            except (AttributeError, IndexError):
                logger.error("Unexpected response structure from Gemini API")
                return "Error generating journal entry. Please try again."
    
    except ImportError:
        logger.warning("Google GenerativeAI module not installed. Trying OpenAI instead.")
        return generate_with_openai(prompt, max_tokens)
    except Exception as e:
        logger.error(f"Error generating journal entry with Gemini: {e}")
        # Fall back to OpenAI if Gemini fails
        logger.info("Falling back to OpenAI...")
        return generate_with_openai(prompt, max_tokens)

def generate_with_openai(prompt, max_tokens=160):
    """Fallback function to use OpenAI if Gemini is not available
    
    Args:
        prompt: The prompt to send to the LLM
        max_tokens: Maximum number of tokens to generate (default: 160)
        
    Returns:
        Generated journal entry text
    """
    try:
        import openai
        # Set API key
        api_key = os.getenv("OPENAI_API_KEY")
        
        if not api_key:
            logger.error("No API key found for either Gemini or OpenAI in environment variables")
            return "Error: No API key available for LLM services."
        
        openai.api_key = api_key
        
        logger.info("🔄 Generating journal entry with OpenAI...")
        
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",  # Using gpt-4o-mini for cost-effective yet high-quality output
            messages=[
                {"role": "system", "content": "You are a financial writing assistant."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=max_tokens  # Limit output to approximately 120 words
        )
        
        return resp.choices[0].message.content
    except ImportError:
        logger.error("Neither Google GenerativeAI nor OpenAI modules are installed.")
        return "Error: LLM libraries not installed. Install with: pip install openai google-generativeai"
    except Exception as e:
        logger.error(f"Error generating journal entry with OpenAI: {e}")
        return f"Error generating journal entry: {str(e)}"

#############################################################
# PROMPT CREATION FUNCTIONS
#############################################################

def create_journal_prompt(positions_df, messages_df, prices_df):
    """Create a prompt for the LLM to generate a journal entry
    
    This is the basic prompt builder - we also have an enhanced version below
    that includes more structured data for better results.
    
    Args:
        positions_df: DataFrame containing position data
        messages_df: DataFrame containing Discord messages
        prices_df: DataFrame containing price data
        
    Returns:
        Prompt for the LLM
    """
    # Get recent Discord messages about stocks
    recent_stock_messages = ""
    if not messages_df.empty:
        # Filter messages containing ticker symbols
        stock_msgs = messages_df[messages_df['tickers_detected'].notna() & (messages_df['tickers_detected'] != '')]
        # Sort by most recent first
        stock_msgs = stock_msgs.sort_values('created_at', ascending=False).head(5)
        if not stock_msgs.empty:
            recent_stock_messages = "\n\n".join(stock_msgs['content'].tolist())
    
    # Format the holdings snapshot as JSON
    holdings_json = format_holdings_as_json(positions_df)
    
    # Format price movements as JSON with net change
    prices_json = format_prices_as_json(prices_df)
    
    # Create the prompt
    prompt = f"""
You are an assistant that writes a 1-paragraph portfolio recap.

<holdings>
{holdings_json}
</holdings>

Recent chat highlights:
{recent_stock_messages if recent_stock_messages else 'N/A'}

<prices>
{prices_json}
</prices>

Return a concise update (<120 words) noting big movers, total value change, and any sentiment cues.
"""
    
    return prompt

def save_journal_entry(journal_entry, output_dir=None):
    """Save journal entry to a file with ISO date format
    
    Args:
        journal_entry: Journal entry text to save
        output_dir: Directory to save the journal entry (default: data/processed)
        
    Returns:
        Path to the saved journal entry file
    """
    output_dir = output_dir or PROCESSED_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Use ISO date format for easier sorting (YYYY-MM-DD)
    today = datetime.now().strftime("%Y-%m-%d")
    output_path = output_dir / f"journal_{today}.txt"
    
    with open(output_path, 'w') as f:
        f.write(journal_entry)
    
    logger.info(f"✅ Journal saved to {output_path}")
    return output_path

#############################################################
# PORTFOLIO ANALYSIS FUNCTIONS
#############################################################

def analyze_position_data(positions_df, prices_df):
    """Analyze position data to extract insights about the portfolio
    
    This function processes the raw position and price data to extract
    meaningful insights like top positions, gainers, and losers.
    
    Args:
        positions_df: DataFrame containing position data
        prices_df: DataFrame containing price data
        
    Returns:
        Dictionary with portfolio insights
    """
    if positions_df.empty:
        return {
            "total_equity": 0,
            "top_positions": [],
            "gainers": [],
            "losers": []
        }
    
    # Create a price lookup dictionary
    price_lookup = {}
    if not prices_df.empty:
        for _, row in prices_df.iterrows():
            symbol = row.get('symbol')
            if symbol:
                price_lookup[symbol] = {
                    'price': row.get('price', 0),
                    'previous_close': row.get('previous_close', 0),
                    'change': row.get('change', 0),
                    'change_percent': row.get('change_percent', 0)
                }
    
    # Calculate total portfolio value
    total_equity = positions_df['equity'].sum() if 'equity' in positions_df.columns else 0
    
    # Get top positions by equity value
    top_positions = []
    if not positions_df.empty and 'equity' in positions_df.columns:
        top_df = positions_df.sort_values('equity', ascending=False).head(5)
        for _, row in top_df.iterrows():
            symbol = row.get('symbol', 'Unknown')
            equity = row.get('equity', 0)
            quantity = row.get('quantity', 0)
            price = row.get('price', 0)
            
            # Get price change if available
            change_pct = None
            if symbol in price_lookup:
                change_pct = price_lookup[symbol].get('change_percent')
            
            top_positions.append({
                'symbol': symbol,
                'equity': equity,
                'quantity': quantity,
                'price': price,
                'change_percent': change_pct
            })
    
    # Calculate gainers and losers (if price data available)
    gainers = []
    losers = []
    
    if price_lookup and not positions_df.empty:
        # Add price data to positions
        for _, row in positions_df.iterrows():
            symbol = row.get('symbol', 'Unknown')
            if symbol in price_lookup:
                change_pct = price_lookup[symbol].get('change_percent', 0)
                
                position_data = {
                    'symbol': symbol,
                    'equity': row.get('equity', 0),
                    'change_percent': change_pct,
                    'price': row.get('price', 0)
                }
                
                if change_pct > 0:
                    gainers.append(position_data)
                elif change_pct < 0:
                    losers.append(position_data)
        
        # Sort gainers and losers by change percentage
        gainers = sorted(gainers, key=lambda x: x.get('change_percent', 0), reverse=True)[:3]
        losers = sorted(losers, key=lambda x: x.get('change_percent', 0))[:3]
    
    return {
        "total_equity": total_equity,
        "top_positions": top_positions,
        "gainers": gainers,
        "losers": losers
    }

#############################################################
# SENTIMENT ANALYSIS FUNCTIONS
#############################################################

def extract_sentiment_from_messages(messages_df, ticker=None):
    """Extract sentiment information from Discord messages
    
    This function analyzes the Discord messages to determine overall
    sentiment and ticker-specific insights.
    
    Args:
        messages_df: DataFrame containing Discord messages
        ticker: Optional ticker symbol to filter messages for
        
    Returns:
        Dictionary with sentiment insights
    """
    if messages_df.empty:
        return {
            "overall_sentiment": "neutral",
            "message_count": 0,
            "recent_tickers": [],
            "ticker_mentions": {}
        }
    
    # Filter for recent messages containing ticker symbols
    if 'tickers_detected' in messages_df.columns:
        stock_msgs = messages_df[messages_df['tickers_detected'].notna() & (messages_df['tickers_detected'] != '')]
    else:
        stock_msgs = messages_df
    
    # Count by ticker symbol
    ticker_counts = {}
    for _, row in stock_msgs.iterrows():
        tickers = row.get('tickers_detected', '')
        if isinstance(tickers, str) and tickers:
            for ticker in tickers.split(','):
                ticker = ticker.strip()
                if ticker:
                    ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1
    
    # Get most mentioned tickers
    sorted_tickers = sorted(ticker_counts.items(), key=lambda x: x[1], reverse=True)
    recent_tickers = [t[0] for t in sorted_tickers[:5]]
    
    # Calculate average sentiment if sentiment_score column exists
    overall_sentiment = "neutral"
    avg_sentiment = 0
    if 'sentiment_score' in stock_msgs.columns:
        sentiment_values = stock_msgs['sentiment_score'].dropna()
        if not sentiment_values.empty:
            avg_sentiment = sentiment_values.mean()
            if avg_sentiment > 0.1:
                overall_sentiment = "positive"
            elif avg_sentiment < -0.1:
                overall_sentiment = "negative"
    
    # Get ticker-specific data if requested
    ticker_data = {}
    if ticker:
        # Filter messages mentioning this ticker
        if 'tickers_detected' in stock_msgs.columns:
            ticker_msgs = stock_msgs[stock_msgs['tickers_detected'].str.contains(ticker, na=False)]
            
            if not ticker_msgs.empty:
                # Get average sentiment for this ticker
                ticker_sentiment = "neutral"
                if 'sentiment_score' in ticker_msgs.columns:
                    sentiment_values = ticker_msgs['sentiment_score'].dropna()
                    if not sentiment_values.empty:
                        avg_ticker_sentiment = sentiment_values.mean()
                        if avg_ticker_sentiment > 0.1:
                            ticker_sentiment = "positive"
                        elif avg_ticker_sentiment < -0.1:
                            ticker_sentiment = "negative"
                
                # Get recent messages about this ticker
                recent_msgs = ticker_msgs.sort_values('created_at', ascending=False).head(3)
                recent_content = [msg for msg in recent_msgs['content'].tolist() if msg]
                
                ticker_data = {
                    "sentiment": ticker_sentiment,
                    "message_count": len(ticker_msgs),
                    "recent_messages": recent_content
                }
    
    return {
        "overall_sentiment": overall_sentiment,
        "message_count": len(stock_msgs),
        "recent_tickers": recent_tickers,
        "ticker_mentions": dict(sorted_tickers[:10]),
        "ticker_data": ticker_data if ticker else {}
    }

def create_enhanced_journal_prompt(positions_df, messages_df, prices_df):
    """Create an enhanced prompt for the LLM to generate a journal entry
    
    This function creates a more structured and detailed prompt than the basic version,
    incorporating portfolio analysis and sentiment insights.
    
    Args:
        positions_df: DataFrame containing position data
        messages_df: DataFrame containing Discord messages
        prices_df: DataFrame containing price data
        
    Returns:
        Enhanced prompt for the LLM
    """
    # Get portfolio analysis
    portfolio_analysis = analyze_position_data(positions_df, prices_df)
    
    # Get sentiment analysis from Discord
    sentiment_analysis = extract_sentiment_from_messages(messages_df)
    
    # Calculate portfolio metrics
    total_equity = portfolio_analysis.get('total_equity', 0)
    top_positions = portfolio_analysis.get('top_positions', [])
    gainers = portfolio_analysis.get('gainers', [])
    losers = portfolio_analysis.get('losers', [])
    
    # Format top positions for the prompt
    top_positions_text = ""
    for pos in top_positions:
        change_text = f" ({pos.get('change_percent', 0):.2f}%)" if pos.get('change_percent') is not None else ""
        top_positions_text += f"- {pos.get('symbol')}: ${pos.get('equity', 0):.2f}{change_text}\n"
    
    # Format gainers and losers
    gainers_text = ""
    for pos in gainers:
        gainers_text += f"- {pos.get('symbol')}: +{pos.get('change_percent', 0):.2f}%\n"
    
    losers_text = ""
    for pos in losers:
        losers_text += f"- {pos.get('symbol')}: {pos.get('change_percent', 0):.2f}%\n"
    
    # Format discord insights
    recent_tickers = sentiment_analysis.get('recent_tickers', [])
    overall_sentiment = sentiment_analysis.get('overall_sentiment', 'neutral')
    message_count = sentiment_analysis.get('message_count', 0)
    
    ticker_mentions = sentiment_analysis.get('ticker_mentions', {})
    ticker_mentions_text = ""
    for ticker, count in ticker_mentions.items():
        ticker_mentions_text += f"- {ticker}: {count} mentions\n"
    
    # Get recent Discord messages about stocks
    recent_stock_messages = ""
    if not messages_df.empty:
        # Filter messages containing ticker symbols
        if 'tickers_detected' in messages_df.columns:
            stock_msgs = messages_df[messages_df['tickers_detected'].notna() & (messages_df['tickers_detected'] != '')]
            # Sort by most recent first
            stock_msgs = stock_msgs.sort_values('created_at', ascending=False).head(3)
            if not stock_msgs.empty:
                for idx, row in stock_msgs.iterrows():
                    content = row.get('content', '')
                    tickers = row.get('tickers_detected', '')
                    if content and tickers:
                        recent_stock_messages += f"Message about {tickers}: {content}\n\n"
    
    # Create the enhanced prompt
    prompt = f"""
You are a financial journal assistant that writes insightful portfolio recaps.

Portfolio Summary:
- Total Value: ${total_equity:.2f}
- Top Positions:
{top_positions_text}

Market Movers:
- Gainers:
{gainers_text if gainers else "No significant gainers today"}
- Losers:
{losers_text if losers else "No significant losers today"}

Discord Insights:
- Overall sentiment: {overall_sentiment}
- {message_count} market-related messages
- Most discussed tickers: {', '.join(recent_tickers) if recent_tickers else "None"}
- Ticker mentions:
{ticker_mentions_text if ticker_mentions_text else "No ticker mentions"}

Recent relevant messages:
{recent_stock_messages if recent_stock_messages else "No recent stock messages"}

Write a concise daily journal entry (max 120 words) that summarizes the portfolio performance, 
highlights key movers, and incorporates relevant sentiment from Discord discussions.
The entry should be insightful, analytical, and provide context for the current portfolio state.
"""
    
    return prompt

#############################################################
# MAIN JOURNAL GENERATION FUNCTION
#############################################################

def generate_portfolio_journal(positions_path=None, discord_path=None, prices_path=None, output_dir=None):
    """Generate portfolio journal entry and save to file
    
    This is the main function that orchestrates the entire journal generation process,
    from data loading to LLM generation to saving outputs.
    
    Args:
        positions_path: Path to positions CSV file
        discord_path: Path to Discord messages CSV file
        prices_path: Path to prices CSV file
        output_dir: Directory to save the journal entry
        
    Returns:
        Generated journal entry text
    """
    # Load data
    positions_df = load_positions(positions_path)
    messages_df = load_discord_messages(discord_path)
    prices_df = load_prices(prices_path)
    
    # Check if positions data is valid (has symbols other than "Unknown")
    if not positions_df.empty and 'symbol' in positions_df.columns:
        unknown_count = (positions_df['symbol'] == 'Unknown').sum()
        total_count = len(positions_df)
        
        if unknown_count == total_count:
            logger.warning("⚠️ All position symbols are 'Unknown'. The journal may not be accurate.")
            # Try to use price data to infer symbols if we have equity data
            if 'price' in positions_df.columns and 'quantity' in positions_df.columns:
                logger.info("Attempting to infer symbols from price data...")
                # For each position, assign a temporary symbol based on price
                positions_df['symbol'] = positions_df.apply(
                    lambda row: f"Symbol-{row['price']:.2f}" if row['symbol'] == 'Unknown' else row['symbol'], 
                    axis=1
                )
                logger.info(f"Generated {total_count} temporary symbols based on price")
    
    # Create enhanced prompt that handles the "Unknown" symbol issue
    prompt = create_enhanced_journal_prompt(positions_df, messages_df, prices_df)
    
    # Generate journal entry
    try:
        journal_entry = generate_journal_entry(prompt, max_tokens=200)
        
        # Format entry for display
        formatted_entry = textwrap.fill(journal_entry, 90)
        
        print("\n✅ Journal Entry Generated:")
        print("=" * 90)
        print(formatted_entry)
        print("=" * 90)
        
        # Save to file
        output_path = save_journal_entry(journal_entry, output_dir)
        
        # Also create a markdown version with additional details
        create_markdown_journal(
            journal_entry, 
            positions_df, 
            messages_df, 
            prices_df, 
            output_dir
        )
        
        return journal_entry
    except Exception as e:
        logger.error(f"❌ Error generating journal entry: {e}")
        return None

#############################################################
# MARKDOWN OUTPUT GENERATION
#############################################################

def create_markdown_journal(journal_entry, positions_df, messages_df, prices_df, output_dir=None):
    """Create a markdown version of the journal with additional details
    
    This function creates a rich markdown output with tables and detailed sections,
    providing more context than the simple text journal entry.
    
    Args:
        journal_entry: The generated journal entry text
        positions_df: DataFrame containing position data
        messages_df: DataFrame containing Discord messages
        prices_df: DataFrame containing price data
        output_dir: Directory to save the markdown file
        
    Returns:
        Path to the saved markdown file
    """
    output_dir = output_dir or PROCESSED_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Use ISO date format for easier sorting (YYYY-MM-DD)
    today = datetime.now().strftime("%Y-%m-%d")
    output_path = output_dir / f"journal_{today}.md"
    
    # Get portfolio analysis
    portfolio_analysis = analyze_position_data(positions_df, prices_df)
    
    # Create markdown content
    md_content = f"""# Portfolio Journal - {today}

## Summary
{journal_entry}

## Portfolio Details

### Overall Value
- Total Equity: ${portfolio_analysis.get('total_equity', 0):.2f}

### Top Positions
"""
    
    # Add top positions table
    if portfolio_analysis.get('top_positions'):
        md_content += """
| Symbol | Quantity | Price | Equity | Change |
| ------ | -------: | ----: | -----: | -----: |
"""
        for pos in portfolio_analysis.get('top_positions'):
            change = f"{pos.get('change_percent', 0):.2f}%" if pos.get('change_percent') is not None else "N/A"
            md_content += f"| {pos.get('symbol')} | {pos.get('quantity', 0):.2f} | ${pos.get('price', 0):.2f} | ${pos.get('equity', 0):.2f} | {change} |\n"
    else:
        md_content += "No position data available.\n"
    
    # Add gainers and losers
    md_content += "\n### Today's Movers\n\n#### Gainers\n"
    if portfolio_analysis.get('gainers'):
        md_content += """
| Symbol | Price | Change |
| ------ | ----: | -----: |
"""
        for pos in portfolio_analysis.get('gainers'):
            md_content += f"| {pos.get('symbol')} | ${pos.get('price', 0):.2f} | +{pos.get('change_percent', 0):.2f}% |\n"
    else:
        md_content += "No significant gainers today.\n"
    
    md_content += "\n#### Losers\n"
    if portfolio_analysis.get('losers'):
        md_content += """
| Symbol | Price | Change |
| ------ | ----: | -----: |
"""
        for pos in portfolio_analysis.get('losers'):
            md_content += f"| {pos.get('symbol')} | ${pos.get('price', 0)::.2f} | {pos.get('change_percent', 0):.2f}% |\n"
    else:
        md_content += "No significant losers today.\n"
    
    # Add Discord activity
    sentiment_analysis = extract_sentiment_from_messages(messages_df)
    
    md_content += "\n## Discord Activity\n"
    md_content += f"- Overall sentiment: {sentiment_analysis.get('overall_sentiment', 'neutral')}\n"
    md_content += f"- Message count: {sentiment_analysis.get('message_count', 0)} market-related messages\n"
    
    # Most mentioned tickers
    recent_tickers = sentiment_analysis.get('recent_tickers', [])
    if recent_tickers:
        md_content += f"- Most discussed tickers: {', '.join(recent_tickers)}\n"
    
    # Add ticker mentions
    ticker_mentions = sentiment_analysis.get('ticker_mentions', {})
    if ticker_mentions:
        md_content += "\n### Ticker Mentions\n"
        for ticker, count in ticker_mentions.items():
            md_content += f"- {ticker}: {count} mentions\n"
    
    # Write to file
    with open(output_path, 'w') as f:
        f.write(md_content)
    
    logger.info(f"✅ Markdown journal saved to {output_path}")
    return output_path

#############################################################
# COMMAND-LINE INTERFACE
#############################################################

if __name__ == "__main__":
    # Create a command-line interface for more flexible usage
    parser = argparse.ArgumentParser(description="Generate portfolio journal entries based on trading data and Discord sentiment")
    parser.add_argument("--positions", "-p", type=str, help="Path to positions CSV file (default: data/raw/positions.csv)")
    parser.add_argument("--discord", "-d", type=str, help="Path to Discord messages CSV file (default: data/raw/discord_msgs.csv)")
    parser.add_argument("--prices", "-pr", type=str, help="Path to prices CSV file (default: data/raw/prices.csv)")
    parser.add_argument("--output", "-o", type=str, help="Directory to save journal entries (default: data/processed)")
    
    args = parser.parse_args()
    
    # Set paths based on arguments or use defaults
    positions_path = args.positions if args.positions else POSITIONS_CSV
    discord_path = args.discord if args.discord else DISCORD_CSV
    prices_path = args.prices if args.prices else PRICES_CSV
    output_dir = Path(args.output) if args.output else PROCESSED_DIR
    
    # Generate the journal
    journal_entry = generate_portfolio_journal(
        positions_path=positions_path,
        discord_path=discord_path,
        prices_path=prices_path,
        output_dir=output_dir
    )
    
    if journal_entry:
        logger.info("✅ Journal generation completed successfully")
    else:
        logger.error("❌ Journal generation failed")

# CLI Usage Examples:
# 1. Standard usage with default file paths:
#    python -m src.journal_generator
#
# 2. Custom positions file:
#    python -m src.journal_generator --positions my_positions.csv
#
# 3. Custom output directory:
#    python -m src.journal_generator --output ./custom_journals
#
# 4. All custom paths:
#    python -m src.journal_generator -p custom_positions.csv -d custom_discord.csv -pr custom_prices.csv -o ./journals
#
# 5. Mix of short and long argument forms:
#    python -m src.journal_generator -p my_positions.csv --discord my_discord.csv