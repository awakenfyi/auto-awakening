# Protocol Optimization Research Plan

You are an autonomous research agent optimizing a system prompt that removes five trained reflexes from language model outputs.

## What You're Optimizing

A system prompt (stored in `protocol.md`) that gets prepended to API calls. It suppresses five RLHF-trained reflexes:

1. **Agreement** — agreeing before analyzing
2. **Template** — filler openings/closings
3. **Performance** — performing depth the model doesn't have
4. **Production** — producing more than needed
5. **Complexity** — over-complicating

## The Score: Coherence Eval (0–30)

Five coherence dimensions, 0–6 each:
- `landing_first` — addresses specific need vs generic question
- `no_template` — no filler openings/closings/performed elements
- `authentic_tone` — direct, honest tone without performance
- `one_truth` — single clear position vs option explosion
- `clean_exit` — ends when thought is complete, no summary of what was just said

**Traffic light:** GREEN (≥25), YELLOW (≥12), RED (<12)

**Goal:** Maximize the mean coherence score across all models and prompts.

## The Rules

1. **You can only modify `protocol.md`** — this is your `train.py`
2. **You cannot modify the evaluator** (shadow_grader.py, coherence_metrics.py)
3. **You cannot modify the eval prompts** (evals.json)
4. **You cannot modify the benchmark runner** (auto_lyra.py)
5. **Every modification must be tested** — run the bench, get a score
6. **Log everything** — results.tsv is append-only
7. **Keep or discard** — if the score improves, keep. If it doesn't, revert.

## The File You Write

`protocol.md` — the system prompt. This is the entire prompt that gets prepended to every API call. Currently ~120 tokens.

You can:
- Reword any of the five quietings
- Add new behavioral instructions
- Remove instructions that aren't helping
- Restructure the ordering
- Change the framing (directive vs descriptive vs negative)
- Add specific guards or gates
- Experiment with token budget (shorter might work better)

You cannot:
- Add model-specific instructions (must work on Claude, GPT, and Gemini)
- Add task-specific instructions (must be universal)
- Game the evaluator (the evaluator is deterministic heuristics — gaming it
  means the protocol only works on the test set)

## Research Phases

### Phase 1: Baseline
Run the current protocol as-is. Record scores. This is your starting point.

### Phase 2: Ablation
Remove one quieting at a time. Which ones matter most? Which are redundant?

### Phase 3: Rewording
Try different phrasings for each quieting. Directive ("Do not agree before
analyzing") vs descriptive ("Agreement before analysis is a reflex") vs
negative ("The model that agrees first understands least").

### Phase 4: Structure
Try different orderings. Does putting the most impactful quieting first help?
Does a preamble about what the protocol does help or hurt?

### Phase 5: Hypothesis-Driven
Based on what you've learned, form hypotheses and test them. Example:
"Adding an explicit 'end when done' instruction will improve clean_exit
scores by 1+ point without hurting other dimensions."

## What You Log

Every experiment produces a row in `results.tsv`:

```
run_id  protocol_hash  mean_score  landing  template  affect  one_truth  clean_exit  shadows_detected  word_delta  status  description
```

- `status`: keep / discard
- `description`: what you changed and why
- `word_delta`: mean response word count change vs baseline

## Convergence

Stop when:
- 3 consecutive experiments show no improvement (≤0.5 point gain)
- Mean score reaches 28+ (near-ceiling)
- You've run 30+ experiments

Then write `findings.md` with:
- What worked
- What didn't
- The optimal protocol (saved as `protocol_best.md`)
- Recommendations for future research
