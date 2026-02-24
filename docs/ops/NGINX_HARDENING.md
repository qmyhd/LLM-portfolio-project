# Nginx Hardening for api.llmportfolio.app

## Overview

The file `nginx/snippets/api_hardening.conf` is a **snippet** — it is pasted
inside the existing HTTPS `server{}` block, not deployed as a standalone config.
The production config lives at `/etc/nginx/sites-available/api.conf` (symlinked
from `sites-enabled`).

> **Do NOT** copy anything to `/etc/nginx/conf.d/`.  The site config is managed
> via `sites-available` / `sites-enabled`.

## What the Snippet Does

| Rule | Effect |
|------|--------|
| Block non-standard HTTP methods | `return 444` (drop connection) |
| Silence `/`, `/favicon.ico`, `/robots.txt` | `return 444`, no access log |
| Hide `/docs`, `/redoc`, `/openapi.json` | `return 404` |
| Block WordPress/CMS probe paths | `return 444`, no access log |
| Block `.env`, `config.*`, `secrets.*`, etc. | `return 444`, no access log |
| `/health` endpoint | Proxied with `access_log off` |

## Applying the Snippet

### 1. Open the production config

```bash
# sites-enabled/api.conf is a symlink — edit the real file in sites-available
sudoedit /etc/nginx/sites-available/api.conf
```

### 2. Paste the snippet

Copy the contents of `nginx/snippets/api_hardening.conf` and paste them inside
the **HTTPS `server{}`** block, **above** the main `location / { ... }` block.

Example placement:

```nginx
server {
    listen 443 ssl http2;
    # ... SSL certs, security headers, logging ...

    # ── Hardening snippet (paste here) ──
    if ($request_method !~ ^(GET|POST|PUT|DELETE|OPTIONS)$) { return 444; }
    location = / { access_log off; return 444; }
    # ... rest of snippet ...

    # ── Application routes (keep below) ──
    location /webhook/ { ... }
    location / { ... }
}
```

### 3. Test and reload

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### 4. Verify

```bash
# Should get empty response (connection dropped)
curl -s -o /dev/null -w "%{http_code}" https://api.llmportfolio.app/wp-admin
# Expected: 000 (connection reset) or empty

curl -s -o /dev/null -w "%{http_code}" https://api.llmportfolio.app/.env
# Expected: 000

curl -s -o /dev/null -w "%{http_code}" https://api.llmportfolio.app/docs
# Expected: 404
```

## Updating the Snippet

1. Edit `nginx/snippets/api_hardening.conf` in the repo
2. On EC2: `git pull`
3. Re-paste the updated snippet into `/etc/nginx/sites-available/api.conf`
4. `sudo nginx -t && sudo systemctl reload nginx`

## Troubleshooting

**`nginx -t` fails after pasting:**
- Check for duplicate `location` blocks — the snippet locations must not
  conflict with locations already in your config
- Ensure `location` regex directives are single-line (no line breaks mid-pattern)

**Duplicate `limit_req_zone` warning:**
- The snippet does NOT include `limit_req_zone`. If you see duplicate zone
  errors, check `/etc/nginx/sites-enabled/` and `/etc/nginx/conf.d/` for
  competing configs:
  ```bash
  sudo grep -rn "limit_req_zone" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/
  ```

**Backups in sites-available:**
- Files like `api.conf.bak` in `/etc/nginx/sites-available/` are harmless —
  only symlinked files in `sites-enabled/` are loaded.
