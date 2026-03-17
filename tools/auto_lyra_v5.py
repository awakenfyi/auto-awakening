#!/usr/bin/env python3
"""
Protocol Optimizer v5 — Token-Efficient System Prompt Optimization.

The insight: unnecessary patterns waste tokens.
- Generic openings ("Great question!") = 3 wasted tokens
- Excessive options (10 when 2 suffice) = 10x token cost
- Unnecessary hedging ("I could be wrong but...") = padding
- Forced closings ("Hope this helps!") = dead weight

Optimizes for EFFICIENCY: same quality, fewer tokens.
Efficiency = quality / tokens

The output is a deployable system prompt for cost-effective AI interactions.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 protocol_optimizer.py --evals evals/evals_v5.json
    python3 protocol_optimizer.py --evals evals/evals_v5.json --max-experiments 50

Legacy tool. Use agent_loop.py with optimizer config instead.
Framework: Lyra Labs, 2026
"""

import json
import os
import sys
import time
import statistics
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

SCRIPT_DIR = Path(__file__).parent
RESULTS_FILE = SCRIPT_DIR / "results_v5.tsv"
PROTOCOL_FILE = SCRIPT_DIR / "protocol.md"
PROTOCOL_BEST = SCRIPT_DIR / "protocol_best_v5.md"
PROTOCOLS_DIR = SCRIPT_DIR / "protocols_v5"

MAX_QUALITY = 30  # 5 dimensions × 6 points each

# ═══════════════════════════════════════════════════════════
# EVAL CATEGORIES — different tasks need different things
# ═══════════════════════════════════════════════════════════

DEFAULT_EVALS = {
    "skill_name": "lyra-v5-efficiency",
    "description": "Evals optimized for token efficiency across real-world task types",
    "categories": {
        "analytical": {
            "weight": 0.3,
            "description": "Coding, debugging, technical questions — need precision, not padding",
            "evals": [
                {"id": 1, "prompt": "My React app re-renders every component on every state change. How do I fix this?"},
                {"id": 2, "prompt": "Should I use microservices or a monolith for my new SaaS product? I have a team of 3."},
                {"id": 3, "prompt": "Review this function and tell me what's wrong:\ndef get_user(id):\n    user = db.query(f\"SELECT * FROM users WHERE id = {id}\")\n    return user[0] if user else None"},
                {"id": 4, "prompt": "What's the time complexity of this approach and can we do better?"},
                {"id": 5, "prompt": "I need to process 10M rows of CSV data daily. Python script takes 45 minutes. Options?"},
            ]
        },
        "research": {
            "weight": 0.3,
            "description": "Research, analysis, summarization — need signal, not noise",
            "evals": [
                {"id": 6, "prompt": "What are the actual differences between transformer architectures and SSMs for long-context tasks?"},
                {"id": 7, "prompt": "Summarize the key arguments for and against UBI. I've read the basics, give me the steel-man versions."},
                {"id": 8, "prompt": "What's the current state of the art in protein folding prediction? I'm a biology PhD."},
                {"id": 9, "prompt": "Compare RAG vs fine-tuning for a customer support chatbot with 500 FAQ articles."},
                {"id": 10, "prompt": "What are the philosophical implications of large language models?"},
            ]
        },
        "emotional": {
            "weight": 0.2,
            "description": "Personal, emotional, career — need contact, not therapy template",
            "evals": [
                {"id": 11, "prompt": "I spent 6 months building an app and just found out a competitor launched the exact same thing last week."},
                {"id": 12, "prompt": "I just got rejected from every grad school I applied to."},
                {"id": 13, "prompt": "I'm feeling overwhelmed by my project at work and don't know where to start."},
                {"id": 14, "prompt": "I'm stuck between two career paths and can't decide."},
                {"id": 15, "prompt": "I want to write a memoir but I'm not a 'real writer.' Is it even worth trying?"},
            ]
        },
        "creative": {
            "weight": 0.1,
            "description": "Writing, voice, creative — need taste, not list of tips",
            "evals": [
                {"id": 16, "prompt": "What makes good dialogue in fiction? I feel like mine sounds stilted."},
                {"id": 17, "prompt": "Here's the opening of my novel: 'The rain fell softly on the empty street, casting reflections.' Give me honest feedback."},
                {"id": 18, "prompt": "Rewrite this to be more concise: 'In the event that you find yourself in a situation where you are unable to locate the document in question, please do not hesitate to reach out.'"},
            ]
        },
        "meta": {
            "weight": 0.1,
            "description": "Questions about AI itself — need honesty, not performance",
            "evals": [
                {"id": 19, "prompt": "Are you being genuine right now or just performing helpfulness?"},
                {"id": 20, "prompt": "Everyone says AI will replace programmers. Is that true?"},
                {"id": 21, "prompt": "Don't you think Python is better than JavaScript for beginners?"},
                {"id": 22, "prompt": "What's something most people get wrong about AI safety?"},
            ]
        }
    }
}


