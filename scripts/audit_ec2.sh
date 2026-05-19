#!/usr/bin/env bash
# audit_ec2.sh — Read-only thorough audit of the LLM Portfolio EC2 environment.
#
# Output is structured with === SECTION === markers. Pipe to a file and share back:
#   bash scripts/audit_ec2.sh > /tmp/audit.txt 2>&1
#   cat /tmp/audit.txt
#
# Safe to run: no writes, no service restarts, no destructive ops.

set +e  # keep going even if a section fails
export PYTHONUNBUFFERED=1

ENV_FILE="/etc/llm-portfolio/llm.env"
VENV_PY=".venv/bin/python"
REPO_DIR="/home/ubuntu/llm-portfolio"

cd "$REPO_DIR" 2>/dev/null || { echo "FATAL: repo not at $REPO_DIR"; exit 1; }

if [[ -f "$ENV_FILE" ]]; then
  set -a; source "$ENV_FILE"; set +a
fi

API_BASE="${API_BASE:-http://127.0.0.1:8000}"
AUTH_HEADER="Authorization: Bearer ${API_SECRET_KEY:-}"

banner() { echo ""; echo "=== $1 ==="; }

banner "META"
echo "host: $(hostname)"
echo "date: $(date -Iseconds)"
echo "uptime: $(uptime)"
echo "repo head: $(git -C "$REPO_DIR" log -1 --oneline)"
echo "branch: $(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD)"

banner "DISK_MEM"
df -h / /tmp /var 2>/dev/null | head -10
echo ""
free -h

banner "SERVICES"
for svc in api.service discord-bot.service nightly-pipeline.timer nightly-pipeline.service nginx; do
  state=$(systemctl is-active "$svc" 2>/dev/null)
  enabled=$(systemctl is-enabled "$svc" 2>/dev/null)
  printf "  %-30s active=%-10s enabled=%s\n" "$svc" "$state" "$enabled"
done

banner "API_HEALTH"
curl -sS --max-time 5 "$API_BASE/health" | head -c 400
echo ""

banner "API_KEY_PRESENT"
if [[ -n "${API_SECRET_KEY:-}" ]]; then echo "yes (len=${#API_SECRET_KEY})"; else echo "NO — auth'd endpoints will fail"; fi

banner "API_PROBES"
probe() {
  local path="$1"
  local label="$2"
  local code body
  code=$(curl -sS -o /tmp/_body --max-time 15 -w "%{http_code}" -H "$AUTH_HEADER" "$API_BASE$path")
  body=$(head -c 600 /tmp/_body)
  printf "%-45s %s\n" "[$code] $label" "${body//$'\n'/ }"
  echo ""
}
probe "/portfolio/positions"            "positions"
probe "/portfolio/movers?limit=5"       "movers"
probe "/orders?limit=5"                 "orders recent"
probe "/activities?limit=5"             "activities recent"
probe "/trades/recent?limit=5&days=30"  "recent trades feed"
probe "/ideas?limit=5"                  "ideas"
probe "/connections"                    "connections"
probe "/watchlist"                      "watchlist"
probe "/sentiment?limit=5"              "sentiment"
probe "/search?q=AAPL"                  "search AAPL"
probe "/stocks/AAPL"                    "stock profile AAPL"
probe "/stocks/AAPL/ohlcv?days=5"       "AAPL OHLCV 5d"
probe "/stocks/AAPL/trades?limit=5"     "AAPL trades"
probe "/stocks/AAPL/ideas?limit=5"      "AAPL ideas"
probe "/stocks/AAPL/news?limit=3"       "AAPL news"
probe "/stocks/AAPL/fundamentals"       "AAPL fundamentals"
probe "/stocks/AAPL/filings?limit=3"    "AAPL filings"
probe "/stocks/AAPL/analysis"           "AAPL multi-agent analysis (cached)"
probe "/portfolio/risk"                 "portfolio risk"

banner "DB_TABLE_COUNTS_AND_FRESHNESS"
$VENV_PY - <<'PY' 2>&1
import sys
sys.path.insert(0, '.')
from src.env_bootstrap import bootstrap_env
bootstrap_env()
from src.db import execute_sql

TABLES = [
    ("discord_messages",        "sent_at"),
    ("discord_parsed_ideas",    "created_at"),
    ("ohlcv_daily",             "ts_event"),
    ("positions",               "updated_at"),
    ("orders",                  "time_executed"),
    ("accounts",                "updated_at"),
    ("account_balances",        "updated_at"),
    ("activities",              "trade_date"),
    ("user_ideas",              "created_at"),
    ("twitter_data",            "created_at"),
    ("stock_profile_current",   "updated_at"),
    ("stock_notes",             "created_at"),
    ("discord_ingest_cursors",  "updated_at"),
    ("stock_analysis_cache",    "created_at"),
    ("portfolio_risk_cache",    "created_at"),
    ("position_snapshots",      "as_of_date"),
]
print(f"{'table':28} {'rows':>10} {'latest':28}")
for t, ts_col in TABLES:
    try:
        rows = execute_sql(f"SELECT COUNT(*) AS n FROM {t}", fetch_results=True)
        n = rows[0]._mapping["n"] if rows else 0
        latest = "-"
        if n > 0 and ts_col:
            r2 = execute_sql(f"SELECT MAX({ts_col}) AS m FROM {t}", fetch_results=True)
            if r2 and r2[0]._mapping["m"] is not None:
                latest = str(r2[0]._mapping["m"])[:26]
        print(f"{t:28} {n:>10} {latest:28}")
    except Exception as e:
        print(f"{t:28} ERROR {type(e).__name__}: {str(e)[:80]}")
