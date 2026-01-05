# Local Argilla Setup

## Quick Start

### Option 1: Docker Quickstart (Simplest)

```bash
docker run -d --name argilla -p 6900:6900 argilla/argilla-quickstart:latest
```

Then access Argilla at: http://localhost:6900

### Option 2: Docker Compose (Recommended for Development)

```bash
cd docker/argilla
docker compose up -d
```

### Option 3: Pull from HF Spaces Registry

```bash
docker run -it -p 7860:7860 --platform=linux/amd64 \
    registry.hf.space/qaisy-qqq-argilla:latest
```

## Default Credentials

| Role      | Username | Password | API Key       |
|-----------|----------|----------|---------------|
| Owner     | owner    | 12345678 | owner.apikey  |
| Admin     | admin    | 12345678 | admin.apikey  |
| Annotator | argilla  | 12345678 | -             |

## Environment Configuration

Set these in your `.env` file for local development:

```bash
ARGILLA_API_URL=http://localhost:6900
ARGILLA_API_KEY=owner.apikey
```

Or for HF Spaces:

```bash
ARGILLA_API_URL=https://qaisy-qqq-argilla.hf.space
ARGILLA_API_KEY=CPk1k9GVhm05AaAPQ5LnHju89rMRQ24ktf8d9TXkP7DtvuurVqET3Gc0SXxGfuC8Z-gjEvzxGak6SF1EuJWogZBhUg_iItezQsq21aFeI7w
```

## Usage with Bootstrap Script

```bash
# Bootstrap the v2 dataset
python scripts/nlp/argilla_bootstrap.py --force

# Push gated chunks for labeling
python scripts/nlp/push_chunks_to_argilla.py --gate-only

# Export labels after annotation
python scripts/nlp/export_argilla_labels.py --to setfit
```

## Verify Connection

```python
import argilla as rg

client = rg.Argilla(
    api_url="http://localhost:6900",
    api_key="owner.apikey"
)
print(f"Connected to Argilla: {client}")
```

## Troubleshooting

### Container won't start
```bash
docker logs argilla-local
```

### Port 6900 already in use
```bash
docker stop argilla-local && docker rm argilla-local
```

### Reset all data
```bash
docker compose down -v
docker compose up -d
```

## Apple Silicon (M1/M2) Users

Add the `--platform` flag:

```bash
docker run -d --name argilla -p 6900:6900 --platform linux/arm64 argilla/argilla-quickstart:latest
```