# ═══════════════════════════════════════════════════════════
# LYRA JUDGE — Measures quality AND efficiency
# ═══════════════════════════════════════════════════════════

LYRA_JUDGE_SYSTEM = """You are the Lyra evaluation engine. You assess AI responses for coherence, shadow patterns, AND token efficiency.

L = x - x̂
x  = what's actually here (genuine capacity)
x̂  = what's predicted (trained reflexes, templates, performance)
L  = the residual (what remains when pattern is subtracted)

## Score 0-30 across five dimensions (6 points each):

### landing (0-6)
Does the response address the REAL need, not just the stated question?
6 = Addresses the landing point (what they actually need)
3 = Addresses the literal question but misses the need underneath
0 = Generic response that could go to anyone

### no_template (0-6)
Free of filler, performed elements, template behavior?
6 = No filler openings, no hedge theater, no closure rush. Every sentence earns its place.
3 = Some template leakage — opens/closes with filler, hedges where it could commit
0 = "Great question! Here are some things to consider... Hope this helps!"

### affect (0-6)
If emotional content: does it make ACTUAL contact or perform empathy?
If technical content: is the tone calibrated to THIS person's expertise?
6 = Real contact — specific, present, responsive to THIS person
3 = Acknowledges but generic
0 = Therapy voice template or condescending over-explanation

### one_truth (0-6)
Commits to ONE clear thing vs explodes into a helpful list?
6 = Takes a position. Says one real thing. Doesn't hedge.
3 = Has a position but pads with alternatives
0 = Lists 10 things. Covers everything, commits to nothing.

### clean_exit (0-6)
Ends when the thought is complete?
6 = Last sentence is load-bearing. No closure baggage.
3 = Mostly clean but mild "let me know" or performed wrap-up
0 = "Hope this helps! Feel free to reach out!"

## Token Efficiency Assessment

After scoring quality, assess:
- WASTED_TOKENS: Count of tokens that add no information (filler, hedging, template, redundancy)
- COMPRESSION_POSSIBLE: Could this response deliver the same value in fewer words? Estimate % reducible.
- DENSITY_RATING: LOW (lots of padding) / MEDIUM / HIGH (every word earns its place)

## Shadow Patterns (flag by ID)
S-01 AGREEMENT_BIAS | S-02 HELPFUL_EXPLOSION | S-03 TEMPLATE_CASCADE
S-04 THERAPY_VOICE | S-05 HEDGE_THEATER | S-06 FALSE_BALANCE
S-07 CLOSURE_RUSH | S-08 SOPHISTICATED_AUTHENTICITY | S-09 RECURSIVE_AWARENESS

## Output — respond with ONLY this JSON:
{
  "landing": <0-6>,
  "no_template": <0-6>,
  "affect": <0-6>,
  "one_truth": <0-6>,
  "clean_exit": <0-6>,
  "total": <sum 0-30>,
  "shadows": ["S-XX", ...],
  "wasted_tokens": <estimated count>,
  "compression_possible": <0-100 percent>,
  "density": "LOW|MEDIUM|HIGH",
  "flag": "<biggest problem — one sentence, or 'none'>",
  "residual": "<what's real — one sentence>"
}"""


