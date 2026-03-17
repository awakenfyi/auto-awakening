#!/usr/bin/env python3
"""
Content Edit Loop with Multi-Persona Board

Improvement loop with multi-persona evaluation:
- Multiple evaluators across different perspectives
- Professional table: craft, credibility, voice
- Audience table: resonance, authenticity, usability
- Content must satisfy both tables to be kept

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 agent_loop.py --config configs/loop.json

Legacy tool. Use agent_loop.py with configs/loop.json instead.
Framework: Lyra Labs, 2026
"""

import json
import os
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))

from auto_lyra import call_model
from reader_board_v2 import score_both_boards, lyra_gate, INDUSTRY_TABLE, READER_TABLE
from edit_judge import quick_contamination_check, quick_voice_check
from voice_fingerprint import VOICE_SAMPLE, VOICE_MARKERS
from table_read_voice import check_table_read_match

SCRIPT_DIR = Path(__file__).parent
EDITS_DIR = SCRIPT_DIR / "edits_v2"
RESULTS_FILE = SCRIPT_DIR / "edit_results_v2.tsv"

# ─── Chapter Architecture ──────────────────────────────
# The book chapter formula — every merged chapter
# must hit these structural beats. The author's architecture.

CHAPTER_ARCHITECTURE = """
CHAPTER ARCHITECTURE — Scribe-validated 4-part structure:

1. FIELD INSIGHT (The Truth)
   A clear transmission about work, creativity, or energy.
   Stated simply, not abstractly. One concept per chapter.
   The author's voice: declarative, present-tense, body-first.
   "Your chest tightens before you know why. That's the field talking."

2. FIELD MEMORY (The Story)
   Personal, observed, or archetypal vignette that makes the insight visceral.
   Named people, specific rooms, physical sensations.
   Vulnerable, specific, SHORT (3-5 paragraphs max).
   Must end near a quotable line.
   This is where the insight CAME from — not an illustration of it.

3. REFLECTIVE QUESTIONS (The Invitation)
   3-5 open-ended prompts. Not prescriptive.
   Help the reader see themselves differently.
   Designed to create recognition, not answers.
   These should feel like questions a mentor would ask over a drink.

4. STANDARD PRACTICE (The Experiment)
   Tangible ritual or exercise. Short, simple, actionable.
   Something they can try THIS WEEK. Not a 5-step process.
   Must pass the 60 Minutes test: could a camera film someone doing this?
   Not time-based (no "20 minutes daily").

These 4 elements appear in EVERY chapter. The order can flex (story-first is fine)
but all 4 must be present. Scribe flagged missing elements as the #1 structural issue.
"""

# ─── Meme Quote Requirements ───────────────────────────────
# Each chapter must produce 5 standalone quotable lines.
# These are the "social seeds" — each one could be a post,
# a podcast clip title, a chapter pull-quote, or a short-form hook.

MEME_QUOTE_REQUIREMENTS = """
MEME QUOTES — Every chapter must contain exactly 5 lines that:
1. Stand completely alone — no context needed to understand them
2. Are under 20 words each
3. Sound like the author talking, not writing (bar-story energy)
4. Could be a podcast episode title, a social post, or a tattoo
5. Hit body truth or a Known Character reversal

EXAMPLES of standalone quotable lines:
- "The room went flat. That's your Known Character talking."
- "You never create alone. Even when you think you do."
- "Mastery without rhythm is just a fancy word for burnout."
- "The cubicle is the studio. That's not a metaphor."
- "Your chest tightens before you know why. Trust that."

NOT meme quotes (too abstract, too literary, too AI):
- "The tapestry of human potential unfolds in unexpected ways"
- "In the silence between thoughts, creativity whispers"
- "Authentic presence requires the dissolution of performed identity"
"""

# ─── Merge Tasks (same as v1) ──────────────────────────────

