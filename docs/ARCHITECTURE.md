# Architecture — The Agent Loop Pattern

## The Core Insight

Every AI improvement task follows the same pattern:

1. A **Worker** generates or transforms content
2. A **Gate** catches obvious failures (free — no API calls)
3. A **Board** evaluates quality (costs tokens)
4. A **Loop Controller** decides: keep or discard, continue or stop

The only things that change between tasks are the prompts and the scoring criteria.

## Components

### Worker

The Worker is the model doing the actual work — editing a chapter, generating a protocol mutation, reviewing content. It receives:

- The current best version of the content
- The task description
- Context from the loop (streak count, best score, top flags from the board)

The Worker's temperature ramps up with the streak: starts at 0.7, rises to 1.0 at streak 20. This forces more creative attempts when the standard approach plateaus.

```python
worker = Worker(
    provider=AnthropicProvider(api_key, "claude-sonnet-4-20250514"),
    prompt_text=Path("prompts/editor.md").read_text(),
    max_tokens=8192,
)
```

### Gate

The Gate is a zero-cost pre-filter. It uses regex and word counts to catch obviously bad outputs before spending tokens on board evaluation.

Configurable checks:
- **Word count ratio** — reject if too compressed or too expanded
- **Banned patterns** — reject if contaminated with AI clichés
- **Custom functions** — add your own checks

```python
gate = Gate({
    "min_word_ratio": 0.5,    # Don't compress below 50% of original
    "max_word_ratio": 1.3,    # Don't expand beyond 130%
    "banned_patterns": ["(?i)in\\s+conclusion", "(?i)let'?s\\s+explore"],
})
```

### Board

The Board evaluates quality by sending the content to a judge model. It can be:

- **Single Board** — one prompt, one score (simpler, cheaper)
- **Multi Board** — multiple personas with weighted scores (richer, more expensive)

The board prompt defines the scoring criteria. The framework parses the JSON response and extracts the score.

```python
board = Board(
    provider=AnthropicProvider(api_key, "claude-haiku-4-5-20251001"),
    prompt_text=Path("prompts/evaluator.md").read_text(),
    max_score=120,
)
```

Use a cheaper/faster model for the board (Haiku) than for the worker (Sonnet). The board runs on every non-gated experiment, so it's the biggest token cost.

### Loop Controller

The `AgentLoop` class orchestrates everything:

```
for each experiment:
    output = worker.generate(best_text, context)
    if not gate.check(output):
        discard, continue
    score = board.score(output)
    if score > best_score:
        keep, reset streak
    else:
        discard, increment streak
    if streak >= max_streak:
        auto-stop
```

Key behaviors:
- **Streak tracking** — counts consecutive experiments without improvement
- **Temperature ramp** — increases creativity as streak grows
- **Near-duplicate skip** — if output word count is within 3% of best on a high streak, skip the board (saves tokens)
- **Auto-stop** — stops the loop when plateau is reached
- **State saving** — saves after every experiment so the loop can resume

## Token Budget

Typical costs per experiment:

| Step | API Calls | Tokens |
|------|-----------|--------|
| Worker | 1 (Sonnet) | ~4K prompt + ~2K output |
| Gate | 0 | Free (regex) |
| Board | 1 (Haiku) | ~3K prompt + ~1K output |
| **Total** | **2** | **~10K** |

With gate filtering, ~30% of experiments skip the board entirely = ~30% token savings.

For a 50-experiment run: ~350K tokens (~$1-2 with Sonnet + Haiku).

## Provider Abstraction

All providers implement the same interface:

```python
class Provider:
    def call(self, prompt, system="", max_tokens=4096, temperature=0.0):
        """Returns (text, usage_dict)."""
```

Supported: Anthropic, OpenAI, Google, any OpenAI-compatible endpoint.

To add a new provider, subclass `Provider` and implement `call()`.

## Review Mode

For one-pass review (no loop), use `ReviewPass`:

```python
reviewer = ReviewPass(
    provider=AnthropicProvider(api_key, "claude-sonnet-4-20250514"),
    review_prompt=Path("prompts/reviewer.md").read_text(),
    cross_chapter_prompt=Path("prompts/cross_chapter_analysis.md").read_text(),
)

reviews, cross = reviewer.review_all(chapters, progress_path="progress.json")
```

This processes each chapter sequentially, saves progress after each one (resume-safe), and runs a cross-chapter analysis at the end.

## Design Decisions

**Why JSON configs instead of Python?** Prompts change 10x more often than code. By putting prompts in markdown files and settings in JSON, you can iterate on the editorial approach without touching the framework.

**Why regex gates instead of LLM gates?** Speed and cost. A regex check takes <1ms and costs nothing. An LLM gate would add another API call per experiment. The gate catches 30% of bad outputs for free.

**Why Haiku for the board?** The board runs on every experiment. Using Sonnet for both worker and board would double the cost. Haiku is 10x cheaper and scores almost as well for evaluation tasks.

**Why auto-stop at 15 instead of 30?** Data from 5 merge loops showed that nothing beats the best after streak ~10. Experiments 10-30 are wasted tokens. Default is 15 with a small buffer.

**Why temperature ramp?** At low streaks, the worker makes sensible edits at temp 0.7. As it exhausts those, it needs more creative leaps. Temperature 1.0 at streak 20 produces wilder attempts that occasionally break through plateaus.