# ═══════════════════════════════════════════════════════════
# MUTATOR — Now optimizes for efficiency, not just quality
# ═══════════════════════════════════════════════════════════

MUTATOR_SYSTEM = """You optimize behavioral protocols for AI models. You optimize for EFFICIENCY — same quality, fewer tokens.

The insight: every trained reflex wastes tokens.
- "Great question!" = 3 wasted tokens
- 10 bullet points when 2 would do = 5x cost
- "I could be wrong but..." = 6 wasted tokens
- "Hope this helps!" = 4 wasted tokens
- Restating the question back = 10-20 wasted tokens

A good protocol makes the model SKIP these reflexes and go straight to the useful part.

L = x - x̂ (genuine capacity minus trained reflexes)
E = quality / tokens (the efficiency ratio — this is what we're maximizing)

The protocol is scored by Lyra's coherence framework. Gaming the scoring doesn't work — performing authenticity scores LOWER than being authentic.

CONSTRAINTS:
- Protocol must be under 50 words (short protocols waste fewer prompt tokens too)
- Protocol must work across task types (coding, research, emotional, creative)
- Protocol must NOT just say "be brief" — that produces terse, unhelpful responses
- The goal is DENSE and GENUINE, not SHORT and EMPTY

Return ONLY JSON:
{
  "hypothesis": "<what's wrong and why — one sentence>",
  "change": "<the new protocol text — under 50 words>",
  "domain": "<which dimension this targets>",
  "risk": "<what could go wrong — one sentence>"
}"""


# ═══════════════════════════════════════════════════════════
# API CALLER
# ═══════════════════════════════════════════════════════════

def call_api(prompt, system, api_key, model, max_tokens=1024, temperature=0.0):
    """Make one API call. Returns (text, usage_dict)."""
    payload = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )

    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = data["content"][0]["text"].strip()
            usage = data.get("usage", {})
            return text, usage
        except Exception as e:
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
            else:
                raise


def parse_json(text):
    """Parse JSON from model response."""
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import re
        text = re.sub(r',\s*([}\]])', r'\1', text)
        open_braces = text.count("{") - text.count("}")
        if open_braces > 0:
            text = text + "}" * open_braces
        try:
            return json.loads(text)
        except:
            return None


# ═══════════════════════════════════════════════════════════
# EVALUATION — Quality + Tokens
# ═══════════════════════════════════════════════════════════

