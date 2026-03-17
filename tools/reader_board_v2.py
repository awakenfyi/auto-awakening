#!/usr/bin/env python3
"""
Evaluation Board v2 — Token-efficient multi-persona evaluation.

Three optimizations:
1. GATE FILTER: Auto-discard low-quality outputs before evaluation (0 tokens)
2. BATCHED EVALUATION: 2 API calls instead of 10 (all personas per board in one prompt)
3. TAILORED CONTEXT: Each evaluator only gets relevant context

Estimated token efficiency: 70-80% savings vs individual calls

Legacy tool. Use agent_loop.py instead.
Framework: Lyra Labs, 2026
"""

import json
import urllib.request
import urllib.error
import time
from voice_fingerprint import VOICE_SAMPLE, BANNED_PATTERNS, VOICE_MARKERS
from table_read_voice import (
    TABLE_READ_GOLD, VOICE_PAIRS, NEVER_IN_TABLE_READS,
    SPOKEN_PHRASES, check_table_read_match
)
from edit_judge import quick_contamination_check, quick_voice_check

# Re-export the board definitions for backward compatibility
from reader_board import INDUSTRY_TABLE, READER_TABLE


# ═══════════════════════════════════════════════════════════
# OPTIMIZATION 1: LYRA GATE
# ═══════════════════════════════════════════════════════════
# Pre-filter at regex speed. If the edit is clearly contaminated,
# don't waste 2 API calls scoring it.

def lyra_gate(edited_chapter, original_word_count=None):
    """
    Fast pre-filter. Returns (pass, report) tuple.
    pass=True means the chapter clears the gate and should be scored.
    pass=False means auto-discard — don't call the board.

    If original_word_count is provided, also checks for overcompression.
    """
    contamination = quick_contamination_check(edited_chapter)
    voice = quick_voice_check(edited_chapter)
    tr = check_table_read_match(edited_chapter)
    edit_words = len(edited_chapter.split())

    report = {
        "contamination": contamination,
        "contamination_count": len(contamination),
        "voice": voice,
        "table_read": tr,
        "table_read_score": tr["table_read_score"],
        "edit_words": edit_words,
    }

    # Gate rules:
    # 1. 3+ banned patterns = auto-discard (heavy contamination)
    if len(contamination) >= 3:
        report["gate"] = "FAIL"
        report["reason"] = f"Heavy contamination: {len(contamination)} banned patterns ({', '.join(contamination[:3])})"
        return False, report

    # 2. Any voice pair violations = auto-discard (AI rewrote the author's words)
    if tr["voice_pair_violations"]:
        report["gate"] = "FAIL"
        report["reason"] = f"Voice pair violation: {tr['voice_pair_violations'][0]}"
        return False, report

    # 3. 5+ table read contamination words = auto-discard
    if len(tr["contamination_found"]) >= 5:
        report["gate"] = "FAIL"
        report["reason"] = f"Table read contamination: {len(tr['contamination_found'])} words ({', '.join(tr['contamination_found'][:3])})"
        return False, report

    # 4. Zero body truth + zero short punches = voice is dead
    if voice["body_truth"] == 0 and voice["short_punches"] < 3:
        report["gate"] = "FAIL"
        report["reason"] = "Voice dead: no body truth, fewer than 3 short punches"
        return False, report

    # 5. Overcompression — if we cut more than 55% of the original, stories lost their room
    if original_word_count and original_word_count > 0:
        reduction = (1 - edit_words / original_word_count) * 100
        report["reduction_pct"] = round(reduction, 1)
        if reduction > 55:
            report["gate"] = "FAIL"
            report["reason"] = f"Overcompression: {reduction:.0f}% cut ({edit_words}w from {original_word_count}w) — Field Memories need room"
            return False, report

    report["gate"] = "PASS"
    report["reason"] = f"Clean: {len(contamination)} contamination, {tr['table_read_score']} table read score"
    return True, report


# ═══════════════════════════════════════════════════════════
# OPTIMIZATION 2: TAILORED CONTEXT PER READER
# ═══════════════════════════════════════════════════════════
# Instead of every reader getting everything, each gets only what they score on.

