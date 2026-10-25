"""Model catalog: context windows and approximate input prices.

Context windows are the manufacturer-published limits. Prices are
approximate USD per 1M *input* tokens, clearly flagged as estimates in
all output — re-check against your provider's pricing page before
billing decisions. The catalog is data, not a network call: edit it,
pass --model with a --budget override, or use --compare for all models.
"""

from __future__ import annotations

DEFAULT_RESERVE_OUT = 4096  # tokens reserved for the model's reply

MODELS = {
    # name: (context window tokens, approx $/1M input tokens)
    "gpt-5": (400_000, 1.25),
    "gpt-5-mini": (400_000, 0.25),
    "gpt-4.1": (1_000_000, 2.00),
    "claude-sonnet-4-5": (200_000, 3.00),
    "claude-opus-4-1": (200_000, 15.00),
    "claude-haiku-4-5": (200_000, 1.00),
    "gemini-2.5-pro": (1_000_000, 1.25),
    "gemini-2.5-flash": (1_000_000, 0.30),
    "llama-3.3-70b": (128_000, None),
    "deepseek-v3": (128_000, 0.27),
    "mistral-large-2": (128_000, 2.00),
}


def resolve(model: str, budget_override=None):
    """Return (model_name, budget, price). Unknown model without an
    explicit budget override raises KeyError."""
    if model not in MODELS and budget_override is None:
        raise KeyError(
            f"unknown model '{model}'. Known: {', '.join(sorted(MODELS))} "
            f"(or pass an explicit --budget)."
        )
    window, price = MODELS.get(model, (0, None))
    budget = int(budget_override) if budget_override else window
    return model, budget, price


def fits(budget: int, tokens: int, reserve_out: int = DEFAULT_RESERVE_OUT) -> dict:
    """Verdict for one model against one total."""
    usable = max(0, budget - reserve_out)
    free = usable - tokens
    return {
        "budget": budget,
        "reserve_out": reserve_out,
        "usable": usable,
        "tokens": tokens,
        "free": free,
        "status": "FITS" if free >= 0 else "OVER",
        "over_by": max(0, -free),
        "usage_pct": round(100.0 * tokens / usable, 1) if usable else float("inf"),
    }


def trim_plan(files, budget: int, reserve_out: int = DEFAULT_RESERVE_OUT):
    """Greedy plan: files are sorted by tokens descending; keep proposing
    whole-file drops until the remainder fits.

    Returns list of dicts: {path, tokens, remaining} — the drop candidates
    in order. Empty list means everything already fits.
    """
    total = sum(f["tokens"] for f in files)
    plan = []
    remaining = total
    if remaining <= budget - reserve_out:
        return plan
    for f in files:  # files arrive sorted desc by tokens
        plan.append({"path": f["path"], "tokens": f["tokens"],
                     "remaining": remaining - f["tokens"]})
        remaining -= f["tokens"]
        if remaining <= budget - reserve_out:
            break
    return plan


def cost_usd(tokens: int, price) -> float | None:
    """Approximate prompt cost; None when price is unknown."""
    if price is None:
        return None
    return round(tokens / 1_000_000 * price, 6)