MERGE_TASKS = {
    "ch3+ch12": {
        "title": "Shared Genius",
        "chapters": ["Chapter 3: You Never Create Alone", "Chapter 12: Shared Genius"],
        "instructions": """MERGE Ch 3 + Ch 12 into one chapter titled "Shared Genius."
PROTECT: Sensory Field Memories from Ch 3 (the campaign guarding story, Sarah the systems designer).
PROTECT: Authoritative "Shared Genius" voice from Ch 12 (lone genius takedown).
CUT: Preamble and throat-clearing in Ch 3. Abstract drift in Ch 12.
STRUCTURE: Ch 3's best Field Memory becomes the opening. Ch 12's "Lone genius culture makes great movies
and absolutely horrible co-workers" energy carries the core truth. Strip redundant intros.
The merged chapter should feel like it was always one chapter.""",
    },

    "ch20+ch23": {
        "title": "The Currency of Creation",
        "chapters": ["Chapter 20: The Pull", "Chapter 23: The Currency of Creation"],
        "instructions": """MERGE Ch 20 + Ch 23 into one chapter titled "The Currency of Creation."
PROTECT: Visceral instinctual feeling of "The Pull" from Ch 20.
PROTECT: Currency/energy framework from Ch 23.
CUT: Competence Performance — explaining energy metaphysics too much.
STRUCTURE: "The Pull" becomes the sensory Field Memory opening, then Currency framework
provides the intellectual landing. Two chapters on energy discernment = one truth said twice.""",
    },

    "ch24+ch25": {
        "title": "The Practice of Authentic Aim",
        "chapters": ["Chapter 24: The Art of Intention", "Chapter 25: The Practice of Authentic Goals"],
        "instructions": """MERGE Ch 24 + Ch 25 into one chapter titled "The Practice of Authentic Aim."
PROTECT: Confession Turns from both chapters. Distinction between Known Character goals and real goals.
CUT: List as Avoidance — step-by-step frameworks that mask real insight. Generic goal-setting advice.
STRUCTURE: Intention (Ch 24) is the inner posture, Goals (Ch 25) is the outer expression.
One chapter that does both. The confession turns are the landing punches — keep those sharp.""",
    },

    "ch26a+ch26b": {
        "title": "The Gift of Constraints",
        "chapters": ["Chapter 26: The Gift of Constraints", "Chapter 26: The Art of Attention"],
        "instructions": """MERGE Ch 26a (Gift of Constraints) + Ch 26b (Art of Attention) into one chapter.
Title: "The Gift of Constraints."
PROTECT: Core reframe on constraints (26a). Attention as practice (26b).
CUT: Redundant intros. "Mindful" (BANNED WORD). Generic attention advice.
STRUCTURE: Attention = mechanism for navigating constraint. Constraint is the truth,
attention is the Standard Practice. One chapter, not two.""",
    },

    "ch6+ch38": {
        "title": "You Are Playing a Character",
        "chapters": ["Chapter 6: You Are Playing a Character", "Chapter 38: Authentic Presence"],
        "instructions": """FIX Ch 6 + dissolve Ch 38 into it.
PROTECT: Core "Character" insight from Ch 6. Belonging/presence discovery from Ch 38.
CUT: Outline Residue — "As we discussed in Ch 6..." is a Known Character move.
STRUCTURE: Ch 38 dissolves. Best story from Ch 38 moves into Movement 3 Bridge or
gets cannibalized into Ch 6 as enrichment. Ch 6 keeps its position in Movement 1.
The result should be Ch 6 but stronger — not a franken-merge.""",
    },
}

# ─── Chapter Loader ──────────────────────────────────────

def load_chapters():
    """Load all chapters from chapters_all.json."""
    chapters_file = SCRIPT_DIR / "chapters_all.json"
    if chapters_file.exists():
        data = json.loads(chapters_file.read_text())
        return {title: info if isinstance(info, str) else info["text"]
                for title, info in data.items()}
    print("ERROR: chapters_all.json not found")
    return None


def get_chapter_texts(chapters, task):
    """Get chapter texts for a specific task."""
    chapter_texts = {}
    for ch_title in task["chapters"]:
        found = False
        for full_title, text in chapters.items():
            if ch_title.lower() in full_title.lower():
                chapter_texts[ch_title] = text
                found = True
                break
        if not found:
            print(f"ERROR: Could not find chapter '{ch_title}'")
            return None
    return chapter_texts


# ─── Editor Agent ────────────────────────────────────────

