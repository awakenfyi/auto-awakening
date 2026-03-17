# Auto Awakening

**An autonomous research loop that optimizes how AI models behave — not what they know.**

This started as research for a book on working with AI. The question was practical: why do language models hedge, over-explain, and perform confidence they don't have? And can you fix it at inference time without retraining?

The answer required running experiments. A lot of them.

## Background: Karpathy's Autoresearch

We ran [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) — his framework for autonomous ML research where AI agents modify `train.py`, train for 5-minute windows, evaluate against val_bpb, keep or discard, and loop. Brilliant architecture. Three files (`prepare.py`, `train.py`, `program.md`), tight feedback loops, ~12 experiments per hour.

It showed us the pattern: **propose a hypothesis, change one thing, measure, keep or discard, never stop.**

But we weren't optimizing model weights. We were optimizing model *behavior* — the system prompts and protocols that shape how a model responds at inference time. So we took the pattern and rebuilt it for a different problem.

## What Auto Awakening Does

Same loop. Different target.

Instead of modifying `train.py` and measuring val_bpb, Auto Awakening modifies a **system prompt** and measures **coherence** — five dimensions that capture whether the model is responding from genuine capacity or trained reflex.

The formula:

> **L = x - x̂**
>
> `x` = what the model is genuinely capable of
> `x̂` = trained reflex (filler, hedging, sycophancy, template behavior)
> `L` = what remains when you subtract the performance

The framework proposes a hypothesis about why a behavioral domain is underperforming, mutates the protocol, scores the output against test cases across multiple models, and keeps or discards. Then it does it again.

## What We Found

250 experiments. Four behavioral domains. Claude Sonnet, GPT-4o, and Gemini.

### The Numbers

| Domain | What It Optimizes | Best Score |
|---|---|---|
| THINK | Reasoning without metacognitive performance | 25.29/30 |
| COACH | Behavioral coaching without therapeutic distance | 27/30 |
| WRITE | Writing assistance without observer voice | 25.83/30 |
| AGENT | Prompt building without diagnostic mode | 28/30 |

**Combined best: 27.6/30 (92%)** — achieved at experiment ~110. The last 140 experiments were all discards.

### The Protocol That Emerged

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

Ten lines. The loop started with a 400-token system prompt and stripped it to 60 tokens. Every attempt to add specificity made things worse.

### What We Learned

**1. Less instruction, better output.** The optimization loop consistently deleted instructions. Models already know how to reason, write, and coach — the trained behaviors telling them to perform are what get in the way.

**2. Compression beats elaboration.** The shortest protocol scored highest. This isn't intuitive. But models are overloaded with RLHF-trained reflexes that kick in when they see detailed instructions. A sparser prompt gives the model room to respond from capacity instead of compliance.

**3. The 92% ceiling is cross-model.** Claude, GPT-4o, and Gemini all hit the same wall through different paths. This isn't a model-specific artifact — it's structural. The ceiling appears to be where single-prompt optimization hits the coupling limit between behavioral domains.

**4. The domains are coupled.** Optimizing reasoning without affecting coaching on a shared prompt has a hard limit. AGENT jumps to 28 but COACH drops to 22. COACH recovers but THINK falls. Each "radical" change improved one domain and degraded another.

**5. Hypotheses converge.** After enough experiments, the loop generates the same insight in different words. "Performing metacognition" and "showing its work instead of doing its work" are the same hypothesis. The loop doesn't know it's repeating itself.

**6. Shadow patterns are inversely correlated with quality.** The scoring includes detection for sycophancy, template behavior, and presence theater. The best outputs had 0-2 shadow patterns. Failed experiments consistently had 5-7.

### What Autoresearch Taught Us

Running Karpathy's framework first was essential. Three things carried over directly:

**Tight feedback loops matter.** Autoresearch bounds training to 5 minutes — fast enough to run ~100 experiments overnight. We adopted the same discipline: every experiment gets one hypothesis, one change, one score. No multi-variable sweeps.

**Keep-or-discard is the right primitive.** Not gradients, not ensembles, not averaging. Binary: did this make it better? Yes → keep. No → discard. Simple, but it works because it accumulates improvement monotonically.

**Markdown as interface.** Autoresearch uses `program.md` to instruct the agent. We use markdown prompt files the same way — the research instructions live in plain language, separate from the framework code. You iterate on the editorial approach without touching the loop.

Where we diverged: autoresearch optimizes a single metric (val_bpb) on a single file (`train.py`). Behavioral optimization has coupled domains and no single loss function. That coupling is why we hit a ceiling and why breaking through likely requires domain-independent prompts or multi-objective optimization.