# Which readers need which context:
READER_CONTEXT_NEEDS = {
    # INDUSTRY TABLE
    "rick_rubin_reader":    {"needs_originals": False, "needs_voice_sample": True,  "needs_banned": False, "needs_table_read": False},
    "podcast_host":         {"needs_originals": False, "needs_voice_sample": False, "needs_banned": False, "needs_table_read": False, "needs_meme_context": True},
    "sixty_minutes_reporter": {"needs_originals": True,  "needs_voice_sample": False, "needs_banned": False, "needs_table_read": False},
    "world_class_editor":   {"needs_originals": True,  "needs_voice_sample": False, "needs_banned": False, "needs_table_read": False},
    "author_ear":           {"needs_originals": False, "needs_voice_sample": True,  "needs_banned": True,  "needs_table_read": True},
    # READER TABLE
    "stuck_vp":             {"needs_originals": False, "needs_voice_sample": False, "needs_banned": False, "needs_table_read": False},
    "burned_out_builder":   {"needs_originals": False, "needs_voice_sample": False, "needs_banned": False, "needs_table_read": False},
    "searching_creative":   {"needs_originals": False, "needs_voice_sample": False, "needs_banned": False, "needs_table_read": False},
    "skeptical_operator":   {"needs_originals": False, "needs_voice_sample": False, "needs_banned": False, "needs_table_read": False},
    "late_night_seeker":    {"needs_originals": False, "needs_voice_sample": False, "needs_banned": False, "needs_table_read": False},
}


def build_reader_block(reader_key, reader):
    """Build a single reader's scoring block for the batched prompt."""
    dims = reader["scores"]
    dim_rubrics = ""
    for dim in dims:
        rubric = reader[dim]
        dim_rubrics += f"  {dim} (0-6): {rubric['description']}\n"
        # Only include 6, 3, 0 anchor points to save tokens (not full 0-6 rubric)
        for level in ["6", "3", "0"]:
            if level in rubric:
                dim_rubrics += f"    {level} = {rubric[level]}\n"

    return f"""--- {reader['name']} ---
Archetype: {reader['archetype']}
Lens: {reader['lens']}
Test question: {reader['test_question']}
Flags: {', '.join(reader['flags_problems'][:2])}
Approves: {', '.join(reader['approves'][:2])}
Dimensions:
{dim_rubrics}"""


def build_batched_board_prompt(board, edited_chapter, original_chapters=None,
                                merge_instructions=None):
    """
    Build ONE prompt for an entire board (5 readers).
    Instead of 5 separate calls, one call scores all 5.
    """

    # Build reader blocks
    reader_blocks = ""
    reader_keys = list(board["readers"].keys())
    for rk in reader_keys:
        reader_blocks += build_reader_block(rk, board["readers"][rk]) + "\n"

    # Determine what shared context this board needs
    needs_originals = any(
        READER_CONTEXT_NEEDS.get(rk, {}).get("needs_originals", False)
        for rk in reader_keys
    )
    needs_voice = any(
        READER_CONTEXT_NEEDS.get(rk, {}).get("needs_voice_sample", False)
        for rk in reader_keys
    )
    needs_banned = any(
        READER_CONTEXT_NEEDS.get(rk, {}).get("needs_banned", False)
        for rk in reader_keys
    )
    needs_table_read = any(
        READER_CONTEXT_NEEDS.get(rk, {}).get("needs_table_read", False)
        for rk in reader_keys
    )
    needs_meme_context = any(
        READER_CONTEXT_NEEDS.get(rk, {}).get("needs_meme_context", False)
        for rk in reader_keys
    )

    # Build context sections (only what's needed)
    context = ""
    if needs_originals and original_chapters:
        context += f"\nORIGINAL CHAPTERS (for merge-seam and evidence checking):\n---\n{original_chapters}\n---\n"
    if merge_instructions:
        context += f"\nMERGE INSTRUCTIONS: {merge_instructions}\n"
    if needs_voice:
        context += f"\n{VOICE_SAMPLE}\n"
    if needs_banned:
        context += f"\nBANNED PATTERNS: {json.dumps(BANNED_PATTERNS[:15])}\n"
    if needs_table_read:
        pairs_str = "\n".join(f"  \"{m}\" → \"{a}\"" for m, a in VOICE_PAIRS[:8])
        context += f"\nTABLE READ VOICE PAIRS:\n{pairs_str}\n"
        context += f"\nNEVER IN TABLE READS: {json.dumps(NEVER_IN_TABLE_READS[:15])}\n"
    if needs_meme_context:
        context += """
MEME QUOTE REQUIREMENT: This chapter MUST contain 5+ standalone quotable lines.
A quotable line is under 20 words, works without ANY context, sounds spoken not written.
When scoring quotability: 6 = five or more lines you'd clip for a podcast title or social post.
Count the ACTUAL quotable lines in the chapter. If fewer than 5, the quotability score cannot exceed 3.
Examples of great meme quotes: "The room went flat.", "You never create alone.", "The cubicle is the studio."
"""

    # Build JSON output template
    json_template = "{\n"
    for rk in reader_keys:
        reader = board["readers"][rk]
        dims_str = ", ".join(f'"{d}": <0-6>' for d in reader["scores"])
        json_template += f'  "{rk}": {{{dims_str}, "total": <sum>, "flag": "<problem or none>", "highlight": "<best line>", "verdict": "<one sentence>"}},\n'
    json_template += "}"

    return f"""Score this chapter through {len(reader_keys)} reader perspectives simultaneously.
Each reader has their own lens, test question, and scoring dimensions.
Score INDEPENDENTLY for each reader — they see different things.

THE READERS:
{reader_blocks}

EDITED CHAPTER TO SCORE:
---
{edited_chapter}
---
{context}

Respond with ONLY this JSON (no markdown, no explanation):
{json_template}"""