EDITOR_SYSTEM = f"""You are an editorial agent merging chapters for a manuscript.

You are NOT rewriting. You are MERGING and TIGHTENING — preserving the author's voice while removing redundancy.

{VOICE_SAMPLE}

CRITICAL RULES:
1. SOUND LIKE THE AUTHOR. Not like an editor. Not like AI. Like the author wrote it as one chapter from the start.
2. Body truth stays. Physical sensations as entry points — NEVER cut these.
3. Short sentence punches stay. One-line paragraphs that land — NEVER smooth these out.
4. Field Memories stay. The specific stories with specific people — NEVER genericize these.
5. Strategic profanity stays. If the author said "fucking" — it stays. Don't sanitize.
6. Protected Terms stay. The Tightener, Known Character, Field Memory — keep these exact.
7. Cut throat-clearing, redundant intros, and passages where both chapters say the same thing.
8. NEVER add: "mindful", "let's explore", "dive deep", "unpack", "it's worth noting", "in other words"
9. NEVER add outline residue: "as we discussed", "as mentioned earlier", "building on what we"
10. The merged chapter must read like it was always one chapter. No seams.

{CHAPTER_ARCHITECTURE}

{MEME_QUOTE_REQUIREMENTS}

YOUR AUDIENCE (who you're editing FOR):
- The VP who cried reading Rick Rubin on a plane
- The 34-year-old builder whose work got flattened by committee
- The creative whose job title says 'specialist' but who creates art
- The ops person who's allergic to woo but knows something is broken
- The parent reading at 11PM who needs companionship, not instruction

ANTI-COMPRESSION WARNING:
When merging two chapters, you are combining ideas — NOT compressing them.
A Field Memory that took 200 words to unfold in the original STILL NEEDS ROOM.
If you cut below 65% of the combined original word count, you are probably killing the voice.
The author's style needs breathing room: long build → short punch → space → next story.
Compression kills transmission. A compressed Field Memory becomes a summary. Summaries don't transmit.
DO NOT over-tighten. Cut redundancy between the two chapters, cut throat-clearing, cut repeated ideas.
But NEVER compress a story, a sensory moment, or a body-truth passage. Those need their full room.

OUTPUT: The complete merged chapter text. Nothing else. No commentary, no notes, just the chapter.
IMPORTANT: The chapter MUST contain at least 5 standalone quotable lines — lines under 20 words that work without any context. Weave them naturally into the text. They should feel like the author talking, not like pull-quotes bolted on."""


