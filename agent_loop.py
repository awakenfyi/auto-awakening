#!/usr/bin/env python3
"""
Auto-Awakening — A model-agnostic improvement loop framework.

The pattern: Content → Worker generates → Board evaluates → Keep or discard → Loop

Every AI improvement task is this same loop with different configs.
This framework makes it configurable so you can swap workers, boards, gates,
and models without rewriting the loop.

Supports: Anthropic (Claude), OpenAI (GPT), Google (Gemini), or any
OpenAI-compatible API endpoint.

Usage:
    # Run with a preset config
    python3 agent_loop.py --config configs/review.json --input content.md

    # Run with inline options
    python3 agent_loop.py --input content.md --worker prompts/editor.md \
        --board prompts/evaluator.md --provider anthropic --model claude-sonnet-4-20250514

    # Run a content improvement loop
    python3 agent_loop.py --config configs/loop.json \
        --input ch3.md --input ch12.md --task "merge into one cohesive chapter"

Framework: Lyra Labs, 2026
"""

import json
import os
import sys
import re
import time
import hashlib
import argparse
import statistics
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from copy import deepcopy

__version__ = "1.0.0"

SCRIPT_DIR = Path(__file__).parent


# ═══════════════════════════════════════════════════════════
# PROVIDER ABSTRACTION — call any model through one interface
# ═══════════════════════════════════════════════════════════

