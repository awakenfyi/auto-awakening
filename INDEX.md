# Auto-Awakening — File Index

**Generated results** (outputs/ and working directories) are not tracked in git.

## Core Framework

```
auto-awakening/
  agent_loop.py              Main agent loop engine (worker + gate + board + controller)

  configs/                   JSON configuration files
    review.json              Review-mode preset
    loop.json                Loop-mode preset
    optimizer.json           Protocol optimization preset

  prompts/                   Markdown system prompts for workers and boards
    reviewer.md              Review-pass system prompt
    cross_chapter_analysis.md Cross-chapter analysis prompt
    editor.md                Content editor system prompt
    evaluator.md             Board evaluation system prompt
    judge.md                 Quality scoring rubric
    mutator.md               Prompt mutation system prompt

  evals/                     Evaluation test sets (JSON)
    evals.json               Core evaluation set
    evals_v3.json            Extended evaluations
    evals_v5.json            Categorized efficiency evaluations

  tools/                     Helper scripts (deprecated but available)
    reviewer.py              Review pass (with resume support)
    edit_loop.py             Content improvement loop
    protocol_optimizer.py    Protocol optimization loop
    evaluator.py             Board evaluation

  logs/                      Run logs and session files
  archive/                   Previous versions and backups
  docs/                      Documentation
    README.md                Getting started
    ARCHITECTURE.md          Technical design
    AUTO_LYRA_SESSION.md     Protocol optimization research notes
```