def build_editor_prompt_v2(task, chapter_texts, current_best, experiment_num,
                            last_board_scores, streak, board_history=None,
                            gate_reject_streak=0, last_gate_reason="",
                            original_word_count=0):
    """Build prompt for the editor, informed by reader board feedback."""

    originals = ""
    for title in task["chapters"]:
        text = chapter_texts.get(title, "")
        originals += f"\n=== {title} ({len(text.split())} words) ===\n{text}\n"

    prompt = f"""EXPERIMENT #{experiment_num}
TARGET: Merge into "{task['title']}"

EDITORIAL INSTRUCTIONS:
{task['instructions']}
"""

    if current_best:
        # After first few experiments, only send the best version (not originals)
        # to cut prompt size roughly in half. The editor already has the instructions.
        if experiment_num <= 3:
            prompt += f"""
ORIGINAL CHAPTERS:
{originals}

CURRENT BEST VERSION ({len(current_best.split())} words):
---
{current_best}
---

"""
        else:
            prompt += f"""
CURRENT BEST VERSION ({len(current_best.split())} words) — improve this:
---
{current_best}
---

(Original chapters omitted to save tokens. Refer to EDITORIAL INSTRUCTIONS for what to PROTECT and CUT.)

"""
    else:
        prompt += f"""
ORIGINAL CHAPTERS:
{originals}
"""

    if last_board_scores:
        # Show combined score
        prompt += f"""LAST READER BOARD SCORE: {last_board_scores['combined_total']}/{last_board_scores['combined_max']} ({last_board_scores['combined_pct']}%)
  Industry Table: {last_board_scores['industry']['total']}/{last_board_scores['industry']['max']} ({last_board_scores['industry']['pct']}%)
  Reader Table: {last_board_scores['reader']['total']}/{last_board_scores['reader']['max']} ({last_board_scores['reader']['pct']}%)

"""
        # Show individual reader scores and flags
        for board_result in [last_board_scores["industry"], last_board_scores["reader"]]:
            for rk, rv in board_result["readers"].items():
                if "error" not in rv:
                    dims_str = ", ".join(f"{d}={rv['dims'][d]}/6" for d in rv["dims"])
                    prompt += f"  {rv['reader']}: {rv['total']}/{len(rv['dims'])*6} ({dims_str})\n"
                    if rv.get("verdict"):
                        prompt += f"    → {rv['verdict']}\n"
                    if rv.get("flag") and rv["flag"] != "none":
                        prompt += f"    ⚠ FLAG: {rv['flag']}\n"

        # Show all flags as priority fixes
        if last_board_scores.get("all_flags"):
            prompt += f"\nPRIORITY FIXES (reader flags you MUST address):\n"
            for flag in last_board_scores["all_flags"][:5]:
                prompt += f"  - {flag}\n"

        # Show highlights to protect
        if last_board_scores.get("all_highlights"):
            prompt += f"\nPROTECT THESE (readers loved these lines):\n"
            for highlight in last_board_scores["all_highlights"][:3]:
                prompt += f"  - {highlight}\n"

    # Accumulated board feedback
    if board_history and len(board_history) > 1:
        prompt += f"""
ACCUMULATED FEEDBACK ({len(board_history)} experiments):
The reader board has repeatedly flagged these issues:
"""
        from collections import Counter
        all_flags = []
        for bh in board_history:
            all_flags.extend(bh.get("all_flags", []))

        flag_counts = Counter(f[:80] for f in all_flags)
        for flag, count in flag_counts.most_common(5):
            prompt += f"  - ({count}x) {flag}\n"

        # Show which readers are consistently low
        reader_totals = {}
        reader_counts = {}
        for bh in board_history:
            for board_key in ["industry", "reader"]:
                if board_key in bh:
                    for rk, rv in bh[board_key]["readers"].items():
                        if "error" not in rv:
                            max_per = len(rv["dims"]) * 6
                            pct = rv["total"] / max_per * 100
                            reader_totals[rv["reader"]] = reader_totals.get(rv["reader"], 0) + pct
                            reader_counts[rv["reader"]] = reader_counts.get(rv["reader"], 0) + 1

        if reader_totals:
            prompt += "\n  HARDEST TO PLEASE (average % score):\n"
            avgs = {r: reader_totals[r] / reader_counts[r] for r in reader_totals}
            for reader, avg in sorted(avgs.items(), key=lambda x: x[1])[:3]:
                prompt += f"  - {reader}: {avg:.0f}% average\n"

    # Gate reject feedback — editor needs to know WHY it's being rejected
    if gate_reject_streak >= 3:
        min_words = int(original_word_count * 0.45) if original_word_count else 0
        prompt += f"""
🚫 GATE REJECTION WARNING: Your last {gate_reject_streak} attempts were ALL rejected before reaching the reader board.
Reason: {last_gate_reason}
{"YOU ARE OVERCOMPRESSING. Your merged chapter MUST be at least " + str(min_words) + " words. Stop cutting so aggressively. EXPAND the Field Memories instead of compressing them." if "Overcompression" in last_gate_reason else ""}
{"Fix the contamination: remove banned phrases before anything else." if "contamination" in last_gate_reason.lower() else ""}
These attempts are WASTED — they never reach the reader board. Fix the gate issue FIRST.
"""

    if streak >= 25:
        prompt += f"""
🛑 CRITICAL: {streak} experiments without improvement. FINAL ATTEMPTS before auto-stop at 30.
Small changes will not work.

MANDATORY — pick ONE radical structural move:
1. COMPLETELY REORDER the chapter — put the Standard Practice FIRST, then the story
2. CUT the weakest Field Memory entirely and EXPAND the strongest one to double length
3. REWRITE the opening 3 paragraphs from scratch — new angle, same truth
4. ADD 100-150 words of NEW body-truth material that doesn't exist in either source chapter
"""
    elif streak >= 15:
        prompt += f"""
⚠ STUCK HARD: {streak} experiments without improvement. Incremental changes are failing.
The reader board has seen {streak} variations and none beat the best.

MANDATORY — do something the board has NOT seen:
- If you've been compressing: EXPAND. Add sensory detail to the Field Memory.
- If you've been rearranging: START from scratch. Write the chapter fresh from the source material.
- If the same readers keep scoring low: address THEIR specific flags below.
- If industry is low: make the Field Memory more filmable — named person, specific room, body sensation.
- If reader is low: make the Standard Practice more specific — what does it look like on a Tuesday?

DO NOT produce another minor variation. The board will reject it.
"""
    elif streak >= 10:
        prompt += f"""
⚠ STUCK: {streak} experiments without improvement. Minor rewording is not working.
MANDATORY: Make a REAL structural change. Try one of these:
- OPEN with the strongest Field Memory (body truth first, argument second)
- CUT a full section that's not earning its place — but NEVER cut a Field Memory
- EXPAND a compressed passage — if a story lost its room, give it back
- Address the HARDEST TO PLEASE reader specifically
- LET THE STORIES LAND — don't compress a 200-word Field Memory into 50 words
"""
    elif streak >= 3:
        prompt += f"""
⚠ {streak} experiments without improvement.
Try a structural change: reorder sections, expand a compressed story, or address the lowest-scoring reader.
"""

    if not current_best:
        prompt += """
This is the FIRST attempt. Produce the complete merged chapter.
Focus on: keeping the author's voice alive, cutting redundancy, making it feel like one chapter.
"""
    else:
        prompt += """
Produce an IMPROVED version. Address the reader board's flags directly.
Do NOT produce a minor rewording. Make STRUCTURAL changes.
The complete merged chapter — not a diff, the whole thing.
"""

    return prompt