BATCHED_SYSTEM = """You are simulating multiple reader personas simultaneously. Each persona has a specific identity, lens, and scoring criteria. Score the chapter independently for each persona — they should disagree where their perspectives differ.

Be specific in flags — quote the exact problematic phrase. Be specific in highlights — quote the exact line that works.

Output ONLY valid JSON. No markdown wrapping. No explanation outside the JSON."""


# ═══════════════════════════════════════════════════════════
# OPTIMIZATION 3: BATCHED API CALLS (2 instead of 10)
# ═══════════════════════════════════════════════════════════

def call_api(prompt, system, api_key, model, max_tokens=1024):
    """Make one API call via urllib."""
    payload = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.0,
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
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["content"][0]["text"].strip()


def parse_board_response(text, board):
    """Parse a batched board response into individual reader results."""
    # Clean markdown wrapping — handle multiple formats
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    # Sometimes the model wraps in just backticks or adds preamble
    if not text.startswith("{"):
        # Find the first { and last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end + 1]

    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        # Try to fix common JSON issues
        import re
        # Remove trailing commas before } or ]
        text = re.sub(r',\s*([}\]])', r'\1', text)
        # Replace single quotes
        text = text.replace("'", '"')
        # Truncated responses — try to close open braces
        open_braces = text.count("{") - text.count("}")
        if open_braces > 0:
            text = text + "}" * open_braces
        try:
            raw = json.loads(text)
        except:
            print(f"    JSON PARSE FAILED — raw response starts with: {text[:120]}...")
            return None

    results = {}
    board_total = 0
    board_max = 0

    for reader_key, reader in board["readers"].items():
        if reader_key in raw:
            rv = raw[reader_key]
            # Ensure dims
            for dim in reader["scores"]:
                if dim not in rv:
                    rv[dim] = 0
            rv["total"] = sum(rv.get(d, 0) for d in reader["scores"])
            rv["reader"] = reader["name"]
            rv["reader_key"] = reader_key
            rv["dims"] = {d: rv.get(d, 0) for d in reader["scores"]}
            results[reader_key] = rv
            board_total += rv["total"]
            board_max += len(reader["scores"]) * 6
        else:
            results[reader_key] = {"error": True, "reader": reader["name"]}
            board_max += len(reader["scores"]) * 6

    return {
        "board": board["name"],
        "total": board_total,
        "max": board_max,
        "pct": round(board_total / board_max * 100, 1) if board_max > 0 else 0,
        "readers": results,
    }


def score_board_batched(board, edited_chapter, original_chapters, merge_instructions,
                        api_key, model="claude-haiku-4-5-20251001", max_retries=2):
    """Score an entire board in ONE API call. Retries on parse failure."""
    prompt = build_batched_board_prompt(
        board, edited_chapter, original_chapters, merge_instructions
    )

    for attempt in range(max_retries):
        try:
            text = call_api(prompt, BATCHED_SYSTEM, api_key, model, max_tokens=1536)
            result = parse_board_response(text, board)
            if result:
                # Check if we got actual scores (not all errors)
                error_count = sum(1 for rv in result["readers"].values() if "error" in rv)
                if error_count == 0:
                    return result
                elif attempt < max_retries - 1:
                    print(f"    [{board['name']}] {error_count} readers failed — retrying ({attempt + 1}/{max_retries})...")
                    time.sleep(1)
                    continue
                else:
                    return result  # Return partial on last attempt
            elif attempt < max_retries - 1:
                print(f"    [{board['name']}] Parse failed — retrying ({attempt + 1}/{max_retries})...")
                time.sleep(1)
                continue
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"    [{board['name']}] ERROR: {e} — retrying ({attempt + 1}/{max_retries})...")
                time.sleep(1)
                continue
            print(f"    [{board['name']}] BATCH ERROR after {max_retries} attempts: {e}")

    return {
        "board": board["name"],
        "total": 0,
        "max": sum(len(r["scores"]) * 6 for r in board["readers"].values()),
        "pct": 0,
        "readers": {rk: {"error": True, "reader": r["name"]} for rk, r in board["readers"].items()},
    }


