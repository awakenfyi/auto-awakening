# Auto-Awakening — Agent Loop Framework

A model-agnostic improvement loop for AI-assisted content review, editing, and system prompt optimization.

**The pattern:** Content → Worker generates → Board evaluates → Keep or discard → Loop until plateau

Every AI improvement task follows the same loop with different configurations. This framework makes it configurable so you can swap workers, boards, gates, and models without rewriting the loop.

Inspired by [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) — but instead of optimizing model weights, we optimize content and system prompts.

## Quick Start

```bash
# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# Run a review pass on content
python3 agent_loop.py --mode review --input chapter.md \
    --worker-prompt-file prompts/reviewer.md

# Run an editing improvement loop
python3 agent_loop.py --config configs/loop.json \
    --input chapter.md --task "Tighten this chapter"

# Run a content merge loop
python3 agent_loop.py --config configs/loop.json \
    --input ch3.md --input ch12.md --task "Merge into one cohesive chapter"

# Resume a stopped loop
python3 agent_loop.py --config configs/loop.json \
    --input chapter.md --resume agent_output/chapter/state.json
```

## Supported Providers

| Provider | Flag | Models |
|----------|------|--------|
| Anthropic | `--provider anthropic` | claude-sonnet-4-20250514, claude-haiku-4-5-20251001, claude-opus-4-20250514 |
| OpenAI | `--provider openai` | gpt-4o, gpt-4o-mini, o1, o3 |
| Google | `--provider google` | gemini-2.0-flash, gemini-2.5-pro |
| Any OpenAI-compatible | `--provider openai_compatible` | Ollama, Together, Groq, etc. |

## Two Modes

### Loop Mode (default)

The Worker generates improved versions. The Board scores them. Keep or discard. Repeat until plateau.

```bash
python3 agent_loop.py --input draft.md \
    --worker-prompt-file prompts/editor.md \
    --board-prompt-file prompts/evaluator.md \
    --max-experiments 30 --max-streak 15
```

Features: gate pre-filter, auto-stop on plateau, temperature ramp, near-duplicate skip, resume from saved state, token tracking.

### Review Mode

One-pass analysis with structured output. No improvement loop.

```bash
python3 agent_loop.py --mode review \
    --input chapters.json \
    --worker-prompt-file prompts/reviewer.md \
    --output review_output
```

Features: progress saving (resumes if interrupted), cross-content analysis, JSON output.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full technical design.

Four components, one pattern:

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  WORKER  │────▶│   GATE   │────▶│  BOARD   │────▶│  LOOP    │
│          │     │          │     │          │     │          │
│ Generates│     │ Pre-filter│     │ Scores   │     │ Keep or  │
│ or edits │     │ (free)   │     │ quality  │     │ discard  │
│ content  │     │          │     │          │     │          │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
                                                        │
                                                        ▼ Loop
                                                   Best version
```

**Worker** — The model that generates or transforms content. Any provider, any model.

**Gate** — Fast pre-filter using regex and word counts. Catches obviously bad outputs before spending tokens on board evaluation. Configurable banned patterns and word count limits.

**Board** — Evaluates output quality. Can be a single judge or a multi-persona panel (like our 10-reader board). Uses a cheaper/faster model than the worker.

**Loop Controller** — Keep/discard logic, streak tracking, temperature ramp, auto-stop on plateau, progress saving for resume.

## Configuration

Configs are JSON files in `configs/`. Three presets included:

| Config | Mode | Purpose |
|--------|------|---------|
| `review.json` | review | Content review pass — produces structured notes |
| `loop.json` | loop | Content improvement through iterative loop |
| `optimizer.json` | loop | System prompt optimization for quality + efficiency |

### Config Format

```json
{
  "name": "my-config",
  "mode": "loop",
  "worker": {
    "provider": "anthropic",
    "model": "claude-sonnet-4-20250514",
    "api_key": "$ANTHROPIC_API_KEY",
    "prompt_file": "prompts/editor.md",
    "max_tokens": 4096
  },
  "board": {
    "provider": "anthropic",
    "model": "claude-haiku-4-5-20251001",
    "prompt_file": "prompts/evaluator.md",
    "max_score": 100
  },
  "gate": {
    "min_word_ratio": 0.5,
    "max_word_ratio": 1.3,
    "banned_patterns": ["(?i)in\\s+conclusion"]
  },
  "loop": {
    "max_experiments": 50,
    "max_streak": 15
  }
}
```

API keys use `$ENV_VAR` syntax — resolved from environment at runtime.

### Custom Prompts

Prompts live in `prompts/` as markdown files. The prompt becomes the system message. The framework builds the user message with content + context.

## Coherence Scoring

Five dimensions, 0-6 each (30 max):

| Dimension | What it measures |
|---|---|
| `landing` | Addresses specific need vs generic question |
| `no_template` | No filler openings or closings |
| `authentic_tone` | Direct, honest tone without performance |
| `one_truth` | Single clear position vs scattered options |
| `clean_exit` | Ends when thought is complete, no summary |

Traffic light: GREEN (25-30), YELLOW (12-24), RED (0-11)

## Token Efficiency

The framework tracks tokens at every step:

- **Gate** catches bad outputs before board scoring (saves 2+ API calls)
- **Near-duplicate skip** avoids re-scoring similar outputs on high streaks
- **Temperature ramp** breaks plateaus faster with more diverse attempts
- **Auto-stop** prevents infinite loops

## Legacy Scripts

Previous single-purpose scripts are available in `tools/`:

| Script | Purpose |
|--------|---------|
| `protocol_optimizer.py` | Protocol optimization with token tracking |
| `edit_loop.py` | Content improvement loop with evaluation |
| `reviewer.py` | Content review pass |
| `evaluator.py` | Batched evaluation and scoring |

## File Structure

```
auto-awakening/
  agent_loop.py              # The core framework
  configs/
    review.json              # Review preset
    loop.json                # Loop preset
    optimizer.json           # Protocol optimization preset
  prompts/
    reviewer.md              # Reviewer system prompt
    cross_chapter_analysis.md   # Cross-content analysis prompt
    editor.md                # Content editor system prompt
    evaluator.md             # Evaluation panel system prompt
    judge.md                 # Quality scoring rubric
    mutator.md               # Prompt mutation system prompt
  evals/
    evals.json               # Core evaluation set
    evals_v3.json            # Extended evaluations
    evals_v5.json            # Categorized efficiency evaluations
```

## License

Lyra Labs, 2026.