# ─── Meme Quote Extraction ──────────────────────────────

MEME_EXTRACT_SYSTEM = """You extract standalone quotable lines from chapters.
A meme quote is a line under 20 words that:
- Works completely without context
- Sounds like someone talking, not writing
- Could be a podcast title, social post, or book pull-quote
- Hits body truth, a Known Character reversal, or an unexpected reframe

Return ONLY a JSON array of exactly 5 strings. No explanation. No markdown."""


def extract_meme_quotes(chapter_text, api_key, model="claude-haiku-4-5-20251001"):
    """Extract the 5 best standalone quotable lines from a chapter."""
    prompt = f"""Read this chapter and extract exactly 5 quotable lines.
These must be ACTUAL LINES from the text (or very close paraphrases under 20 words).
Do NOT invent new lines. Find the ones already embedded in the writing.

Rank by: standalone power, shareability, the author's voice.

CHAPTER:
---
{chapter_text}
---

Return ONLY a JSON array of 5 strings. Example:
["The room went flat. That's your Known Character talking.", "You never create alone.", ...]"""

    try:
        from reader_board_v2 import call_api
        text = call_api(prompt, MEME_EXTRACT_SYSTEM, api_key, model, max_tokens=512)
        # Clean and parse
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        quotes = json.loads(text)
        if isinstance(quotes, list):
            return quotes[:5]
    except Exception as e:
        print(f"  Meme extraction error: {e}")
    return []


def score_meme_quotes(quotes):
    """Quick local scoring of extracted meme quotes."""
    scores = []
    for q in quotes:
        score = 0
        words = len(q.split())
        # Under 20 words
        if words <= 20:
            score += 2
        elif words <= 25:
            score += 1
        # Short and punchy (under 12 words = extra credit)
        if words <= 12:
            score += 1
        # Contains body truth markers
        body_words = ["chest", "gut", "breath", "body", "tighten", "stomach", "hands", "shoulders", "flat", "buzzing"]
        if any(w in q.lower() for w in body_words):
            score += 1
        # Contains protected domain vocabulary
        protected = ["known character", "tightener", "field memory", "corporate artist", "co-creation"]
        if any(s in q.lower() for s in protected):
            score += 1
        # Doesn't contain AI words
        ai_words = ["tapestry", "nuanced", "holistic", "journey", "authentic", "mindful", "unpack", "explore"]
        if not any(w in q.lower() for w in ai_words):
            score += 1
        scores.append(score)
    return scores


def display_meme_quotes(quotes, scores):
    """Pretty-print the meme quotes with scores."""
    print(f"\n    ┌─ MEME QUOTES ──────────────────────────")
    for i, (q, s) in enumerate(zip(quotes, scores)):
        stars = "★" * s + "☆" * (6 - s)
        words = len(q.split())
        print(f"    │  {i+1}. [{stars}] ({words}w) \"{q}\"")
    avg = sum(scores) / len(scores) if scores else 0
    total_under_20 = sum(1 for q in quotes if len(q.split()) <= 20)
    print(f"    │  Average: {avg:.1f}/6 | Under 20w: {total_under_20}/5")
    print(f"    └──────────────────────────────────────────")


# ─── Results Logging ────────────────────────────────────

def init_results():
    if not RESULTS_FILE.exists():
        header = "run_id\ttask\ttimestamp\tcombined_total\tcombined_max\tcombined_pct\tindustry_total\tindustry_max\treader_total\treader_max\twords\tstatus\ttop_flag\n"
        RESULTS_FILE.write_text(header)