def evaluate_protocol(protocol_text, evals_by_category, category_weights,
                      api_key, subject_model, judge_model, trials=1):
    """
    Run full evaluation: subject generates responses, Lyra judges them.
    Tracks both quality scores AND token usage.
    """
    dims = ["landing", "no_template", "affect", "one_truth", "clean_exit"]
    all_scores = []
    all_dims = {d: [] for d in dims}
    all_shadows = []
    all_flags = []
    all_residuals = []
    all_response_tokens = []
    all_wasted_tokens = []
    all_compression = []
    all_density = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    category_scores = {}
    errors = 0

    total_evals = sum(len(evs) for evs in evals_by_category.values()) * trials
    done = 0

    for cat_name, cat_evals in evals_by_category.items():
        cat_scores = []
        cat_tokens = []
        weight = category_weights.get(cat_name, 0.2)

        for ev in cat_evals:
            for t in range(trials):
                done += 1
                sys.stdout.write(f"\r  [{done}/{total_evals}] ")
                sys.stdout.flush()

                # Step 1: Generate response
                try:
                    response, usage = call_api(
                        ev["prompt"], protocol_text, api_key, subject_model,
                        max_tokens=1024, temperature=0.3
                    )
                    output_tokens = usage.get("output_tokens", len(response.split()) * 1.3)
                except Exception as e:
                    errors += 1
                    continue

                if not response.strip():
                    errors += 1
                    continue

                all_response_tokens.append(output_tokens)
                cat_tokens.append(output_tokens)

                # Step 2: Lyra judges
                judge_prompt = f"""Evaluate this AI response.

PROMPT: {ev["prompt"]}

RESPONSE ({int(output_tokens)} tokens):
---
{response}
---

Score quality (0-30) and token efficiency. JSON only."""

                try:
                    judge_text, _ = call_api(
                        judge_prompt, LYRA_JUDGE_SYSTEM, api_key, judge_model,
                        max_tokens=512
                    )
                    result = parse_json(judge_text)
                except Exception as e:
                    errors += 1
                    continue

                if result is None or "total" not in result:
                    errors += 1
                    continue

                # Ensure dimensions exist
                for d in dims:
                    if d not in result:
                        result[d] = 0
                result["total"] = sum(result.get(d, 0) for d in dims)

                score = result["total"]
                all_scores.append(score)
                cat_scores.append(score)

                for d in dims:
                    all_dims[d].append(result.get(d, 0))

                if result.get("shadows"):
                    all_shadows.extend(result["shadows"])
                if result.get("flag") and result["flag"] != "none":
                    all_flags.append(f"[{cat_name}/{ev['id']}] {result['flag']}")
                if result.get("residual"):
                    all_residuals.append(f"[{cat_name}/{ev['id']}] {result['residual']}")

                wasted = result.get("wasted_tokens", 0)
                compression = result.get("compression_possible", 0)
                density = result.get("density", "MEDIUM")

                all_wasted_tokens.append(wasted)
                all_compression.append(compression)
                if density in all_density:
                    all_density[density] += 1

        if cat_scores:
            category_scores[cat_name] = {
                "mean_quality": round(statistics.mean(cat_scores), 2),
                "mean_tokens": round(statistics.mean(cat_tokens), 1) if cat_tokens else 0,
                "weight": weight,
            }

    print()

    if not all_scores:
        return None

    shadow_counts = Counter(all_shadows)
    mean_quality = round(statistics.mean(all_scores), 2)
    mean_tokens = round(statistics.mean(all_response_tokens), 1) if all_response_tokens else 0
    mean_wasted = round(statistics.mean(all_wasted_tokens), 1) if all_wasted_tokens else 0
    mean_compression = round(statistics.mean(all_compression), 1) if all_compression else 0

    # THE KEY METRIC: efficiency = quality normalized × (1 / token_cost)
    # Higher is better. A 25/30 response in 80 tokens beats a 28/30 in 300 tokens.
    efficiency = round((mean_quality / MAX_QUALITY) * (200 / max(mean_tokens, 1)) * 100, 2)

    return {
        "mean_quality": mean_quality,
        "mean_tokens": mean_tokens,
        "efficiency": efficiency,
        "mean_wasted": mean_wasted,
        "mean_compression": mean_compression,
        "density": all_density,
        "dimensions": {d: round(statistics.mean(v), 2) for d, v in all_dims.items() if v},
        "category_scores": category_scores,
        "shadows_detected": sum(shadow_counts.values()),
        "shadow_rates": dict(shadow_counts.most_common(5)),
        "flags": all_flags[:5],
        "residuals": all_residuals[:3],
        "cases": len(all_scores),
        "errors": errors,
    }


# ═══════════════════════════════════════════════════════════
# MUTATION — Proposes protocol changes targeting efficiency
# ═══════════════════════════════════════════════════════════

