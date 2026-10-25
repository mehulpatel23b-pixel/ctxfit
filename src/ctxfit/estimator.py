"""Token estimation without a tokenizer.

Heuristic estimator calibrated against BPE-family tokenizers (GPT,
Claude, Llama, Mistral): English prose averages ~4.0 chars/token, dense
code ~3.5, structured data ~3.2. The estimate per file is the max of a
character-based and a word-based approximation, which keeps short
keyword-dense files from being under-counted. Documented accuracy:
typically within +/-15% of tiktoken counts for real-world source files.
"""

from __future__ import annotations

import math
import os

# characters-per-token ratios by file kind (lower = denser)
_CODE_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp",
    ".cc", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".cs", ".sh",
    ".bash", ".zsh", ".sql", ".css", ".scss",
}
_DATA_EXTS = {".json", ".yaml", ".yml", ".toml", ".xml", ".csv", ".ndjson"}
_PROSE_EXTS = {".md", ".txt", ".rst", ".adoc"}

_CHAR_RATIOS = {"code": 3.5, "data": 3.2, "prose": 4.0, "default": 3.8}

# directories never worth packing into a prompt
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".pytest_cache", "dist", "build", ".tox", ".eggs",
    "target", "vendor", ".next", ".idea", ".vscode",
}

_BINARY_SNIFF = 4096

_word_factor = 1.3  # avg tokens per English word for mixed text


def kind_for(path: str) -> str:
    """Classify a path as code / data / prose / default."""
    ext = os.path.splitext(path)[1].lower()
    if ext in _CODE_EXTS:
        return "code"
    if ext in _DATA_EXTS:
        return "data"
    if ext in _PROSE_EXTS:
        return "prose"
    return "default"


def looks_binary(path: str) -> bool:
    """Cheap sniff: NUL bytes in the head of the file mean binary."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(_BINARY_SNIFF)
    except OSError:
        return True
    return b"\x00" in head


def estimate_tokens(text: str, kind: str = "default") -> int:
    """Estimate the LLM token count of ``text`` (model-agnostic heuristic)."""
    if not text:
        return 0
    chars_ratio = _CHAR_RATIOS.get(kind, _CHAR_RATIOS["default"])
    by_chars = math.ceil(len(text) / chars_ratio)
    by_words = math.ceil(len(text.split()) * _word_factor)
    return max(1, max(by_chars, by_words))


def estimate_file(path: str) -> dict:
    """Estimate tokens for one file. Raises ValueError for binary files."""
    if looks_binary(path):
        raise ValueError(f"binary file: {path}")
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    kind = kind_for(path)
    return {
        "path": path,
        "kind": kind,
        "bytes": os.path.getsize(path),
        "lines": text.count("\n") + (1 if text else 0),
        "tokens": estimate_tokens(text, kind),
    }


def collect(paths, exclude_str=()):
    """Walk paths, skipping SKIP_DIRS and excluded substrings.

    Returns (files, skipped) where files is a list of estimate dicts
    sorted by token count (descending).
    """
    excl = tuple(exclude_str)
    files, skipped = [], []
    for base in paths:
        if os.path.isfile(base):
            try:
                files.append(estimate_file(base))
            except ValueError as exc:
                skipped.append(str(exc))
        elif os.path.isdir(base):
            for root, dirs, names in os.walk(base):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                for name in sorted(names):
                    full = os.path.join(root, name)
                    if excl and any(p in full for p in excl):
                        continue
                    try:
                        files.append(estimate_file(full))
                    except ValueError as exc:
                        skipped.append(str(exc))
        else:
            skipped.append(f"not found: {base}")
    files.sort(key=lambda f: (-f["tokens"], f["path"]))
    return files, skipped
