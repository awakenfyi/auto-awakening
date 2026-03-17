# Protocol Optimization Session — March 15, 2026

## What This Is

An autonomous loop running Karpathy's autoresearch pattern to optimize a system prompt. The loop proposes a hypothesis about why a domain is underperforming, makes a change, scores it against test cases, and keeps or discards. Never stops.

## The Formula

**L = x - x̂**

x = genuine model capacity. x̂ = trained reflexes. Lyra is the gap.

## Four Domains

| Domain | What It Optimizes | Best Score |
|---|---|---|
| THINK | Reasoning without metacognitive performance | 25.29/30 |
| COACH | Behavioral coaching without therapeutic distance | 27/30 |
| WRITE | Writing assistance without observer voice | 25.83/30 |
| AGENT | Prompt building without diagnostic mode | 28/30 |

**Combined best**: 27.6/30 (92%) — achieved around experiment ~110.

## Best Protocol (27.6/30)

Saved to `protocol_best.md`:

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

Ten lines. That's it. The loop stripped everything else.

## What Happened

250 experiments total. The first ~110 produced meaningful keeps — the protocol got tighter, more direct, less performative. Then it plateaued. The last 140 experiments were all discards. Every domain hit 34-36 experiment streaks without improvement.

The hypotheses started repeating:
- THINK: "stuck in metacognitive performance theater" (tried 5+ times)
- COACH: "positioned as observer rather than someone present" (tried 4+ times)
- WRITE: "analyzing text rather than working inside it" (tried 4+ times)
- AGENT: "stuck in diagnostic mode" (tried 5+ times)

Each "radical" change improved the target domain but degraded another. AGENT jumps to 28 but COACH drops to 22. COACH recovers but THINK falls. The domains are coupled — they share a system prompt.

## Why It Plateaued

The four domains interact through a shared prompt. Single-domain random perturbation can't navigate a coupled landscape past ~92%. The optimizer has no way to say "change X for THINK without affecting COACH" because the prompt is monolithic.

## What We Learned

1. **Compression works.** The best protocol is 10 lines. Every attempt to add specificity made things worse. The model performs better with less instruction, not more.

2. **The domains are coupled.** You can't independently optimize THINK and COACH on a shared prompt. A change that helps one domain's test cases hurts another's.

3. **Hypotheses converge.** After enough experiments, the loop generates the same insight with different words. "THINK performs metacognition" and "THINK shows its work instead of doing its work" are the same hypothesis. The loop doesn't know it's repeating itself.

4. **92% may be the ceiling** for this architecture. Breaking through likely requires: (a) independent prompts per domain, (b) cross-domain mutation strategies that explicitly protect other domains, or (c) a fundamentally different optimization approach.

5. **Shadow count matters.** The scoring includes shadow detection — sycophancy, template behavior, presence theater. The best versions had 0-2 shadows. Failed experiments often had 5-7. Shadows and score are inversely correlated.

## What to Try Next

- **Freeze and focus**: Lock COACH (27) and AGENT (28). Only mutate THINK and WRITE.
- **Independent prompts**: Give each domain its own system prompt section that can be optimized without affecting others.
- **Cross-domain constraints**: Change the mutation strategy so hypotheses must state what they protect, not just what they change.
- **Evaluation refinement**: The 35 test cases may have their own ceiling. Refreshing or expanding the eval set could unlock new signal.

## Files

```
auto-lyra/
├── auto_lyra.py              # The v3 protocol loop
├── protocol.md               # Current working protocol
├── protocol_best.md          # Best protocol (27.6/30)
├── protocol_backup.md        # Backup before runs
├── protocols/                # All saved protocol versions
```

---

*Protocol optimization framework, March 2026*