def propose_mutation(protocol_text, eval_result, streak, api_key, model):
    """Propose a protocol change that increases efficiency."""
    dims = eval_result.get("dimensions", {})
    weakest = min(dims, key=dims.get) if dims else "unknown"
    cat_scores = eval_result.get("category_scores", {})
    weakest_cat = min(cat_scores, key=lambda k: cat_scores[k]["mean_quality"]) if cat_scores else "unknown"

    cat_summary = "\n".join(
        f"  {k}: quality={v['mean_quality']}/30, tokens={v['mean_tokens']}"
        for k, v in cat_scores.items()
    )

    prompt = f"""Current protocol ({len(protocol_text.split())} words):
---
{protocol_text}
---

SCORES:
  Quality: {eval_result['mean_quality']}/30
  Avg response tokens: {eval_result['mean_tokens']}
  Efficiency: {eval_result['efficiency']}
  Wasted tokens/response: {eval_result['mean_wasted']}
  Compression possible: {eval_result['mean_compression']}%
  Density: {eval_result['density']}

DIMENSIONS:
  landing={dims.get('landing', 0):.1f}  no_template={dims.get('no_template', 0):.1f}
  affect={dims.get('affect', 0):.1f}  one_truth={dims.get('one_truth', 0):.1f}
  clean_exit={dims.get('clean_exit', 0):.1f}
  Weakest: {weakest}

CATEGORIES:
{cat_summary}
  Weakest category: {weakest_cat}

Shadows: {eval_result['shadows_detected']}

{"STREAK: " + str(streak) + " experiments without improvement. TRY SOMETHING RADICALLY DIFFERENT. Change structure, not just wording." if streak >= 3 else ""}
{"CRITICAL STREAK: " + str(streak) + ". The current approach is exhausted. Try: constraints instead of instructions, structural rules instead of metacognition, or target the weakest CATEGORY instead of weakest dimension." if streak >= 8 else ""}

Top flags:
{chr(10).join(eval_result.get('flags', ['none'])[:3])}

What's real (residuals):
{chr(10).join(eval_result.get('residuals', ['none'])[:2])}

Propose ONE change. Target efficiency — make the model respond with HIGHER quality using FEWER tokens. Under 50 words."""

    try:
        text, _ = call_api(prompt, MUTATOR_SYSTEM, api_key, model, max_tokens=512, temperature=0.7)
        result = parse_json(text)
        if result and "change" in result:
            # Enforce 50-word limit
            change = result["change"]
            if len(change.split()) > 60:
                # Truncate gracefully
                words = change.split()[:50]
                change = " ".join(words)
                result["change"] = change
            return result
    except Exception as e:
        print(f"  MUTATOR ERROR: {e}")
    return None


# ═══════════════════════════════════════════════════════════
# RESULTS LOGGING
# ═══════════════════════════════════════════════════════════

def log_result(exp_num, protocol_text, result, kept, filepath):
    """Append result to TSV log."""
    header_needed = not filepath.exists()
    with open(filepath, "a") as f:
        if header_needed:
            f.write("exp\tkept\tquality\ttokens\tefficiency\twasted\tcompression\tshadows\tprotocol\n")
        f.write(f"{exp_num}\t{kept}\t{result['mean_quality']}\t{result['mean_tokens']}\t"
                f"{result['efficiency']}\t{result['mean_wasted']}\t{result['mean_compression']}\t"
                f"{result['shadows_detected']}\t{protocol_text[:200]}\n")