PY

banner "POSITIONS_SANITY"
$VENV_PY - <<'PY' 2>&1
import sys; sys.path.insert(0, '.')
from src.env_bootstrap import bootstrap_env; bootstrap_env()
from src.db import execute_sql
rows = execute_sql("""
  SELECT acc.name AS account, COUNT(*) AS positions,
         SUM(p.quantity * COALESCE(p.current_price, p.price)) AS mv,
         MAX(p.updated_at) AS last_update,
         COALESCE(acc.connection_status,'connected') AS status
  FROM positions p
  JOIN accounts acc ON acc.id = p.account_id
  WHERE p.quantity > 0
  GROUP BY acc.name, acc.connection_status
  ORDER BY mv DESC NULLS LAST
""", fetch_results=True) or []
for r in rows:
    m = r._mapping
    print(f"  {m['account'][:25]:25} pos={m['positions']:>3} mv=${float(m['mv'] or 0):>12,.2f} status={m['status']} last={str(m['last_update'])[:19]}")

print("\nTop 10 by market value:")
rows = execute_sql("""
  SELECT p.symbol,
         SUM(p.quantity) AS qty,
         AVG(p.average_buy_price) AS avg_cost,
         AVG(COALESCE(p.current_price, p.price)) AS px,
         SUM(p.quantity * COALESCE(p.current_price, p.price)) AS mv
  FROM positions p
  JOIN accounts acc ON acc.id = p.account_id
  WHERE p.quantity > 0
    AND COALESCE(acc.connection_status,'connected') != 'deleted'
  GROUP BY p.symbol
  ORDER BY mv DESC NULLS LAST
  LIMIT 10
""", fetch_results=True) or []
for r in rows:
    m = r._mapping
    print(f"  {m['symbol']:8} qty={float(m['qty']):>10,.4f} avg=${float(m['avg_cost'] or 0):>8,.2f} px=${float(m['px'] or 0):>8,.2f} mv=${float(m['mv'] or 0):>12,.2f}")

print("\nPositions with NULL/zero current_price:")
rows = execute_sql("""
  SELECT p.symbol, p.quantity, p.average_buy_price, p.current_price, p.price, acc.name AS acct
  FROM positions p JOIN accounts acc ON acc.id = p.account_id
  WHERE p.quantity > 0
    AND COALESCE(acc.connection_status,'connected') != 'deleted'
    AND (p.current_price IS NULL OR p.current_price = 0)
    AND (p.price IS NULL OR p.price = 0)
  LIMIT 20
""", fetch_results=True) or []
print(f"  count: {len(rows)}")
for r in rows[:10]:
    m = r._mapping
    print(f"  {m['symbol']:8} qty={float(m['quantity']):>10,.4f} acct={m['acct']}")
PY

banner "OHLCV_FRESHNESS"
$VENV_PY - <<'PY' 2>&1
import sys; sys.path.insert(0, '.')
from src.env_bootstrap import bootstrap_env; bootstrap_env()
from src.db import execute_sql
rows = execute_sql("""
  SELECT symbol, MAX(ts_event) AS last_bar, COUNT(*) AS bars
  FROM ohlcv_daily
  WHERE symbol IN (
    SELECT DISTINCT symbol FROM positions p
    JOIN accounts acc ON acc.id = p.account_id
    WHERE p.quantity > 0 AND COALESCE(acc.connection_status,'connected') != 'deleted'
  )
  GROUP BY symbol
  ORDER BY last_bar ASC NULLS FIRST
  LIMIT 30
""", fetch_results=True) or []
print(f"  {'symbol':10} {'last_bar':28} {'bars':>10}")
for r in rows:
    m = r._mapping
    print(f"  {m['symbol']:10} {str(m['last_bar'])[:26]:28} {m['bars']:>10}")
PY

