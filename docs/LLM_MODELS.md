# LLM Portfolio Journal - LLM Model Strategy

> **Last Updated:** February 5, 2026  
> **Purpose:** Document the model selection strategy for NLP parsing and AI features

## Overview

The LLM Portfolio Journal uses a tiered model strategy to balance cost, latency, and quality across different NLP tasks. Models are routed based on message complexity, token count, and task requirements.

## Model Tiers

### Tier 1: Quick Triage (`gpt-5-nano`)

**Use Case:** Initial message classification and triage  
**Environment Variable:** `OPENAI_MODEL_TRIAGE`  
**Fallback:** `gpt-4o-mini`

- Ultra-fast initial classification
- Determines if message contains actionable trading ideas
- Routes to appropriate main model based on complexity
- Lowest cost per token

```python
# Example: Quick triage decision
# "just bought AAPL" → classify as trading idea → route to main model
# "good morning everyone" → classify as social → skip parsing
```

### Tier 2: Main Parsing (`gpt-5-mini`)

**Use Case:** Standard message parsing and summaries  
**Environment Variables:** `OPENAI_MODEL_MAIN`, `OPENAI_MODEL_SUMMARY`  
**Fallback:** `gpt-4o-mini`

- Primary workhorse for idea extraction
- Handles 80%+ of messages
- Structured output extraction (symbols, labels, levels, direction)
- Good balance of quality and cost

**Capabilities:**
- Extract trading symbols (e.g., `$AAPL`, `$MSFT`)
- Identify trading labels (SWING, SCALP, MOMENTUM, etc.)
- Parse price levels (entry, target, stop-loss)
- Determine trade direction (LONG, SHORT, NEUTRAL)
- Calculate confidence scores

### Tier 3: Escalation & Long Context (`gpt-5.1`)

**Use Case:** Complex messages, high symbol density, long content  
**Environment Variables:** `OPENAI_MODEL_ESCALATION`, `OPENAI_MODEL_LONG`  
**Fallback:** `gpt-4o`

Triggers when:
- Token count > `OPENAI_LONG_CONTEXT_THRESHOLD_TOKENS` (default: 500)
- Character count > `OPENAI_LONG_CONTEXT_THRESHOLD_CHARS` (default: 2000)
- High symbol density (5+ tickers in one message)
- Complex multi-idea messages
- Low confidence from main model (< `OPENAI_ESCALATION_THRESHOLD`, default: 0.8)

**Capabilities:**
- Better reasoning for ambiguous content
- More accurate multi-idea extraction
- Handles nested/complex trading setups
- Higher quality for edge cases

### Tier 4: Extremely Long Context (`gpt-4.1`)

**Use Case:** Very long messages, batch summaries, complex analysis  
**Environment Variable:** Custom routing logic  
**Fallback:** `gpt-4o`

Reserved for:
- Messages exceeding 8K tokens
- Full-document analysis
- Batch result aggregation
- Research synthesis

### Tier 5: Journal Generation (`gemini-1.5-flash`)

**Use Case:** Daily journal entry generation  
**Environment Variable:** `GEMINI_API_KEY`  
**Fallback:** `gpt-4o-mini`

- Free tier available (cost optimization)
- Long context window (1M tokens)
- Good for summarization tasks
- Used for daily portfolio journal entries

```python
# Example: Journal entry from day's trading ideas
# Input: All parsed ideas from the day
# Output: Formatted journal entry with key themes, patterns, P&L summary
```

## Model Routing Logic