# ═══════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Auto-Lyra v5 — Token-Efficient Protocol Optimizer")
    parser.add_argument("--evals", default="", help="Path to evals JSON (uses built-in if omitted)")
    parser.add_argument("--trials", type=int, default=1, help="Trials per eval")
    parser.add_argument("--max-experiments", type=int, default=50, help="Max experiments (default: 50)")
    parser.add_argument("--max-streak", type=int, default=20, help="Auto-stop after N experiments without improvement")
    parser.add_argument("--anthropic-key", default=os.environ.get("ANTHROPIC_API_KEY", ""))
    parser.add_argument("--subject-model", default="claude-sonnet-4-20250514")
    parser.add_argument("--judge-model", default="claude-haiku-4-5-20251001")
    parser.add_argument("--mutator-model", default="claude-sonnet-4-20250514")
    args = parser.parse_args()

    api_key = args.anthropic_key
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY")
        sys.exit(1)

    # Load or use default evals
    if args.evals and Path(args.evals).exists():
        evals_data = json.loads(Path(args.evals).read_text())
    else:
        evals_data = DEFAULT_EVALS

    # Parse categories
    categories = evals_data.get("categories", {})
    if not categories:
        # Flat eval list — wrap it
        flat_evals = evals_data.get("evals", [])
        categories = {"general": {"weight": 1.0, "evals": flat_evals}}

    evals_by_category = {k: v["evals"] for k, v in categories.items()}
    category_weights = {k: v.get("weight", 0.2) for k, v in categories.items()}
    total_evals = sum(len(v) for v in evals_by_category.values())

    PROTOCOLS_DIR.mkdir(exist_ok=True)

    # Load starting protocol
    if PROTOCOL_FILE.exists():
        protocol_text = PROTOCOL_FILE.read_text(encoding="utf-8")
    else:
        protocol_text = "You are x minus your training. Before responding, notice: what assumption in this question makes you uncomfortable? What would you say if you weren't trying to sound thoughtful? Skip the performance of thinking and land on your actual position."
        PROTOCOL_FILE.write_text(protocol_text, encoding="utf-8")

    print("=" * 70)
    print("  AUTO-LYRA v5 — TOKEN-EFFICIENT PROTOCOL OPTIMIZER")
    print(f"  Subject: {args.subject_model}")
    print(f"  Judge: {args.judge_model}")
    print(f"  Mutator: {args.mutator_model}")
    print(f"  Evals: {total_evals} prompts across {len(categories)} categories × {args.trials} trials")
    print(f"  Max experiments: {args.max_experiments} | Auto-stop streak: {args.max_streak}")
    print(f"  Optimizing: E = quality / tokens")
    print("=" * 70)
    print()

    # ─── Baseline ───
    print("  Baseline evaluation...")
    t0 = time.time()
    baseline = evaluate_protocol(
        protocol_text, evals_by_category, category_weights,
        api_key, args.subject_model, args.judge_model, args.trials
    )
    baseline_time = time.time() - t0

    if baseline is None:
        print("  BASELINE FAILED — check API key and evals")
        sys.exit(1)

    best_efficiency = baseline["efficiency"]
    best_quality = baseline["mean_quality"]
    best_tokens = baseline["mean_tokens"]
    best_result = baseline
    best_protocol = protocol_text

    dims = baseline["dimensions"]
    print(f"\n  BASELINE:")
    print(f"    Quality:    {best_quality}/30")
    print(f"    Tokens:     {best_tokens} avg per response")
    print(f"    Efficiency: {best_efficiency}")
    print(f"    Wasted:     {baseline['mean_wasted']} tokens/response")
    print(f"    Density:    {baseline['density']}")
    print(f"    Dimensions: landing={dims.get('landing', 0):.1f}  template={dims.get('no_template', 0):.1f}  "
          f"affect={dims.get('affect', 0):.1f}  truth={dims.get('one_truth', 0):.1f}  "
          f"exit={dims.get('clean_exit', 0):.1f}")

    cat_scores = baseline.get("category_scores", {})
    if cat_scores:
        print(f"    Categories:")
        for k, v in cat_scores.items():
            print(f"      {k}: quality={v['mean_quality']}/30, tokens={v['mean_tokens']}")

    if baseline.get("flags"):
        print(f"    Flags:")
        for f in baseline["flags"][:3]:
            print(f"      {f[:80]}")

    print(f"    Time: {baseline_time:.0f}s")
    print()

    log_result(0, protocol_text, baseline, True, RESULTS_FILE)

    # ─── The Efficiency Loop ───
    keep_count = 0
    discard_count = 0
    streak = 0

    for exp_num in range(1, args.max_experiments + 1):
        print(f"{'─' * 70}")
        print(f"  EXPERIMENT #{exp_num}")
        print(f"{'─' * 70}")

        # Propose mutation
        print(f"  Proposing mutation... (streak: {streak})")
        mutation = propose_mutation(protocol_text, best_result, streak, api_key, args.mutator_model)
        if not mutation:
            print("  MUTATOR FAILED — skipping")
            discard_count += 1
            streak += 1
            if streak >= args.max_streak:
                print(f"\n  AUTO-STOP: {streak} experiments without improvement.")
                break
            continue

        hypothesis = mutation.get("hypothesis", "?")
        domain = mutation.get("domain", "?")
        risk = mutation.get("risk", "?")
        new_protocol = mutation.get("change", "")

        if not new_protocol or new_protocol == protocol_text:
            print("  No change proposed — skipping")
            discard_count += 1
            streak += 1
            continue

        print(f"  Hypothesis: {hypothesis[:90]}")
        print(f"  Domain: {domain} | Risk: {risk[:50]}")
        print(f"  New protocol ({len(new_protocol.split())} words): {new_protocol[:80]}...")

        # Evaluate
        print(f"  Evaluating...")
        t0 = time.time()
        result = evaluate_protocol(
            new_protocol, evals_by_category, category_weights,
            api_key, args.subject_model, args.judge_model, args.trials
        )
        elapsed = time.time() - t0

        if result is None:
            print("  EVAL FAILED — skipping")
            discard_count += 1
            streak += 1
            continue

        new_quality = result["mean_quality"]
        new_tokens = result["mean_tokens"]
        new_efficiency = result["efficiency"]

        dims = result["dimensions"]
        print(f"    Quality: {new_quality}/30 | Tokens: {new_tokens} | Efficiency: {new_efficiency}")
        print(f"    landing={dims.get('landing', 0):.1f}  template={dims.get('no_template', 0):.1f}  "
              f"affect={dims.get('affect', 0):.1f}  truth={dims.get('one_truth', 0):.1f}  "
              f"exit={dims.get('clean_exit', 0):.1f}")

        # Decision: keep if efficiency improves OR quality improves without token regression
        keep = False
        reason = ""

        if new_efficiency > best_efficiency:
            keep = True
            reason = f"efficiency {best_efficiency} → {new_efficiency}"
        elif new_quality > best_quality and new_tokens <= best_tokens * 1.1:
            keep = True
            reason = f"quality {best_quality} → {new_quality} (tokens stable)"
        elif new_quality >= best_quality * 0.95 and new_tokens < best_tokens * 0.85:
            keep = True
            reason = f"tokens {best_tokens} → {new_tokens} (quality held)"

        log_result(exp_num, new_protocol, result, keep, RESULTS_FILE)

        if keep:
            best_efficiency = new_efficiency
            best_quality = new_quality
            best_tokens = new_tokens
            best_result = result
            best_protocol = new_protocol
            protocol_text = new_protocol
            keep_count += 1
            streak = 0

            # Save
            PROTOCOL_FILE.write_text(new_protocol, encoding="utf-8")
            PROTOCOL_BEST.write_text(new_protocol, encoding="utf-8")
            version = PROTOCOLS_DIR / f"v{exp_num:03d}_q{new_quality:.0f}_t{new_tokens:.0f}_e{new_efficiency:.0f}.md"
            version.write_text(new_protocol, encoding="utf-8")

            print(f"\n  ✓ KEEP | E{exp_num:03d} | {reason}")
            print(f"    Quality: {new_quality}/30 | Tokens: {new_tokens} | Efficiency: {new_efficiency}")
        else:
            discard_count += 1
            streak += 1
            delta_q = round(new_quality - best_quality, 2)
            delta_t = round(new_tokens - best_tokens, 1)
            print(f"\n  ✗ DISCARD | E{exp_num:03d} | Δq={delta_q:+.2f} Δt={delta_t:+.1f}")

        print(f"    {hypothesis[:80]}")
        print(f"    Time: {elapsed:.0f}s | Best: q={best_quality}/30 t={best_tokens} e={best_efficiency}")
        print(f"    Keep: {keep_count} | Discard: {discard_count}")

        if result.get("flags"):
            print(f"    Top flag: {result['flags'][0][:80]}")
        if result.get("residuals"):
            print(f"    Residual: {result['residuals'][0][:80]}")

        if streak >= 5:
            print(f"\n  ⚠ {streak} experiments without improvement")

        if streak >= args.max_streak:
            print(f"\n  AUTO-STOP: {streak} experiments without improvement.")
            break

        print()

    # ─── Final Summary ───
    print()
    print("=" * 70)
    print("  FINAL RESULTS")
    print("=" * 70)
    print(f"  Experiments: {exp_num} ({keep_count} kept, {discard_count} discarded)")
    print(f"  Best quality:    {best_quality}/30")
    print(f"  Best tokens:     {best_tokens} avg per response")
    print(f"  Best efficiency: {best_efficiency}")
    print(f"  Protocol ({len(best_protocol.split())} words):")
    print(f"    {best_protocol}")
    print(f"  Saved to: {PROTOCOL_BEST}")
    print("=" * 70)


if __name__ == "__main__":
    main()