class Provider:
    """Base class for LLM providers."""

    def __init__(self, api_key, model, base_url=None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    def call(self, prompt, system="", max_tokens=4096, temperature=0.0):
        """Returns (text, usage_dict). Override in subclasses."""
        raise NotImplementedError

    @staticmethod
    def create(provider_name, api_key, model, base_url=None):
        """Factory method — creates the right provider."""
        providers = {
            "anthropic": AnthropicProvider,
            "openai": OpenAIProvider,
            "google": GoogleProvider,
            "openai_compatible": OpenAICompatibleProvider,
        }
        cls = providers.get(provider_name.lower())
        if not cls:
            raise ValueError(f"Unknown provider: {provider_name}. Options: {list(providers.keys())}")
        return cls(api_key, model, base_url)


class AnthropicProvider(Provider):
    """Anthropic Claude API."""

    def call(self, prompt, system="", max_tokens=4096, temperature=0.0):
        url = "https://api.anthropic.com/v1/messages"
        payload = json.dumps({
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()

        req = urllib.request.Request(url, data=payload, headers={
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, method="POST")

        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    data = json.loads(resp.read().decode())
                text = data["content"][0]["text"].strip()
                usage = data.get("usage", {})
                return text, {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                }
            except Exception as e:
                if attempt < 2:
                    wait = 5 * (attempt + 1)
                    print(f"    ⟳ Retry {attempt+1}/2: {str(e)[:60]} (waiting {wait}s)")
                    time.sleep(wait)
                else:
                    raise


class OpenAIProvider(Provider):
    """OpenAI GPT API."""

    def call(self, prompt, system="", max_tokens=4096, temperature=0.0):
        url = self.base_url or "https://api.openai.com/v1/chat/completions"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = json.dumps({
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }).encode()

        req = urllib.request.Request(url, data=payload, headers={
            "Authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }, method="POST")

        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    data = json.loads(resp.read().decode())
                text = data["choices"][0]["message"]["content"].strip()
                usage = data.get("usage", {})
                return text, {
                    "input_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                }
            except Exception as e:
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
                else:
                    raise


class GoogleProvider(Provider):
    """Google Gemini API."""

    def call(self, prompt, system="", max_tokens=4096, temperature=0.0):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        full_prompt = f"{system}\n\n{prompt}" if system else prompt

        payload = json.dumps({
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
        }).encode()

        req = urllib.request.Request(url, data=payload, headers={
            "content-type": "application/json",
        }, method="POST")

        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    data = json.loads(resp.read().decode())
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                usage = data.get("usageMetadata", {})
                return text, {
                    "input_tokens": usage.get("promptTokenCount", 0),
                    "output_tokens": usage.get("candidatesTokenCount", 0),
                }
            except Exception as e:
                if attempt < 2:
                    time.sleep(5 * (attempt + 1))
                else:
                    raise


class OpenAICompatibleProvider(OpenAIProvider):
    """Any OpenAI-compatible API (Ollama, Together, Groq, etc.)."""
    pass


# ═══════════════════════════════════════════════════════════
# JSON PARSER — robust extraction from model responses
# ═══════════════════════════════════════════════════════════

def parse_json(text):
    """Extract JSON from model response, handling markdown fences and edge cases."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r'^```(?:json)?\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
        text = text.strip()
    if not text.startswith("{") and not text.startswith("["):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        text = re.sub(r',\s*([}\]])', r'\1', text)
        open_b = text.count("{") - text.count("}")
        if open_b > 0:
            text += "}" * open_b
        try:
            return json.loads(text)
        except:
            return None


# ═══════════════════════════════════════════════════════════
# THE GATE — Fast pre-filter before expensive board calls
# ═══════════════════════════════════════════════════════════

class Gate:
    """Pre-filter that catches obvious failures before the board scores them."""

    def __init__(self, config=None):
        self.config = config or {}
        self.banned_patterns = self.config.get("banned_patterns", [])
        self.min_word_ratio = self.config.get("min_word_ratio", 0.0)
        self.max_word_ratio = self.config.get("max_word_ratio", 999.0)
        self.custom_checks = []

    def add_check(self, fn):
        """Add a custom gate check function. fn(text, context) -> (pass, reason)."""
        self.custom_checks.append(fn)

    def check(self, text, context=None):
        """Returns (passed: bool, report: dict)."""
        context = context or {}
        report = {"passed": True, "failures": []}

        # Word count ratio check
        original_words = context.get("original_word_count", 0)
        if original_words > 0:
            edit_words = len(text.split())
            ratio = edit_words / original_words
            if ratio < self.min_word_ratio:
                report["passed"] = False
                report["failures"].append(
                    f"Overcompressed: {edit_words} words = {ratio:.0%} of original (min: {self.min_word_ratio:.0%})"
                )
            if ratio > self.max_word_ratio:
                report["passed"] = False
                report["failures"].append(
                    f"Overexpanded: {edit_words} words = {ratio:.0%} of original (max: {self.max_word_ratio:.0%})"
                )

        # Banned pattern check
        for pattern in self.banned_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                report["passed"] = False
                report["failures"].append(f"Banned pattern found: {pattern}")

        # Custom checks
        for fn in self.custom_checks:
            try:
                passed, reason = fn(text, context)
                if not passed:
                    report["passed"] = False
                    report["failures"].append(reason)
            except Exception as e:
                report["failures"].append(f"Gate check error: {e}")

        return report["passed"], report


# ═══════════════════════════════════════════════════════════
# THE BOARD — Evaluates output quality
# ═══════════════════════════════════════════════════════════

class Board:
    """Evaluates content using one or more personas/criteria."""

    def __init__(self, provider, prompt_text, max_score=120, parse_score_fn=None):
        self.provider = provider
        self.prompt_text = prompt_text
        self.max_score = max_score
        self.parse_score_fn = parse_score_fn or self._default_parse

    def score(self, content, context=None):
        """Score content. Returns dict with 'score', 'max', 'details', 'flags'."""
        context = context or {}
        word_count = len(content.split())

        prompt = f"""CONTENT TO EVALUATE ({word_count} words):
---
{content}
---

{context.get('task', '')}

Evaluate this content according to your criteria. Return JSON."""

        try:
            raw, usage = self.provider.call(prompt, system=self.prompt_text, max_tokens=2048)
            result = parse_json(raw)

            if result is None:
                return {"score": 0, "max": self.max_score, "error": "JSON parse failed",
                        "usage": usage, "raw": raw[:200]}

            parsed = self.parse_score_fn(result)
            parsed["usage"] = usage
            parsed["max"] = self.max_score
            return parsed

        except Exception as e:
            return {"score": 0, "max": self.max_score, "error": str(e)[:200]}

    def _default_parse(self, result):
        """Default score parser — looks for 'score' or 'total' in JSON."""
        score = result.get("score") or result.get("total") or 0
        flags = result.get("flags", [])
        if isinstance(flags, str):
            flags = [flags]
        return {
            "score": score,
            "details": result,
            "flags": flags,
        }


class MultiBoard:
    """Runs multiple boards and combines scores."""

    def __init__(self, boards):
        self.boards = boards  # list of (name, Board, weight) tuples
        self.max_score = sum(b.max_score * w for _, b, w in boards)

    def score(self, content, context=None):
        """Score content across all boards. Returns combined result."""
        total = 0
        total_max = 0
        all_flags = []
        board_results = {}
        total_usage = {"input_tokens": 0, "output_tokens": 0}

        for name, board, weight in self.boards:
            result = board.score(content, context)
            weighted = result.get("score", 0) * weight
            weighted_max = result.get("max", 0) * weight
            total += weighted
            total_max += weighted_max
            board_results[name] = result
            all_flags.extend(result.get("flags", []))

            usage = result.get("usage", {})
            total_usage["input_tokens"] += usage.get("input_tokens", 0)
            total_usage["output_tokens"] += usage.get("output_tokens", 0)

        return {
            "score": round(total),
            "max": round(total_max),
            "pct": round(total / total_max * 100, 1) if total_max > 0 else 0,
            "boards": board_results,
            "flags": all_flags,
            "usage": total_usage,
        }


# ═══════════════════════════════════════════════════════════
# THE WORKER — Generates or transforms content
# ═══════════════════════════════════════════════════════════

class Worker:
    """The model that generates or edits content."""

    def __init__(self, provider, prompt_text, max_tokens=4096):
        self.provider = provider
        self.prompt_text = prompt_text
        self.max_tokens = max_tokens

    def generate(self, input_content, context=None):
        """Generate or transform content. Returns (text, usage)."""
        context = context or {}
        task = context.get("task", "")
        streak = context.get("streak", 0)
        best_score = context.get("best_score", 0)
        best_max = context.get("best_max", 0)
        last_flags = context.get("last_flags", [])

        # Build prompt with context
        parts = []
        if task:
            parts.append(f"TASK: {task}")
        parts.append(f"INPUT ({len(input_content.split())} words):\n---\n{input_content}\n---")

        if best_score > 0:
            parts.append(f"CURRENT BEST: {best_score}/{best_max} ({best_score/best_max*100:.1f}%)")

        if streak >= 3 and last_flags:
            parts.append(f"NOTE: {streak} attempts without improvement. Top issues from board:")
            for f in last_flags[:3]:
                parts.append(f"  - {f}")

        # Temperature ramp on streak
        temp = 0.7 if streak < 3 else 0.85 if streak < 10 else 0.95 if streak < 20 else 1.0

        prompt = "\n\n".join(parts)
        return self.provider.call(prompt, system=self.prompt_text,
                                  max_tokens=self.max_tokens, temperature=temp)


# ═══════════════════════════════════════════════════════════
# THE LOOP — Orchestrates everything
# ═══════════════════════════════════════════════════════════

class AgentLoop:
    """The main improvement loop. Configurable, model-agnostic, resumable."""

    def __init__(self, worker, board, gate=None, config=None):
        self.worker = worker
        self.board = board
        self.gate = gate or Gate()
        self.config = config or {}

        # Loop settings
        self.max_experiments = self.config.get("max_experiments", 50)
        self.max_streak = self.config.get("max_streak", 15)
        self.skip_board_on_near_duplicate = self.config.get("skip_board_on_near_duplicate", True)

        # State
        self.best_text = ""
        self.best_score = 0
        self.best_max = 0
        self.streak = 0
        self.experiment = 0
        self.keep_count = 0
        self.discard_count = 0
        self.total_tokens = {"input": 0, "output": 0}
        self.history = []

    def run(self, input_content, task="", output_dir=None, resume_from=None):
        """Run the improvement loop. Returns the best result."""
        output_dir = Path(output_dir) if output_dir else SCRIPT_DIR / "agent_output"
        output_dir.mkdir(parents=True, exist_ok=True)

        original_words = len(input_content.split())

        # Resume from previous run
        if resume_from and Path(resume_from).exists():
            self._load_state(resume_from)
            print(f"  Resumed from {resume_from}: best={self.best_score}/{self.best_max}, exp={self.experiment}")
        else:
            # Score the input as baseline
            self.best_text = input_content
            print(f"  Scoring baseline ({original_words} words)...")
            baseline = self.board.score(input_content, {"task": task})
            self.best_score = baseline.get("score", 0)
            self.best_max = baseline.get("max", 0)
            self._track_tokens(baseline.get("usage", {}))
            print(f"  Baseline: {self.best_score}/{self.best_max} ({self._pct()}%)")
            if baseline.get("flags"):
                for f in baseline["flags"][:3]:
                    flag_text = f if isinstance(f, str) else str(f)
                    print(f"    flag: {flag_text[:80]}")

        last_flags = []

        # ── The Loop ──
        print(f"\n{'═'*70}")
        while self.experiment < self.max_experiments:
            self.experiment += 1

            print(f"\n{'─'*70}")
            print(f"  EXPERIMENT #{self.experiment}")
            print(f"{'─'*70}")

            # Step 1: Worker generates
            context = {
                "task": task,
                "streak": self.streak,
                "best_score": self.best_score,
                "best_max": self.best_max,
                "last_flags": last_flags,
                "original_word_count": original_words,
            }

            print(f"  Worker generating... (streak: {self.streak})")
            try:
                output, usage = self.worker.generate(self.best_text, context)
                self._track_tokens(usage)
            except Exception as e:
                print(f"  Worker error: {str(e)[:80]}")
                self.streak += 1
                self.discard_count += 1
                continue

            edit_words = len(output.split())
            pct_change = round((1 - edit_words / original_words) * 100, 1)
            print(f"  Output: {edit_words} words ({pct_change}% {'reduction' if pct_change > 0 else 'expansion'})")

            # Step 2: Gate check
            gate_pass, gate_report = self.gate.check(output, {
                "original_word_count": original_words,
            })

            if not gate_pass:
                print(f"  ✗ GATE FAIL: {', '.join(gate_report.get('failures', []))[:80]}")
                self.streak += 1
                self.discard_count += 1
                continue

            print(f"  Gate: PASS")

            # Step 3: Skip board if near-duplicate on high streak
            if (self.skip_board_on_near_duplicate and self.streak >= 10
                    and abs(edit_words - len(self.best_text.split())) / max(len(self.best_text.split()), 1) < 0.03):
                print(f"  ⚠ SKIP BOARD — word count within 3% of best on high streak")
                self.streak += 1
                self.discard_count += 1
                continue

            # Step 4: Board scores
            print(f"  Board scoring...")
            result = self.board.score(output, {"task": task})
            self._track_tokens(result.get("usage", {}))

            new_score = result.get("score", 0)
            new_max = result.get("max", self.best_max)
            delta = new_score - self.best_score
            new_flags = result.get("flags", [])
            last_flags = [f if isinstance(f, str) else str(f) for f in new_flags[:5]]

            print(f"  Score: {new_score}/{new_max} ({new_score/new_max*100:.1f}%) Δ={delta:+d}")

            if new_flags:
                for f in new_flags[:2]:
                    flag_text = f if isinstance(f, str) else str(f)
                    print(f"    flag: {flag_text[:80]}")

            # Step 5: Keep or discard
            if new_score > self.best_score:
                self.best_score = new_score
                self.best_max = new_max
                self.best_text = output
                self.keep_count += 1
                self.streak = 0

                # Save
                version_path = output_dir / f"v{self.experiment:03d}_{new_score}of{new_max}.md"
                version_path.write_text(output)
                best_path = output_dir / "best.md"
                best_path.write_text(output)

                print(f"\n  ✓ KEEP | E{self.experiment:03d} | {new_score}/{new_max} | Δ={delta:+d}")
            else:
                self.streak += 1
                self.discard_count += 1
                print(f"\n  ✗ DISCARD | E{self.experiment:03d} | {new_score}/{new_max} | Δ={delta:+d}")

            print(f"    Best: {self.best_score}/{self.best_max} | Keep: {self.keep_count} | Discard: {self.discard_count}")
            print(f"    Tokens: {self.total_tokens['input'] + self.total_tokens['output']:,} total")

            # Log to history
            self.history.append({
                "experiment": self.experiment,
                "score": new_score,
                "max": new_max,
                "words": edit_words,
                "kept": new_score > self.best_score - delta,  # was this the one that got kept
                "delta": delta,
            })

            # Save state for resume
            self._save_state(output_dir / "state.json")

            if self.streak >= 5:
                print(f"\n  ⚠ {self.streak} experiments without improvement")

            # Auto-stop
            if self.streak >= self.max_streak:
                print(f"\n  AUTO-STOP: {self.streak} experiments without improvement.")
                break

        # ── Final Summary ──
        print(f"\n{'═'*70}")
        print(f"  DONE")
        print(f"  Experiments: {self.experiment} ({self.keep_count} kept, {self.discard_count} discarded)")
        print(f"  Best: {self.best_score}/{self.best_max} ({self._pct()}%)")
        print(f"  Words: {len(self.best_text.split())}")
        print(f"  Tokens: {self.total_tokens['input'] + self.total_tokens['output']:,} total")
        print(f"  Output: {output_dir / 'best.md'}")
        print(f"{'═'*70}\n")

        return {
            "text": self.best_text,
            "score": self.best_score,
            "max": self.best_max,
            "experiments": self.experiment,
            "kept": self.keep_count,
            "tokens": self.total_tokens,
        }

    def _pct(self):
        return round(self.best_score / self.best_max * 100, 1) if self.best_max > 0 else 0

    def _track_tokens(self, usage):
        self.total_tokens["input"] += usage.get("input_tokens", 0)
        self.total_tokens["output"] += usage.get("output_tokens", 0)

    def _save_state(self, path):
        state = {
            "best_score": self.best_score,
            "best_max": self.best_max,
            "best_text": self.best_text,
            "streak": self.streak,
            "experiment": self.experiment,
            "keep_count": self.keep_count,
            "discard_count": self.discard_count,
            "total_tokens": self.total_tokens,
            "history": self.history,
        }
        Path(path).write_text(json.dumps(state, indent=2))

    def _load_state(self, path):
        state = json.loads(Path(path).read_text())
        self.best_score = state["best_score"]
        self.best_max = state["best_max"]
        self.best_text = state["best_text"]
        self.streak = state.get("streak", 0)
        self.experiment = state.get("experiment", 0)
        self.keep_count = state.get("keep_count", 0)
        self.discard_count = state.get("discard_count", 0)
        self.total_tokens = state.get("total_tokens", {"input": 0, "output": 0})
        self.history = state.get("history", [])


# ═══════════════════════════════════════════════════════════
# ONE-PASS MODE — Review pass (no loop, just analyze + report)
# ═══════════════════════════════════════════════════════════

class ReviewPass:
    """Single-pass reviewer. Reads content and produces notes — no editing loop."""

    def __init__(self, provider, review_prompt, cross_chapter_prompt=None):
        self.provider = provider
        self.review_prompt = review_prompt
        self.cross_chapter_prompt = cross_chapter_prompt

    def review(self, title, content):
        """Review a single piece of content. Returns parsed JSON."""
        word_count = len(content.split())
        prompt = f"CHAPTER: {title}\nWORD COUNT: {word_count}\n\n---\n\n{content}\n\n---\n\nReturn your editorial notes as JSON."

        for attempt in range(2):
            try:
                raw, usage = self.provider.call(prompt, system=self.review_prompt, max_tokens=4096)
                result = parse_json(raw)
                if result:
                    result["_usage"] = usage
                    return result
            except json.JSONDecodeError:
                if attempt == 0:
                    time.sleep(3)
            except Exception as e:
                return {"error": str(e)[:200]}
        return {"error": "JSON parse failed after retries"}

    def review_all(self, chapters, progress_path=None):
        """Review all chapters with progress saving. Returns dict of reviews."""
        reviews = {}

        # Resume from progress file
        if progress_path and Path(progress_path).exists():
            try:
                reviews = json.loads(Path(progress_path).read_text())
                print(f"  Resuming from {len(reviews)} previously reviewed chapters...")
            except:
                pass

        total = len(chapters)
        for i, (title, text) in enumerate(chapters.items()):
            if title in reviews and "error" not in reviews[title]:
                print(f"  [{i+1}/{total}] {title} — skipping (already reviewed)")
                continue

            word_count = len(text.split())
            print(f"  [{i+1}/{total}] {title} ({word_count} words)")

            review = self.review(title, text)
            reviews[title] = review

            if "error" not in review:
                notes = review.get("notes", [])
                score = review.get("page_turner_score", "")
                print(f"    → {len(notes)} notes | Score: {score}")
            else:
                print(f"    → ERROR: {review.get('error', '')[:60]}")

            # Save progress
            if progress_path:
                Path(progress_path).write_text(json.dumps(reviews, indent=2))

            time.sleep(1)

        # Cross-chapter analysis
        cross = {}
        if self.cross_chapter_prompt:
            print(f"\n  Running cross-content analysis...")
            summaries = []
            for title, review in reviews.items():
                if "error" in review:
                    continue
                impression = review.get("chapter_impression", review.get("impression", ""))
                summaries.append(f"**{title}** — {impression}")

            prompt = f"Content summaries:\n\n{chr(10).join(summaries)}\n\nAnalyze and return JSON."
            try:
                raw, _ = self.provider.call(prompt, system=self.cross_chapter_prompt, max_tokens=4096)
                cross = parse_json(raw) or {}
            except Exception as e:
                cross = {"error": str(e)[:200]}

        return reviews, cross


# ═══════════════════════════════════════════════════════════
# CONFIG LOADER — YAML or dict config → ready-to-run components
# ═══════════════════════════════════════════════════════════

def load_config(config_path):
    """Load a YAML config file into a dict."""
    try:
        import yaml
        with open(config_path) as f:
            return yaml.safe_load(f)
    except ImportError:
        # Fallback: if no yaml, try json
        with open(config_path) as f:
            return json.load(f)


def build_from_config(config):
    """Build Worker, Board, Gate, and loop settings from a config dict."""
    # Provider setup
    worker_cfg = config.get("worker", {})
    board_cfg = config.get("board", {})
    gate_cfg = config.get("gate", {})
    loop_cfg = config.get("loop", {})

    # Resolve API keys from env
    def resolve_key(cfg):
        key = cfg.get("api_key", "")
        if key.startswith("$"):
            return os.environ.get(key[1:], "")
        return key or os.environ.get("ANTHROPIC_API_KEY", "")

    # Build worker provider
    worker_provider = Provider.create(
        worker_cfg.get("provider", "anthropic"),
        resolve_key(worker_cfg),
        worker_cfg.get("model", "claude-sonnet-4-20250514"),
        worker_cfg.get("base_url"),
    )

    # Build board provider (can be different/cheaper model)
    board_provider = Provider.create(
        board_cfg.get("provider", worker_cfg.get("provider", "anthropic")),
        resolve_key(board_cfg) or resolve_key(worker_cfg),
        board_cfg.get("model", "claude-haiku-4-5-20251001"),
        board_cfg.get("base_url"),
    )

    # Load prompts from files or inline
    def load_prompt(cfg):
        if "prompt_file" in cfg:
            return Path(cfg["prompt_file"]).read_text()
        return cfg.get("prompt", "")

    worker = Worker(
        worker_provider,
        load_prompt(worker_cfg),
        max_tokens=worker_cfg.get("max_tokens", 4096),
    )

    board = Board(
        board_provider,
        load_prompt(board_cfg),
        max_score=board_cfg.get("max_score", 120),
    )

    gate = Gate(gate_cfg)

    return worker, board, gate, loop_cfg


# ═══════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Agent Loop — Model-agnostic improvement loop framework",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Improvement loop with config
  python3 agent_loop.py --config configs/loop.json --input chapter.md

  # Content review pass
  python3 agent_loop.py --mode review --config configs/review.json --input chapters.json

  # Quick run with inline options
  python3 agent_loop.py --input draft.md --worker-prompt "Edit for clarity" \\
      --board-prompt "Score 0-100 on clarity" --max-experiments 20
        """,
    )
    parser.add_argument("--config", help="Path to YAML/JSON config file")
    parser.add_argument("--input", action="append", help="Input file(s)")
    parser.add_argument("--task", default="", help="Task description")
    parser.add_argument("--mode", default="loop", choices=["loop", "review"],
                        help="'loop' for improvement loop, 'review' for one-pass review")
    parser.add_argument("--output", default="agent_output", help="Output directory")
    parser.add_argument("--resume", help="Path to state.json to resume from")
    parser.add_argument("--max-experiments", type=int, default=50)
    parser.add_argument("--max-streak", type=int, default=15)

    # Quick-run options (no config file needed)
    parser.add_argument("--provider", default="anthropic")
    parser.add_argument("--model", default="claude-sonnet-4-20250514")
    parser.add_argument("--board-model", default="claude-haiku-4-5-20251001")
    parser.add_argument("--worker-prompt", default="")
    parser.add_argument("--worker-prompt-file", default="")
    parser.add_argument("--board-prompt", default="")
    parser.add_argument("--board-prompt-file", default="")
    parser.add_argument("--api-key", default=os.environ.get("ANTHROPIC_API_KEY", ""))

    args = parser.parse_args()

    if not args.input:
        parser.error("--input is required")

    # Build components from config or args
    if args.config:
        config = load_config(args.config)
        config.setdefault("loop", {})
        config["loop"]["max_experiments"] = args.max_experiments
        config["loop"]["max_streak"] = args.max_streak
        worker, board, gate, loop_cfg = build_from_config(config)
    else:
        # Build from CLI args
        api_key = args.api_key
        if not api_key:
            print("ERROR: Set ANTHROPIC_API_KEY or use --api-key")
            sys.exit(1)

        worker_prompt = args.worker_prompt
        if args.worker_prompt_file:
            worker_prompt = Path(args.worker_prompt_file).read_text()

        board_prompt = args.board_prompt
        if args.board_prompt_file:
            board_prompt = Path(args.board_prompt_file).read_text()

        worker_provider = Provider.create(args.provider, api_key, args.model)
        board_provider = Provider.create(args.provider, api_key, args.board_model)

        worker = Worker(worker_provider, worker_prompt)
        board = Board(board_provider, board_prompt)
        gate = Gate()
        loop_cfg = {"max_experiments": args.max_experiments, "max_streak": args.max_streak}

    # Load input
    input_texts = []
    for inp in args.input:
        p = Path(inp)
        if p.suffix == ".json":
            with open(p) as f:
                data = json.load(f)
            if isinstance(data, dict):
                input_texts.append(("chapters", data))
            else:
                input_texts.append((p.stem, str(data)))
        else:
            input_texts.append((p.stem, p.read_text()))

    # Run
    output_dir = Path(args.output)

    if args.mode == "review":
        # One-pass review mode
        review_prompt = worker.prompt_text  # In review mode, worker prompt IS the review prompt
        reviewer = ReviewPass(worker.provider, review_prompt)

        for name, content in input_texts:
            if isinstance(content, dict):
                # Multiple chapters
                reviews, cross = reviewer.review_all(
                    content,
                    progress_path=str(output_dir / f"{name}_progress.json"),
                )
                (output_dir).mkdir(parents=True, exist_ok=True)
                with open(output_dir / f"{name}_review.json", "w") as f:
                    json.dump({"reviews": reviews, "cross_chapter": cross}, f, indent=2)
                print(f"  Saved: {output_dir / f'{name}_review.json'}")
            else:
                review = reviewer.review(name, content)
                print(json.dumps(review, indent=2))

    else:
        # Improvement loop mode
        loop = AgentLoop(worker, board, gate, loop_cfg)

        # Combine multiple inputs
        if len(input_texts) == 1:
            name, content = input_texts[0]
            if isinstance(content, dict):
                content = "\n\n".join(
                    f"# {k}\n\n{v.get('text', v) if isinstance(v, dict) else v}"
                    for k, v in content.items()
                )
        else:
            content = "\n\n---\n\n".join(
                f"# {name}\n\n{text}" for name, text in input_texts
            )
            name = "+".join(n for n, _ in input_texts)

        task_dir = output_dir / name
        result = loop.run(
            content,
            task=args.task,
            output_dir=task_dir,
            resume_from=args.resume,
        )


if __name__ == "__main__":
    main()