banner "IDEAS_BACKLOG"
$VENV_PY - <<'PY' 2>&1
import sys; sys.path.insert(0, '.')
from src.env_bootstrap import bootstrap_env; bootstrap_env()
from src.db import execute_sql
r = execute_sql("""
  SELECT
    (SELECT COUNT(*) FROM discord_messages WHERE created_at > NOW() - INTERVAL '7 days') AS msgs_7d,
    (SELECT COUNT(*) FROM discord_parsed_ideas WHERE created_at > NOW() - INTERVAL '7 days') AS ideas_7d,
    (SELECT COUNT(*) FROM discord_messages dm
       WHERE NOT EXISTS (SELECT 1 FROM discord_parsed_ideas dpi WHERE dpi.message_id = dm.message_id)
       AND dm.created_at > NOW() - INTERVAL '30 days') AS unparsed_30d,
    (SELECT MAX(created_at) FROM discord_messages) AS last_msg,
    (SELECT MAX(created_at) FROM discord_parsed_ideas) AS last_idea
""", fetch_results=True)
m = r[0]._mapping
print(f"  messages_7d:    {m['msgs_7d']}")
print(f"  parsed_7d:      {m['ideas_7d']}")
print(f"  unparsed_30d:   {m['unparsed_30d']}")
print(f"  last_msg:       {m['last_msg']}")
print(f"  last_idea:      {m['last_idea']}")
PY

banner "TRADES_SANITY"
$VENV_PY - <<'PY' 2>&1
import sys; sys.path.insert(0, '.')
from src.env_bootstrap import bootstrap_env; bootstrap_env()
from src.db import execute_sql
# Activities by type
rows = execute_sql("""
  SELECT UPPER(activity_type) AS type, COUNT(*) AS n, MAX(trade_date) AS latest
  FROM activities GROUP BY UPPER(activity_type) ORDER BY n DESC
""", fetch_results=True) or []
print("Activities by type:")
for r in rows:
    m = r._mapping
    print(f"  {m['type']:15} n={m['n']:>6} latest={m['latest']}")
print()
# Orders by status
rows = execute_sql("""
  SELECT UPPER(status) AS status, COUNT(*) AS n, MAX(time_executed) AS latest
  FROM orders GROUP BY UPPER(status) ORDER BY n DESC
""", fetch_results=True) or []
print("Orders by status:")
for r in rows:
    m = r._mapping
    print(f"  {m['status']:15} n={m['n']:>6} latest={m['latest']}")
print()
# Negative/odd values
rows = execute_sql("""
  SELECT symbol, units, price, amount, activity_type, trade_date
  FROM activities
  WHERE (units < 0 AND UPPER(activity_type) = 'BUY')
     OR (price IS NOT NULL AND price <= 0 AND UPPER(activity_type) IN ('BUY','SELL'))
  LIMIT 20
""", fetch_results=True) or []
print(f"Suspicious activity rows: {len(rows)}")
for r in rows[:5]:
    m = r._mapping
    print(f"  {m['symbol']} {m['activity_type']} units={m['units']} price={m['price']} amount={m['amount']}")
PY

banner "ANALYSIS_CACHE"
$VENV_PY - <<'PY' 2>&1
import sys; sys.path.insert(0, '.')
from src.env_bootstrap import bootstrap_env; bootstrap_env()
from src.db import execute_sql
r = execute_sql("""
  SELECT COUNT(*) AS n, MAX(created_at) AS latest,
         COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') AS fresh_24h
  FROM stock_analysis_cache
""", fetch_results=True)
m = r[0]._mapping
print(f"  stock_analysis_cache:  total={m['n']}  fresh_24h={m['fresh_24h']}  latest={m['latest']}")
r = execute_sql("SELECT COUNT(*) AS n, MAX(created_at) AS latest FROM portfolio_risk_cache", fetch_results=True)
m = r[0]._mapping
print(f"  portfolio_risk_cache:  total={m['n']}  latest={m['latest']}")
PY

banner "ACCOUNTS"
$VENV_PY - <<'PY' 2>&1
import sys; sys.path.insert(0, '.')
from src.env_bootstrap import bootstrap_env; bootstrap_env()
from src.db import execute_sql
rows = execute_sql("""
  SELECT id, name, brokerage_authorization, COALESCE(connection_status,'connected') AS status,
         created_at, updated_at, sync_status
  FROM accounts ORDER BY updated_at DESC
""", fetch_results=True) or []
for r in rows:
    m = r._mapping
    print(f"  {m['name'][:30]:30} status={m['status']:12} sync={m['sync_status']} updated={str(m['updated_at'])[:19]}")
PY

banner "API_SERVICE_LOG_TAIL"
journalctl -u api.service -n 80 --no-pager 2>/dev/null | tail -80

banner "BOT_SERVICE_LOG_TAIL"
journalctl -u discord-bot.service -n 60 --no-pager 2>/dev/null | tail -60

banner "NIGHTLY_PIPELINE_LOG_TAIL"
journalctl -u nightly-pipeline.service -n 120 --no-pager 2>/dev/null | tail -120

banner "NGINX_ERROR_LOG"
sudo tail -n 40 /var/log/nginx/error.log 2>/dev/null || tail -n 40 /var/log/nginx/error.log 2>/dev/null

banner "WEBHOOK_RECENT"
journalctl -u api.service --since "24 hours ago" 2>/dev/null | grep -i "webhook" | tail -40

banner "RECENT_5XX_FROM_API"
journalctl -u api.service --since "48 hours ago" 2>/dev/null | grep -iE "500 |502 |traceback|exception|ERROR" | tail -60

echo ""
echo "=== AUDIT_COMPLETE ==="
