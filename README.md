# ctxfit — will it fit in the context window?

[![tests](https://img.shields.io/badge/tests-19%2F19%20passing-2ea44f)]()
[![dependencies](https://img.shields.io/badge/dependencies-0-000000?style=flat&logoColor=00FF41)]()
![python](https://img.shields.io/badge/python-3.9%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

> **Pre-flight check for the AI-coding era.** Point ctxfit at the files you're about to paste into a prompt — source, docs, configs, scraped content — and it tells you, *before* you burn tokens: how many tokens it is, whether it fits the model's context window, what to drop if it doesn't, and roughly what the prompt will cost.

Zero dependencies. Pure Python 3.9+ stdlib. No network calls, no tokens spent, no API keys.

---

## Why

Every developer working with LLMs does this dance:

- You paste your project into ChatGPT/Claude/Cursor and get half of it silently ignored — the model never tells you the context was truncated.
- You build an agent, wire up a RAG bundle or a "read these files" tool, and only find out it's oversized at 2am in production.
- You switch models (Claude 200k -> local Llama 128k) and have to re-do all the mental arithmetic.
- You want a rough cost of "one full pass over this repo".

**ctxfit** turns that into one command, and its exit codes make it a CI gate: if a prompt bundle stops fitting the target model's window, your build fails instead of your agent hallucinating.

---

## Install

```bash
# from source
git clone https://github.com/mehulpatel23b-pixel/ctxfit.git
cd ctxfit
pip install .

# then
ctxfit --help
```

No third-party packages are required or installed — stdlib only.

---

## Usage

```bash
# does my agent's skill folder fit in Claude Sonnet 4.5 (default model)?
ctxfit ./skills/agent

# check against a specific model
ctxfit src/ docs/api.md --model gpt-5

# a model not in the catalog: give an explicit budget
ctxfit logs/ --model my-private-model --budget 32000

# fit matrix across every catalog model + JSON for scripting
ctxfit ./repo --compare --json > fit.json

# exclude noise, show more, reserve more for the reply
ctxfit . --exclude tests/ --exclude .github --top 40 --reserve-out 16384
```

### Real output (verified)

```
$ ctxfit ./site-seller --model claude-sonnet-4-5 --compare

ctxfit :: claude-sonnet-4-5
  budget        200,000 tokens (usable 195,904 after 4,096 reserved for output)
  total         8,818 tokens from 5 files
  usage         4.5% of usable budget
  est. cost     $0.0265 per prompt (approx, input only)
  verdict       [OK] FITS

  top 5 files by tokens
        6,218  code    scripts/generate_demo_site.py
          894  prose   SKILL.md
          832  code    scripts/check_gmail_replies.py
          684  code    scripts/send_outreach_email.py
          190  code    scripts/run.sh

  model matrix (this total across catalog windows):
    claude-haiku-4-5        200,000      4.5%  [FITS]
    claude-sonnet-4-5       200,000      4.5%  [FITS]
    deepseek-v3             128,000      7.1%  [FITS]
    gemini-2.5-pro       1,000,000      0.9%  [FITS]
    gpt-5                   400,000      2.2%  [FITS]
    gpt-5-mini              400,000      2.2%  [FITS]
    llama-3.3-70b           128,000      7.1%  [FITS]
    ...
```

And when it doesn't fit, ctxfit tells you exactly what to remove first:

```
  verdict       [OVER] OVER — over by 396,096 tokens

  to fit, drop (in order):
    -   520,000  docs/scraped_corpus.md  -> remaining 0
```

### Exit codes (CI gate)

| code | meaning |
|------|---------|
| 0    | everything fits the usable budget |
| 1    | total exceeds the usable budget (add files to the drop list) |
| 2    | runtime / IO error |
| 64   | usage error (unknown model without `--budget`, bad arguments) |

```yaml
# fail the build when the agent prompt bundle stops fitting
- run: ctxfit bundles/agent-context/ --model claude-sonnet-4-5
```

---

## Architecture

```
                 ┌─────────────────────────────────────────────┐
   paths ──────► │  estimator.py                               │
                 │  walk + skip junk dirs (.git, venv, node_  │
                 │  modules…), sniff binaries, classify each  │
                 │  file (code/data/prose), estimate tokens  │
                 │  via calibrated chars/word heuristics     │
                 └───────────────┬─────────────────────────-─┘
                                 │ per-file token counts
                                 ▼
                 ┌─────────────────────────────────────────────┐
                 │  catalog.py                                  │
                 │  model windows + prices → fits() verdict,  │
                 │  trim_plan() greedy drop list, cost_usd()   │
                 └───────────────┬──────────────────────────--─┘
                                 │ verdict + plan
                                 ▼
                 ┌─────────────────────────────────────────────┐
                 │  cli.py                                      │
                 │  argparse → text report / JSON, exit-code   │
                 │  gate, --compare matrix, --exclude filters  │
                 └─────────────────────────────────────────────┘
```

### Token estimation, honestly

There is no tokenizer here — by design. ctxfit estimates with a calibrated heuristic: English prose ≈ 4.0 chars/token, dense code ≈ 3.5, structured data (JSON/YAML) ≈ 3.2, each cross-checked against a words×1.3 bound and the max wins. On real-world source files this lands within roughly ±15% of tiktoken-style BPE counts, but the number is an **estimate** — leave headroom rather than budgeting to the last token (that's what `--reserve-out` is for).

### Project structure

```
ctxfit/
├── src/ctxfit/
│   ├── __init__.py      # version
│   ├── estimator.py     # walk, classify, binary sniff, token estimate
│   ├── catalog.py       # model windows, fit verdict, trim plan, cost
│   └── cli.py           # argparse CLI, text/JSON report, exit codes
├── tests/
│   └── test_ctxfit.py   # 19 tests: estimator, catalog, CLI, JSON mode
├── pyproject.toml       # pip install . → console script `ctxfit`
├── requirements.txt     # empty on purpose: zero dependencies
├── LICENSE              # MIT
└── README.md
```

---

## Real-world use cases

1. **Agent prompt engineering** — you're packing skill files + configs for an autonomous agent; run ctxfit first to know the bundle's exact shape and which files actually cost the most.
2. **CI gate for context bundles** — repos that maintain "AI context" folders (CLAUDE.md bundles, agent skills) fail the build when a doc edit silently pushes the bundle past the model window.
3. **Model migration math** — moving a whole 700k-token context pipeline from GPT-4.1 (1M window) to Claude (200k)? `--compare` shows instantly which parts survive.
4. **RAG / local-LLM sizing** — before chunking a corpus for embeddings or running a local 128k model, see whether the whole thing fits or you need retrieval at all.
5. **Cost awareness** — teams routinely paste the same 10k-token blob into chat 50 times a day; `est. cost` (rate × your actual usage) is the number that changes habits.
6. **Code review prompts** — "review these 12 files" is often beyond a small-context model; check the total before the model quietly reads only half of it.
7. **Log triage** — estimate whether today's error log fits in an LLM call, and which log files are eating the budget, before you paste.

---

## Honesty section

- Token counts are heuristic **estimates** (±15% typ.), not exact tokenizer output; leave a safety margin.
- Prices in the catalog are approximate input-cost figures for orientation, not a billing oracle — verify with your provider.
- Context windows are manufacturer-published limits; provider-side behavior (truncation, caching, reserved system prompts) can still bite you.
- ctxfit reads files locally and makes **no network calls**. It never sends your code anywhere.

## License

MIT © Mehul Patel