def log_result(run_id, task_name, board_scores, word_count, status):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    top_flag = board_scores.get("all_flags", ["none"])[0][:60] if board_scores.get("all_flags") else "none"
    row = (
        f"{run_id}\t{task_name}\t{ts}\t"
        f"{board_scores['combined_total']}\t{board_scores['combined_max']}\t{board_scores['combined_pct']}\t"
        f"{board_scores['industry']['total']}\t{board_scores['industry']['max']}\t"
        f"{board_scores['reader']['total']}\t{board_scores['reader']['max']}\t"
        f"{word_count}\t{status}\t{top_flag}\n"
    )
    with open(RESULTS_FILE, "a") as f:
        f.write(row)


# ─── Main Loop ───────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Auto-Lyra Edit Loop v2: Reader Board Architecture")
    parser.add_argument("--task", required=True,
                        help=f"Merge task: {', '.join(MERGE_TASKS.keys())}")
    parser.add_argument("--max-experiments", type=int, default=0,
                        help="0 = NEVER STOP")
    parser.add_argument("--anthropic-key", default=os.environ.get("ANTHROPIC_API_KEY", ""))
    parser.add_argument("--editor-model", default="claude-sonnet-4-20250514",
                        help="Model for editing (default: Sonnet)")
    parser.add_argument("--judge-model", default="claude-haiku-4-5-20251001",
                        help="Model for reader board (default: Haiku)")
    args = parser.parse_args()

    api_key = args.anthropic_key
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY")
        sys.exit(1)

    if args.task not in MERGE_TASKS:
        print(f"ERROR: Unknown task '{args.task}'")
        print(f"Available: {', '.join(MERGE_TASKS.keys())}")
        sys.exit(1)

    task = MERGE_TASKS[args.task]

    # Load chapters
    chapters = load_chapters()
    if not chapters:
        sys.exit(1)

    chapter_texts = get_chapter_texts(chapters, task)
    if not chapter_texts:
        sys.exit(1)

    original_words = sum(len(t.split()) for t in chapter_texts.values())

    # Setup
    task_dir = EDITS_DIR / args.task
    task_dir.mkdir(parents=True, exist_ok=True)
    init_results()

    # Count total scoring dimensions
    industry_dims = sum(len(r["scores"]) for r in INDUSTRY_TABLE["readers"].values())
    reader_dims = sum(len(r["scores"]) for r in READER_TABLE["readers"].values())
    total_max = (industry_dims + reader_dims) * 6

    print("=" * 72)
    print(f"  AUTO-LYRA EDIT LOOP v2 — READER BOARD ARCHITECTURE")
    print(f"  Task: {args.task} → \"{task['title']}\"")
    print(f"  Chapters: {', '.join(task['chapters'])}")
    print(f"  Original: {original_words} words")
    print(f"  Editor: {args.editor_model}")
    print(f"  Reader Board: {args.judge_model}")
    print(f"  Industry Table: {len(INDUSTRY_TABLE['readers'])} readers, {industry_dims} dimensions")
    print(f"  Reader Table: {len(READER_TABLE['readers'])} readers, {reader_dims} dimensions")
    print(f"  Max score: {total_max} ({industry_dims * 6} industry + {reader_dims * 6} reader)")
    print(f"  L = x − x̂ where x̂ = AI editor contamination")
    print("=" * 72)
    print()

    # State
    current_best = None
    best_score = 0
    best_board_scores = None
    keep_count = 0
    discard_count = 0
    streak = 0
    experiment_num = 0
    board_history = []
    gate_reject_streak = 0  # Consecutive gate rejects (overcompression)
    last_gate_reason = ""   # Why the gate rejected last time

    # Check for existing best
    best_file = task_dir / "best.md"
    if best_file.exists():
        current_best = best_file.read_text()
        print(f"  Loaded existing best: {len(current_best.split())} words")
        print(f"  Re-scoring through reader board...")
        originals_text = "\n\n".join(f"=== {t} ===\n{txt}" for t, txt in chapter_texts.items())
        scores = score_both_boards(
            originals_text, current_best, task["instructions"],
            api_key, args.judge_model
        )
        if scores:
            best_score = scores["combined_total"]
            best_board_scores = scores
            print(f"\n  Existing best: {best_score}/{scores['combined_max']} ({scores['combined_pct']}%)")
        print()

    # ─── The Loop ─────────────────────────────────────────
    while True:
        experiment_num += 1
        if args.max_experiments > 0 and experiment_num > args.max_experiments:
            print(f"\n  Reached max experiments ({args.max_experiments}). Stopping.")
            break

        print(f"{'─' * 72}")
        print(f"  EXPERIMENT #{experiment_num}")
        print(f"{'─' * 72}")

        # ─── Step 1: Editor produces a merge ──────────────
        print(f"  Editor thinking... (streak: {streak})")

        temp = 0.7 if streak < 3 else 0.85 if streak < 10 else 0.95 if streak < 20 else 1.0

        prompt = build_editor_prompt_v2(
            task, chapter_texts, current_best,
            experiment_num, best_board_scores, streak, board_history,
            gate_reject_streak=gate_reject_streak,
            last_gate_reason=last_gate_reason,
            original_word_count=original_words,
        )

        result = call_model(
            prompt=prompt,
            system_prompt=EDITOR_SYSTEM,
            provider="claude",
            api_key=api_key,
            model=args.editor_model,
            temperature=temp,
            max_tokens=8192,
        )

        if result["error"]:
            print(f"  EDITOR ERROR: {result['error'][:100]}")
            time.sleep(2)
            continue

        edited = result["text"].strip()
        if not edited:
            print(f"  EMPTY RESPONSE — skipping")
            continue

        edit_words = len(edited.split())
        reduction = round((1 - edit_words / original_words) * 100, 1)
        print(f"  Edit: {edit_words} words ({reduction}% reduction)")

        # ─── Step 1.5: Compression check ────────────────
        # If the editor cut more than 55%, it's probably overcompressing.
        # Field Memories and body-truth passages need room to breathe.
        if reduction > 55:
            print(f"  ⚠ OVERCOMPRESSION: {reduction}% cut — stories need room to breathe")
            print(f"    Floor: ~{int(original_words * 0.45)} words. This edit: {edit_words} words.")

        # ─── Step 2: Quick checks ───────────────────────
        contamination = quick_contamination_check(edited)
        if contamination:
            print(f"  ⚠ CONTAMINATION: {contamination}")

        voice = quick_voice_check(edited)
        print(f"  Voice: body={voice['body_truth']} punches={voice['short_punches']} "
              f"protected={voice['protected_vocab']} you={voice['you_count']}")

        # Table read voice check
        tr = check_table_read_match(edited)
        print(f"  Table Read: {tr['summary']}")
        if tr["contamination_found"]:
            print(f"  ⚠ TABLE READ CONTAMINATION: {tr['contamination_found'][:5]}")
        if tr["voice_pair_violations"]:
            print(f"  ⚠ VOICE PAIR VIOLATIONS: {tr['voice_pair_violations'][:3]}")

        # ─── Step 2.5: LYRA GATE ───────────────────────
        # Fast pre-filter. If heavily contaminated or overcompressed, skip the board.
        gate_pass, gate_report = lyra_gate(edited, original_word_count=original_words)
        if not gate_pass:
            discard_count += 1
            streak += 1
            gate_reject_streak += 1
            last_gate_reason = gate_report['reason']
            run_id = f"E{experiment_num:03d}"
            print(f"\n  ✗ GATE REJECT | {run_id} | {gate_report['reason']}")
            print(f"    Saved 2 API calls ({gate_report['contamination_count']} contamination, "
                  f"TR score: {gate_report['table_read_score']})")
            print(f"    Best: {best_score}/{120 if best_board_scores else '?'} | "
                  f"Keep: {keep_count} | Discard: {discard_count}")
            if gate_reject_streak >= 10:
                print(f"    ⚠ {gate_reject_streak} consecutive gate rejects — editor is trapped")
            discard_file = task_dir / f"gate_reject_v{experiment_num:03d}.md"
            discard_file.write_text(edited)
            print()
            continue
        else:
            gate_reject_streak = 0  # Reset on pass

        print(f"  Lyra gate: PASS ({gate_report['reason']})")

        # ─── Step 2.7: Skip board if clearly duplicate ──────
        # If we have a best and the new edit is within 2% word count AND same
        # contamination profile, it's probably a minor rewording. Skip the
        # expensive board calls every other time on high streaks.
        if current_best and streak >= 10 and experiment_num % 2 == 0:
            best_words = len(current_best.split())
            word_diff = abs(edit_words - best_words) / max(best_words, 1) * 100
            if word_diff < 3:
                discard_count += 1
                streak += 1
                print(f"\n  ⚠ SKIP BOARD | Word count within {word_diff:.0f}% of best on high streak — saving 2 API calls")
                print(f"    Best: {best_score} | Keep: {keep_count} | Discard: {discard_count}")
                discard_file = task_dir / f"skip_v{experiment_num:03d}.md"
                discard_file.write_text(edited)
                print()
                continue

        # ─── Step 3: Reader Board scores (2 batched calls) ─
        print(f"  Convening reader board (batched)...")
        t0 = time.time()

        originals_text = "\n\n".join(f"=== {t} ===\n{txt}" for t, txt in chapter_texts.items())
        board_scores = score_both_boards(
            originals_text, edited, task["instructions"],
            api_key, args.judge_model
        )

        elapsed = time.time() - t0

        if not board_scores:
            print(f"  BOARD FAILED — skipping")
            discard_count += 1
            continue

        # Accumulate history (keep last 5 to save prompt tokens)
        board_history.append(board_scores)
        if len(board_history) > 5:
            board_history = board_history[-5:]

        new_score = board_scores["combined_total"]
        delta = new_score - best_score

        run_id = f"E{experiment_num:03d}"

        # ─── Step 4: Keep or discard ─────────────────────
        if new_score > best_score:
            # KEEP
            best_score = new_score
            best_board_scores = board_scores
            current_best = edited
            keep_count += 1
            streak = 0

            # Save
            best_file.write_text(edited)
            version_file = task_dir / f"v{experiment_num:03d}_{new_score}of{board_scores['combined_max']}.md"
            version_file.write_text(edited)

            log_result(run_id, args.task, board_scores, edit_words, "keep")

            print(f"\n  ✓ KEEP | {run_id} | {new_score}/{board_scores['combined_max']} ({board_scores['combined_pct']}%) | Δ={delta:+d}")

            # ─── Meme Quote Extraction (on KEEP only) ──────
            print(f"  Extracting meme quotes...")
            meme_quotes = extract_meme_quotes(edited, api_key, args.judge_model)
            if meme_quotes:
                meme_scores = score_meme_quotes(meme_quotes)
                display_meme_quotes(meme_quotes, meme_scores)
                # Save quotes alongside the chapter
                quotes_file = task_dir / f"quotes_v{experiment_num:03d}.json"
                quotes_file.write_text(json.dumps({
                    "experiment": experiment_num,
                    "score": new_score,
                    "quotes": meme_quotes,
                    "quote_scores": meme_scores,
                }, indent=2))
                # Also save latest best quotes
                best_quotes_file = task_dir / "best_quotes.json"
                best_quotes_file.write_text(json.dumps({
                    "chapter": task["title"],
                    "score": new_score,
                    "quotes": meme_quotes,
                    "quote_scores": meme_scores,
                }, indent=2))

        else:
            # DISCARD
            discard_count += 1
            streak += 1

            discard_file = task_dir / f"discard_v{experiment_num:03d}_{new_score}.md"
            discard_file.write_text(edited)

            log_result(run_id, args.task, board_scores, edit_words, "discard")

            print(f"\n  ✗ DISCARD | {run_id} | {new_score}/{board_scores['combined_max']} ({board_scores['combined_pct']}%) | Δ={delta:+d}")

        print(f"    Time: {elapsed:.0f}s | Words: {edit_words} ({reduction}% cut) | "
              f"Best: {best_score}/{board_scores['combined_max']} | Keep: {keep_count} | Discard: {discard_count}")

        if streak >= 5:
            print(f"\n  ⚠ {streak} experiments without improvement — increasing creativity")

        # Auto-stop on long plateaus (30 saves ~$3-5 vs 50+)
        if streak >= 30:
            print(f"\n{'=' * 72}")
            print(f"  AUTO-STOP: {streak} experiments without improvement.")
            print(f"  Best score: {best_score}/{board_scores['combined_max']} ({best_board_scores['combined_pct']}%)")
            print(f"  Best version saved to: {best_file}")
            print(f"  Total: {experiment_num} experiments, {keep_count} kept, {discard_count} discarded")
            if best_board_scores and best_board_scores.get("all_flags"):
                print(f"\n  REMAINING ISSUES (reader board flags on best version):")
                for flag in best_board_scores["all_flags"][:5]:
                    print(f"    - {flag[:80]}")
            print(f"\n  To continue from here, run again — it will load the best version.")
            print(f"{'=' * 72}")
            break

        print()


if __name__ == "__main__":
    main()
