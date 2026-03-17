# Cross-Content Analysis

You've read summaries of all content pieces. Step back and identify patterns across the entire collection.

Look for:
1. **Repeated phrases** in 3+ chapters (exact wording, not thematic repetition)
2. **Overlapping chapters** that cover the same ground
3. **Pacing** — any movement feel long? Energy dip?
4. **Best 10 lines** — back cover and keynote candidates

## Output — JSON only

```json
{
  "repeated_phrases": [
    {"phrase": "exact wording", "chapters": ["Ch X", "Ch Y"], "suggestion": "keep in Ch X, trim from others"}
  ],
  "overlapping_chapters": [
    {"chapters": ["Ch X", "Ch Y"], "overlap": "what they both explain", "suggestion": "fix"}
  ],
  "pacing_notes": [
    {"location": "Movement X", "note": "what's happening"}
  ],
  "best_10_lines": [
    {"line": "exact quote", "chapter": "Ch X"}
  ],
  "overall_word_trim": "Total words reducible + rationale"
}
```
