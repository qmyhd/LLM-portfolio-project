#!/usr/bin/env python
"""
Comprehensive API and environment variable testing script.
Tests all APIs and services used in the LLM Portfolio Project.
"""

import os
import logging
import sys
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger()

def test_environment_variables():
    """Test that all required environment variables are present"""
    logger.info("🔍 Testing Environment Variables...")
    
    # Load environment variables
    load_dotenv()
    
    required_vars = {
        'Discord Bot': [
            'DISCORD_CLIENT_ID',
            'DISCORD_CLIENT_SECRET', 
            'DISCORD_BOT_TOKEN',
            'LOG_CHANNEL_IDS'
        ],
        'SnapTrade/Robinhood': [
            'SNAPTRADE_CLIENT_ID',
            'SNAPTRADE_CONSUMER_KEY',
            'SNAPTRADE_USER_ID',
            'SNAPTRADE_USER_SECRET',
            'ROBINHOOD_ACCOUNT_ID',
            'ROBINHOOD_USERNAME'
        ],
        'Twitter/X API': [
            'TWITTER_API_KEY',
            'TWITTER_API_SECRET_KEY',
            'TWITTER_ACCESS_TOKEN',
            'TWITTER_ACCESS_TOKEN_SECRET',
            'TWITTER_Client_ID',
            'TWITTER_Client_Secret',
            'TWITTER_BEARER_TOKEN'
        ],
        'LLM APIs': [
            'GEMINI_API_KEY',
            'OPENAI_API_KEY'
        ],
        'Optional': [
            'Github_Personal_Access_Token',
            'Polygon_API_KEY'
        ]
    }
    
    results = {}
    for category, vars_list in required_vars.items():
        results[category] = {}
        for var in vars_list:
            value = os.getenv(var)
            if value and value != f"your_{var.lower()}":
                results[category][var] = "✅ Set"
            else:
                results[category][var] = "❌ Missing/Default"
    
    # Print results
    for category, vars_dict in results.items():
        logger.info(f"\n📋 {category}:")
        for var, status in vars_dict.items():
            logger.info(f"  {var}: {status}")
    
    return results

def test_twitter_api():
    """Test Twitter API connection"""
    logger.info("\n🐦 Testing Twitter API...")
    
    try:
        import tweepy
        
        bearer = os.getenv("TWITTER_BEARER_TOKEN")
        if not bearer:
            logger.error("❌ TWITTER_BEARER_TOKEN not found")
            return False
            
        client = tweepy.Client(bearer_token=bearer, wait_on_rate_limit=False)
        resp = client.get_user(username="jack")
        
        if resp.data:  # type: ignore
            logger.info(f"✅ Twitter v2 API working: {resp.data.name} (ID {resp.data.id})")  # type: ignore
            return True
        else:
            logger.error("❌ Twitter API test failed")
            return False
            
    except ImportError:
        logger.error("❌ Tweepy not installed. Install with: pip install tweepy")
        return False
    except Exception as e:
        logger.error(f"❌ Twitter API error: {e}")
        return False

def test_openai_api():
    """Test OpenAI API connection"""
    logger.info("\n🤖 Testing OpenAI API...")
    
    try:
        import openai
        
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or api_key.strip() == "" or api_key == "your_openai_api_key":
            logger.warning("⚠️ OPENAI_API_KEY not configured - skipping test")
            return False
            
        client = openai.OpenAI(api_key=api_key)
        
        # Test with a minimal request
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": "Hello"}],
            max_tokens=5
        )
        
        logger.info("✅ OpenAI API working")
        return True
        
    except Exception as e:
        error_str = str(e)
        # Check for quota exceeded error and skip retries
        if "insufficient_quota" in error_str.lower() or "quota" in error_str.lower():
            logger.warning("⚠️ OpenAI API quota exceeded - use Gemini as primary LLM")
            return False
        else:
            logger.error(f"❌ OpenAI API error: {e}")
            return False

def test_gemini_api():
    """Test Google Gemini API connection"""
    logger.info("\n🔮 Testing Google Gemini API...")
    
    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.error("❌ GEMINI_API_KEY not found")
            return False
            
        # Test Gemini API with a simple request
        import requests
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        
        data = {
            "contents": [{
                "parts": [{
                    "text": "Hello"
                }]
            }],
            "generationConfig": {
                "maxOutputTokens": 5
            }
        }
        
        response = requests.post(url, json=data)
        
        if response.status_code == 200:
            logger.info("✅ Gemini API working")
            return True
        else:
            logger.error(f"❌ Gemini API error: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Gemini API error: {e}")
        return False