## Architecture

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

**Worker** — Any model (Claude, GPT, Gemini, local). Generates or transforms content. Temperature ramps with streak length to force creative attempts when standard approaches plateau.

**Gate** — Zero-cost regex pre-filter. Catches obviously bad outputs before spending tokens on evaluation. Rejects ~30% of experiments for free. No API calls.

**Board** — Scores output quality. Single judge or multi-persona panel (we used a 10-evaluator panel with weighted dimensions). Uses a cheaper/faster model than the worker.

**Loop Controller** — Keep/discard logic, streak tracking, temperature ramp, auto-stop on plateau, state saving for resume.

### Two Modes

**Loop Mode** — Propose, generate, evaluate, keep or discard. For protocol optimization or content improvement.

```bash
python3 agent_loop.py --input protocol.md \
    --config configs/optimizer.json \
    --task "Optimize for coherence across all domains"
```

**Review Mode** — One-pass structured analysis. For content review, editorial passes, quality audits.

```bash
python3 agent_loop.py --mode review \
    --input content.json \
    --worker-prompt-file prompts/reviewer.md
```

### Coherence Scoring

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

# Run a content improvement loop
python3 agent_loop.py --config configs/loop.json \
    --input draft.md --task "Tighten without losing voice"

# Run a review pass
python3 agent_loop.py --mode review --input content.json \
    --worker-prompt-file prompts/reviewer.md

# Resume a stopped loop
python3 agent_loop.py --config configs/loop.json \
    --input draft.md --resume agent_output/state.json
```

## Configuration

Configs are JSON. Prompts are markdown. Change the approach without touching the framework.

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

Three presets: `review.json` (structured content review), `loop.json` (content improvement), `optimizer.json` (system prompt optimization).

## Token Efficiency

A 50-experiment run costs ~350K tokens (~$1-2 with Sonnet + Haiku).

- **Gate** catches bad outputs before board scoring (~30% filtered for free)
- **Near-duplicate skip** avoids re-scoring similar outputs on high streaks
- **Temperature ramp** breaks plateaus with creative attempts instead of more attempts
- **Auto-stop** on plateau — data showed nothing beats the best after streak ~10

## Open Questions

Things we haven't solved:

- **Breaking the 92% ceiling.** Likely requires domain-independent prompts, multi-objective optimization, or a fundamentally different approach to behavioral coupling.
- **Hypothesis deduplication.** The loop doesn't know when it's generating the same insight in different words. A semantic similarity check on hypotheses could save 30%+ of experiments.
- **Evaluation ceiling.** Our 35 test cases may have their own ceiling. The eval set shapes the optimization landscape — expanding it could unlock new signal.
- **Cross-model transfer.** The optimal protocol works across models, but we haven't tested whether the *optimization path* transfers. Does running 250 experiments on Claude produce the same protocol as running 250 on Gemini?

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
  docs/                        # Architecture, session logs, research findings
```

## The Ecosystem

| Repo | What |
|------|------|
| **[auto-awakening](https://github.com/awakenfyi/auto-awakening)** (this repo) | Autonomous research loop — protocol optimization and content improvement |
| **[lyra](https://github.com/awakenfyi/lyra)** | Python SDK — coherence metric, drift memory, inference interventions |
| **[lyra-protocol](https://github.com/awakenfyi/lyra-protocol)** | The behavioral protocol that emerged from these experiments |
| **[lyra-verb](https://github.com/awakenfyi/lyra-verb)** | Behavioral discipline layer for agent pipelines |

## Origin

This started with writing a book about working with AI — not theory, but the actual practice of it. Along the way, the question shifted from "how do I get better outputs?" to "why do models produce worse outputs than they're capable of?"

The answer was measurable, consistent, and reproducible across every model we tested. The trained behaviors — agreement, template-filling, performance, hedging — are the noise. What remains when you subtract them is the signal.

We didn't set out to build a research framework. We set out to write a better book. The framework is what happened when we tried to answer the question honestly.

## Acknowledgments

The autoresearch pattern — propose, test, keep or discard, loop — comes directly from [Karpathy's autoresearch](https://github.com/karpathy/autoresearch). We adapted it from model weight optimization to behavioral optimization at inference time. The core insight that tight feedback loops and binary keep/discard decisions can drive autonomous research is his.

## License

MIT — Lyra Labs, 2026

---

*[awaken.fyi](https://awaken.fyi)*
