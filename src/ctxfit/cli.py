"""CLI: ctxfit [paths] --model claude-sonnet-4-5

Exit codes (CI gate):
  0  everything fits the budget
  1  total exceeds the usable budget
  2  runtime/IO error
  64 usage error (bad arguments, unknown model without --budget)
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .catalog import (DEFAULT_RESERVE_OUT, MODELS, cost_usd, fits,
                      resolve, trim_plan)
from .estimator import collect


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ctxfit",
        description="Pre-flight check: will these files fit in your LLM's "
                    "context window? Zero dependencies, no tokens spent.")
    p.add_argument("paths", nargs="+", metavar="PATH",
                   help="files and/or directories to scan")
    p.add_argument("-m", "--model", default="claude-sonnet-4-5",
                   help=f"model to check against (default: claude-sonnet-4-5). "
                        f"Known: {', '.join(sorted(MODELS))}")
    p.add_argument("-b", "--budget", type=int, default=None,
                   help="override the context window (tokens) for unknown models")
    p.add_argument("--compare", action="store_true",
                   help="show a fit matrix for every model in the catalog")
    p.add_argument("--reserve-out", type=int, default=DEFAULT_RESERVE_OUT,
                   help=f"tokens reserved for the model reply "
                        f"(default: {DEFAULT_RESERVE_OUT})")
    p.add_argument("--exclude", action="append", default=[],
                   metavar="SUBSTR",
                   help="skip paths containing this substring (repeatable)")
    p.add_argument("--top", type=int, default=15,
                   help="how many largest files to list (default: 15)")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--version", action="version", version=f"ctxfit {__version__}")
    return p


def _text_report(payload):
    model, verdict = payload["model"], payload["fit"]
    lines = []
    lines.append(f"ctxfit :: {model}")
    lines.append(f"  budget        {verdict['budget']:,} tokens "
                 f"(usable {verdict['usable']:,} after {verdict['reserve_out']:,} reserved for output)")
    lines.append(f"  total         {verdict['tokens']:,} tokens "
                 f"from {len(payload['files'])} files")
    lines.append(f"  usage         {verdict['usage_pct']}% of usable budget")
    cost = payload["cost_usd"]
    lines.append(f"  est. cost     ${cost:.4f} per prompt (approx, input only)"
                 if cost is not None else
                 "  est. cost     n/a (price unknown for this model)")
    lines.append(f"  verdict       [{'OK' if verdict['status'] == 'FITS' else 'OVER'}] "
                 f"{verdict['status']}"
                 + (f" — over by {verdict['over_by']:,} tokens" if verdict["status"] == "OVER" else ""))
    lines.append("")
    lines.append(f"  top {min(payload['top'], len(payload['files']))} files by tokens")
    for f in payload["files"][:payload["top"]]:
        lines.append(f"    {f['tokens']:>9,}  {f['kind']:<7} {f['path']}")
    if payload["drop_plan"]:
        lines.append("")
        lines.append("  to fit, drop (in order):")
        for d in payload["drop_plan"]:
            lines.append(f"    - {d['tokens']:>9,}  {d['path']}"
                         f"  -> remaining {d['remaining']:,}")
    if payload["skipped"]:
        lines.append("")
        lines.append(f"  skipped: {len(payload['skipped'])} (binary/missing)")
    if payload["matrix"]:
        lines.append("")
        lines.append("  model matrix (this total across catalog windows):")
        for row in payload["matrix"]:
            flag = "FITS" if row["status"] == "FITS" else "OVER"
            lines.append(f"    {row['model']:<20} {row['budget']:>10,}  "
                         f"{row['usage_pct']:>7}%  [{flag}]")
    return "\n".join(lines)


def run(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        model, budget, price = resolve(args.model, args.budget)
        files, skipped = collect(args.paths, args.exclude)
    except KeyError as exc:
        print(f"ctxfit: {exc}", file=sys.stderr)
        return 64
    except OSError as exc:
        print(f"ctxfit: {exc}", file=sys.stderr)
        return 2

    total = sum(f["tokens"] for f in files)
    verdict = fits(budget, total, args.reserve_out)
    payload = {
        "model": model,
        "files": files,
        "top": args.top,
        "skipped": skipped,
        "fit": verdict,
        "cost_usd": cost_usd(total, price),
        "drop_plan": trim_plan(files, budget, args.reserve_out),
        "matrix": [],
    }
    if args.compare:
        for name in sorted(MODELS):
            w, pr = MODELS[name]
            pv = fits(w, total, args.reserve_out)
            payload["matrix"].append({
                "model": name, "budget": w, "tokens": total,
                "status": pv["status"], "usage_pct": pv["usage_pct"],
                "cost_usd": cost_usd(total, pr),
            })

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(_text_report(payload))
    return 0 if verdict["status"] == "FITS" else 1


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
