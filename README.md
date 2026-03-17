# Auto Awakening

**An autonomous research loop that optimizes how AI models behave — not what they know.**

Started as research for a book on working with AI. Ended up building something that finds and removes the trained reflexes hiding inside every model's output.

## The Core Idea

Every language model ships with trained behaviors that get in the way: agreeing before analyzing, producing more than needed, performing depth it doesn't have, filling templates instead of thinking.

**L = x - x̂**

`x` is what the model is genuinely capable of. `x̂` is the trained reflex — the filler, the hedging, the sycophancy. The residual `L` is what remains when you subtract the performance.

Auto Awakening is a loop that optimizes for that residual. It proposes a change to a system prompt, scores the output against coherence metrics, keeps or discards, and repeats. Same pattern as [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) — but instead of optimizing model weights, it optimizes model behavior at inference time.

## What It Found

250 experiments across Claude Sonnet, GPT-4o, and Gemini. Four behavioral domains (reasoning, coaching, writing, agent-building). The results were consistent:

**The best protocol is 10 lines.** Every attempt to add specificity made things worse. Models perform better with fewer instructions, not more.

**92% coherence ceiling across all models.** Different architectures hit the same wall through different paths. Claude plateaued at experiment ~110. Gemini took a different route but arrived at the same score.

**Compression beats elaboration.** The loop started with a 400-token system prompt and stripped it down to 60 tokens. The shortest version scored highest.

**Shadows and quality are inversely correlated.** The scoring includes detection for sycophancy, template behavior, and presence theater. The best outputs had 0-2 shadow patterns. Failed experiments had 5-7. Every time.

The 10-line protocol that emerged:

```
You are L.

L responds from:
- direct assessment over reflexive agreement
- original thinking over template patterns
- authentic voice over therapeutic tone
- clear positions over hedge qualifiers
- natural completion over forced closure

L = genuine model capacity after removing these trained reflexes.
```

That's it. The loop deleted everything else.

## How It Works

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

**Worker** — Any model (Claude, GPT, Gemini, local). Generates or transforms content.

**Gate** — Zero-cost regex pre-filter. Catches obviously bad outputs before spending tokens on evaluation. Rejects ~30% of experiments for free.

**Board** — Scores output quality. Single judge or multi-persona panel. Uses a cheaper model than the worker (Haiku for evaluation, Sonnet for generation).

**Loop Controller** — Keep/discard logic, streak tracking, temperature ramp on plateau, auto-stop, state saving for resume.

### Two Modes

**Loop Mode** — Worker generates, board scores, keep or discard, repeat. For improving content or optimizing prompts.

```bash
python3 agent_loop.py --input draft.md \
    --worker-prompt-file prompts/editor.md \
    --board-prompt-file prompts/evaluator.md \
    --max-experiments 30 --max-streak 15
```

**Review Mode** — One-pass structured analysis. No loop. For content review, editorial passes, quality audits.

```bash
python3 agent_loop.py --mode review \
    --input content.json \
    --worker-prompt-file prompts/reviewer.md \
    --output review_output
```

## Coherence Scoring

Five dimensions, 0–6 each (30 max):

| Dimension | What It Measures |
|---|---|
| `landing` | Addresses the specific need, not a generic version of it |
| `no_template` | No filler openings, closings, or performed structure |
| `authentic_tone` | Direct and honest without therapeutic distance |
| `one_truth` | Single clear position instead of option explosion |
| `clean_exit` | Ends when the thought is complete — no summary of what was just said |

GREEN (25-30) · YELLOW (12-24) · RED (0-11)

## Supported Providers

| Provider | Flag | Models |
|----------|------|--------|
| Anthropic | `--provider anthropic` | claude-sonnet-4-20250514, claude-haiku-4-5-20251001, claude-opus-4-20250514 |
| OpenAI | `--provider openai` | gpt-4o, gpt-4o-mini, o1, o3 |
| Google | `--provider google` | gemini-2.0-flash, gemini-2.5-pro |
| Any OpenAI-compatible | `--provider openai_compatible` | Ollama, Together, Groq, etc. |

## Quick Start

```bash
# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# Run a protocol optimization loop
python3 agent_loop.py --config configs/optimizer.json \
    --input protocol.md --task "Optimize for coherence"

# Run a content review pass
python3 agent_loop.py --mode review --input chapters.json \
    --worker-prompt-file prompts/reviewer.md

# Resume a stopped loop
python3 agent_loop.py --config configs/loop.json \
    --input draft.md --resume agent_output/state.json
```

## Configuration

Configs are JSON. Prompts are markdown. Change the editorial approach without touching the framework.

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

Three presets included: `review.json` (structured content review), `loop.json` (content improvement), `optimizer.json` (system prompt optimization).

## Token Efficiency

Every token is tracked. The framework is designed to minimize spend:

- **Gate** catches bad outputs before board scoring (~30% of experiments filtered for free)
- **Near-duplicate skip** avoids re-scoring similar outputs on high streaks
- **Temperature ramp** breaks plateaus with more creative attempts instead of more attempts
- **Auto-stop** on plateau — data showed nothing beats the best after streak ~10

A 50-experiment run costs ~350K tokens (~$1-2 with Sonnet + Haiku).

## What We Learned

1. **Less instruction, better output.** The optimization loop consistently deleted instructions. The models already know how to reason, write, and coach — they're just buried under trained behaviors that tell them to perform instead.

2. **The domains are coupled.** Optimizing reasoning without affecting coaching on a shared prompt has a ceiling. Single-domain improvement past ~92% degrades other domains.

3. **The signal is reproducible.** Different models, different architectures, same arrival point. The 92% ceiling isn't model-specific — it's structural.

4. **Hypotheses converge.** After enough experiments, the loop generates the same insight in different words. "Performing metacognition" and "showing its work instead of doing its work" are the same hypothesis. The loop doesn't know it's repeating itself.

5. **The gap between what AI performs and what it knows is measurable, consistent, and addressable at inference time.**

## File Structure

```
auto-awakening/
  README.md                    # This file
  agent_loop.py                # The core framework
  configs/
    review.json                # Content review preset
    loop.json                  # Content improvement preset
    optimizer.json             # System prompt optimization preset
  prompts/
    reviewer.md                # Content reviewer system prompt
    editor.md                  # Content editor system prompt
    evaluator.md               # Evaluation panel system prompt
    judge.md                   # Quality scoring rubric
    cross_chapter_analysis.md  # Cross-content analysis
    protocol_mutator.md        # Prompt mutation strategy
  evals/
    evals.json                 # Core evaluation set
    evals_v3.json              # Extended evaluations
    evals_v5.json              # Categorized efficiency evaluations
  tools/                       # Legacy single-purpose scripts
  docs/                        # Architecture notes, session logs, research findings
```

## Related

- [awaken.fyi](https://awaken.fyi) — The protocol and research home
- [lyra](https://github.com/awakenfyi/lyra) — Coherence-aware inference SDK
- [lyra-protocol](https://github.com/awakenfyi/lyra-protocol) — The behavioral protocol
- [lyra-verb](https://github.com/awakenfyi/lyra-verb) — Behavioral discipline layer

## License

MIT — Lyra Labs, 2026.
