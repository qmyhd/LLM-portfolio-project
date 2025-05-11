# check_twitter_api.py
import os
import logging
import tweepy
from dotenv import load_dotenv

# ——— Logging setup —————————————————————————————————————————————————
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger()

# ——— Load env vars —————————————————————————————————————————————————
load_dotenv()
BEARER         = os.getenv("TWITTER_BEARER_TOKEN")
API_KEY        = os.getenv("TWITTER_API_KEY")
API_SECRET     = os.getenv("TWITTER_API_SECRET_KEY")
ACCESS_TOKEN   = os.getenv("TWITTER_ACCESS_TOKEN")
ACCESS_SECRET  = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")

# ——— v2 Bearer Token test —————————————————————————————————————————————
if not BEARER:
    logger.error("🔴 No TWITTER_BEARER_TOKEN in .env – aborting v2 test")
else:
    try:
        client = tweepy.Client(bearer_token=BEARER, wait_on_rate_limit=False)
        resp = client.get_user(username="jack")  # jack is a known, active account
        if resp.data:
            logger.info(f"🟢 v2 Bearer works: {resp.data.username} (ID {resp.data.id})")
        else:
            logger.error(f"🔴 v2 Bearer returned no data. Errors: {resp.errors}")
    except Exception as e:
        logger.error(f"🔴 v2 Bearer error: {e}")

# ——— v1.1 OAuth1 test ————————————————————————————————————————————————
if None in (API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_SECRET):
    logger.warning("⚠️ Missing one or more v1.1 creds – skipping OAuth1 test")
else:
    try:
        auth = tweepy.OAuth1UserHandler(
            API_KEY, API_SECRET,
            ACCESS_TOKEN, ACCESS_SECRET
        )
        api = tweepy.API(auth, wait_on_rate_limit=False)
        me = api.verify_credentials()
        logger.info(f"🟢 v1.1 OAuth works: @{me.screen_name}")
    except Exception as e:
        logger.error(f"🔴 v1.1 OAuth error: {e}")