def test_snaptrade_api():
    """Test SnapTrade API connection"""
    logger.info("\n📈 Testing SnapTrade API...")
    
    try:
        from snaptrade_client import SnapTrade
        
        client_id = os.getenv("SNAPTRADE_CLIENT_ID")
        consumer_key = os.getenv("SNAPTRADE_CONSUMER_KEY")
        user_id = os.getenv("SNAPTRADE_USER_ID")
        user_secret = os.getenv("SNAPTRADE_USER_SECRET")
        
        if not all([client_id, consumer_key, user_id, user_secret]):
            logger.error("❌ SnapTrade credentials missing")
            return False
            
        snaptrade = SnapTrade(
            client_id=client_id,
            consumer_key=consumer_key
        )
        
        # Test connection by getting user accounts
        accounts = snaptrade.account_information.list_user_accounts(
            user_id=user_id,
            user_secret=user_secret
        )
        
        if hasattr(accounts, 'body') and accounts.body:
            logger.info("✅ SnapTrade API working - Found accounts")
            return True
        else:
            logger.warning("⚠️ SnapTrade API connected but no accounts found")
            return True
            
    except Exception as e:
        logger.error(f"❌ SnapTrade API error: {e}")
        return False

def test_discord_bot_config():
    """Test Discord bot configuration"""
    logger.info("\n🤖 Testing Discord Bot Configuration...")
    
    try:
        import discord
        
        token = os.getenv("DISCORD_BOT_TOKEN")
        client_id = os.getenv("DISCORD_CLIENT_ID")
        channel_ids = os.getenv("LOG_CHANNEL_IDS")
        
        if not token:
            logger.error("❌ DISCORD_BOT_TOKEN missing")
            return False
            
        if not client_id:
            logger.error("❌ DISCORD_CLIENT_ID missing")
            return False
            
        if not channel_ids:
            logger.error("❌ LOG_CHANNEL_IDS missing")
            return False
            
        # Validate channel IDs format
        try:
            channel_list = [int(ch.strip()) for ch in channel_ids.split(',') if ch.strip()]
            logger.info(f"✅ Discord configuration valid - Monitoring {len(channel_list)} channels")
            return True
        except ValueError:
            logger.error("❌ LOG_CHANNEL_IDS contains invalid channel ID format")
            return False
            
    except Exception as e:
        logger.error(f"❌ Discord configuration error: {e}")
        return False

def test_data_directories():
    """Test that all required data directories exist"""
    logger.info("\n📁 Testing Data Directories...")
    
    from pathlib import Path
    
    base_dir = Path(__file__).parent
    required_dirs = [
        base_dir / "data" / "raw",
        base_dir / "data" / "processed", 
        base_dir / "data" / "database"
    ]
    
    all_exist = True
    for dir_path in required_dirs:
        if dir_path.exists():
            logger.info(f"✅ {dir_path.relative_to(base_dir)}")
        else:
            logger.error(f"❌ {dir_path.relative_to(base_dir)} missing")
            all_exist = False
            
    return all_exist

def test_core_imports():
    """Test that all core modules can be imported"""
    logger.info("\n📦 Testing Core Module Imports...")
    
    modules_to_test = [
        'src.data_collector',
        'src.journal_generator', 
        'src.database',
        'src.bot',
        'src.bot.events'
    ]
    
    success_count = 0
    for module in modules_to_test:
        try:
            __import__(module)
            logger.info(f"✅ {module}")
            success_count += 1
        except Exception as e:
            logger.error(f"❌ {module}: {e}")
    
    return success_count == len(modules_to_test)

def main():
    """Run all tests"""
    logger.info("🚀 Starting comprehensive API and configuration tests...")
    
    test_results = {}
    
    # Run all tests (Gemini first as primary LLM)
    test_results['Environment Variables'] = test_environment_variables()
    test_results['Data Directories'] = test_data_directories()
    test_results['Core Imports'] = test_core_imports()
    test_results['Twitter API'] = test_twitter_api()
    test_results['Gemini API (Primary)'] = test_gemini_api()
    test_results['OpenAI API (Fallback)'] = test_openai_api()
    test_results['SnapTrade API'] = test_snaptrade_api()
    test_results['Discord Config'] = test_discord_bot_config()
    
    # Summary
    logger.info("\n" + "="*50)
    logger.info("📊 TEST SUMMARY")
    logger.info("="*50)
    
    passed = 0
    total = 0
    
    for test_name, result in test_results.items():
        if test_name == 'Environment Variables':
            continue  # Skip env vars in pass/fail count
            
        total += 1
        if result:
            logger.info(f"✅ {test_name}")
            passed += 1
        else:
            logger.info(f"❌ {test_name}")
    
    logger.info(f"\n🎯 Overall: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All systems ready!")
        return True
    else:
        logger.warning("⚠️ Some tests failed - check configuration")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