```
┌─────────────────┐
│  Discord Msg    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐     No      ┌─────────────────┐
│   Quick Triage  │───────────▶│   Skip Parsing  │
│   (gpt-5-nano)  │             └─────────────────┘
└────────┬────────┘
         │ Yes (contains ideas)
         ▼
┌─────────────────┐
│  Check Length   │
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
 Short      Long (>500 tokens)
    │         │
    ▼         ▼
┌─────────┐ ┌─────────┐
│Main     │ │Long Ctx │
│gpt-5-   │ │gpt-5.1  │
│mini     │ └────┬────┘
└────┬────┘      │
     │           │
     ▼           │
┌─────────────┐  │
│ Confidence  │  │
│  Check      │  │
└────┬────────┘  │
     │           │
 <0.8│   ≥0.8   │
     │     │     │
     ▼     │     │
┌─────────┐│     │
│Escalate ││     │
│gpt-5.1  │◀─────┘
└────┬────┘
     │
     ▼
┌─────────────────┐
│  Final Ideas    │
└─────────────────┘
```

## Environment Configuration

### Required API Keys

```bash
# Primary: OpenAI API (required)
OPENAI_API_KEY=sk-...

# Optional: Google Gemini (for journal generation)
GEMINI_API_KEY=AIza...
```

### Model Routing Variables

```bash
# Triage model (first pass classification)
OPENAI_MODEL_TRIAGE=gpt-5-nano

# Main parsing model (standard messages)
OPENAI_MODEL_MAIN=gpt-5-mini

# Escalation model (complex/ambiguous)
OPENAI_MODEL_ESCALATION=gpt-5.1

# Long context model (>500 tokens)
OPENAI_MODEL_LONG=gpt-5.1

# Summary model (batch summaries)
OPENAI_MODEL_SUMMARY=gpt-5-mini
```

### Routing Thresholds

```bash
# Token threshold for long context routing
OPENAI_LONG_CONTEXT_THRESHOLD_TOKENS=500

# Character threshold for long context routing
OPENAI_LONG_CONTEXT_THRESHOLD_CHARS=2000

# Confidence threshold for escalation
OPENAI_ESCALATION_THRESHOLD=0.8
```

### Quality Controls

```bash
# Temperature (lower = more deterministic)
OPENAI_TEMPERATURE=0.1

# Max output tokens
OPENAI_MAX_OUTPUT_TOKENS=3500

# Reasoning effort for main model
OPENAI_REASONING_EFFORT_MAIN=medium

# Reasoning effort for escalation
OPENAI_REASONING_EFFORT_ESCALATION=medium
```

## Fallback Chain

If a model is unavailable or rate-limited:

1. **gpt-5-nano** → `gpt-4o-mini` → `gpt-3.5-turbo`
2. **gpt-5-mini** → `gpt-4o-mini` → `gpt-4-turbo`
3. **gpt-5.1** → `gpt-4o` → `gpt-4-turbo`
4. **gemini-1.5-flash** → `gpt-4o-mini`

## Cost Optimization

### Batch API (50% Discount)

For non-real-time processing, use OpenAI Batch API:

```bash
# Batch completion window (24h recommended)
OPENAI_BATCH_COMPLETION_WINDOW=24h

# Poll interval for batch status
OPENAI_BATCH_POLL_SECONDS=15

# Max requests per batch
OPENAI_BATCH_MAX_REQUESTS=20000
```

Batch pipeline: `scripts/nlp/batch_backfill.py`

### Cost Per Task (Estimated)

| Task | Model | Tokens (avg) | Cost/1K msgs |
|------|-------|--------------|--------------|
| Triage | gpt-5-nano | ~100 | ~$0.02 |
| Main Parse | gpt-5-mini | ~800 | ~$0.40 |
| Escalation | gpt-5.1 | ~1500 | ~$1.50 |
| Journal | gemini-flash | ~2000 | Free tier |

## Monitoring

Check model usage in OpenAI dashboard:
- Usage by model
- Token consumption
- Error rates
- Latency percentiles

Local logging includes:
- Model routing decisions
- Confidence scores
- Escalation triggers
- Batch job status

## Future Considerations

1. **Local Models**: Ollama/LMStudio for sensitive data or offline use
2. **Fine-tuning**: Custom model for trading terminology
3. **Anthropic Claude**: Alternative for complex reasoning tasks
4. **Multi-modal**: Image analysis for chart screenshots

---

*See [ARCHITECTURE.md](ARCHITECTURE.md) for full system documentation.*