def score_both_boards(original_chapters, edited_chapter, merge_instructions,
                      api_key, model="claude-haiku-4-5-20251001"):
    """
    Score through BOTH boards using batched calls.
    2 API calls instead of 10.
    """

    print(f"    ┌─ INDUSTRY TABLE ─────────────────────")
    industry = score_board_batched(
        INDUSTRY_TABLE, edited_chapter, original_chapters,
        merge_instructions, api_key, model
    )
    for rk, rv in industry["readers"].items():
        if "error" not in rv:
            name = rv["reader"]
            dims = "  ".join(f"{d}={rv['dims'][d]}/6" for d in rv["dims"])
            print(f"    │  {name}: {rv['total']}/{len(rv['dims'])*6}  ({dims})")
            if rv.get("flag") and rv.get("flag") != "none":
                print(f"    │    flag: {str(rv['flag'])[:80]}")
        else:
            print(f"    │  {rv['reader']}: ERROR")
    print(f"    │  INDUSTRY TOTAL: {industry['total']}/{industry['max']} ({industry['pct']}%)")
    print(f"    └──────────────────────────────────────")

    print(f"    ┌─ READER TABLE ───────────────────────")
    reader = score_board_batched(
        READER_TABLE, edited_chapter, original_chapters,
        merge_instructions, api_key, model
    )
    for rk, rv in reader["readers"].items():
        if "error" not in rv:
            name = rv["reader"]
            dims = "  ".join(f"{d}={rv['dims'][d]}/6" for d in rv["dims"])
            print(f"    │  {name}: {rv['total']}/{len(rv['dims'])*6}  ({dims})")
            if rv.get("flag") and rv.get("flag") != "none":
                print(f"    │    flag: {str(rv['flag'])[:80]}")
        else:
            print(f"    │  {rv['reader']}: ERROR")
    print(f"    │  READER TOTAL: {reader['total']}/{reader['max']} ({reader['pct']}%)")
    print(f"    └──────────────────────────────────────")

    combined_total = industry["total"] + reader["total"]
    combined_max = industry["max"] + reader["max"]
    combined_pct = round(combined_total / combined_max * 100, 1) if combined_max > 0 else 0

    # Collect all flags and highlights
    all_flags = []
    all_highlights = []
    all_verdicts = []
    for board_result in [industry, reader]:
        for rk, rv in board_result["readers"].items():
            if "error" not in rv:
                if rv.get("flag") and rv.get("flag") != "none":
                    all_flags.append(f"[{rv['reader']}] {rv['flag']}")
                if rv.get("highlight"):
                    all_highlights.append(f"[{rv['reader']}] {rv['highlight']}")
                if rv.get("verdict"):
                    all_verdicts.append(f"[{rv['reader']}] {rv['verdict']}")

    return {
        "industry": industry,
        "reader": reader,
        "combined_total": combined_total,
        "combined_max": combined_max,
        "combined_pct": combined_pct,
        "all_flags": all_flags,
        "all_highlights": all_highlights,
        "all_verdicts": all_verdicts,
        "total_score": combined_total,
        "one_note": all_flags[0] if all_flags else "No flags",
        "best_moment": all_highlights[0] if all_highlights else "",
        "worst_moment": all_flags[0] if all_flags else "",
    }


# ═══════════════════════════════════════════════════════════
# CLI TEST
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Reader Board v2 — Token-efficient evaluation")
    print(f"Industry Table: {len(INDUSTRY_TABLE['readers'])} readers")
    print(f"Reader Table: {len(READER_TABLE['readers'])} readers")

    total_dims = sum(len(r["scores"]) for r in INDUSTRY_TABLE["readers"].values()) + \
                 sum(len(r["scores"]) for r in READER_TABLE["readers"].values())
    print(f"Total dimensions: {total_dims}")
    print(f"Max score: {total_dims * 6}")
    print(f"\nAPI calls per experiment: 2 (was 10)")
    print(f"Estimated token savings: 70-80%")

    # Test the Lyra gate
    print("\n--- LYRA GATE TEST ---")
    clean = "Your chest tightens. The room shifts. That's The Tightener."
    dirty = "It's worth noting that one should mindfully lean into the nuanced tapestry of the holistic journey."

    ok, report = lyra_gate(clean)
    print(f"Clean text: gate={'PASS' if ok else 'FAIL'} — {report['reason']}")

    ok, report = lyra_gate(dirty)
    print(f"Dirty text: gate={'PASS' if ok else 'FAIL'} — {report['reason']}")
