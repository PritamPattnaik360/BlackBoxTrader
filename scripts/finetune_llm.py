"""
Fine-tune BlackBoxTrader's local LLM using an Ollama Modelfile.

No HuggingFace, no LoRA, no GPU required.

How it works:
  1. Reads high-quality training samples from the SQLite database
  2. Selects the best examples (balanced wins/losses, highest quality)
  3. Builds an Ollama Modelfile with those examples embedded as few-shot pairs
  4. Runs 'ollama create blackbox-trader' to register the custom model locally
  5. The trading engine automatically switches to 'blackbox-trader' going forward

Usage:
    python scripts/finetune_llm.py
    python scripts/finetune_llm.py --min-quality 0.4 --max-examples 20
    python scripts/finetune_llm.py --list-samples
    python scripts/finetune_llm.py --reset   # revert to base llama3.2:3b
"""

import sys
import argparse
import json
import sqlite3
import subprocess
import tempfile
import os
from pathlib import Path

ROOT    = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "backend" / "blackbox.db"
OUT_DIR = ROOT / "data" / "models"

BASE_MODEL    = "llama3.2:3b"
CUSTOM_MODEL  = "blackbox-trader"

# ── Training data ─────────────────────────────────────────────────────────────

def load_training_data(min_quality: float = 0.4) -> list[dict]:
    if not DB_PATH.exists():
        print(f"[ERROR] Database not found: {DB_PATH}")
        print("        Start BlackBoxTrader first so the DB is created.")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT instruction, response, quality, was_correct, pnl_pct, ticker "
        "FROM llm_training_sample WHERE quality >= ? ORDER BY quality DESC",
        (min_quality,),
    ).fetchall()
    conn.close()

    samples = [
        {
            "instruction": r[0], "response": r[1],
            "quality": r[2], "was_correct": bool(r[3]),
            "pnl_pct": r[4], "ticker": r[5],
        }
        for r in rows
    ]
    print(f"Loaded {len(samples)} sample(s) with quality >= {min_quality}")
    return samples


def _select_examples(samples: list[dict], max_examples: int) -> list[dict]:
    """
    Pick a balanced set of wins and losses, ordered by quality descending.
    Deduplicates by ticker so no single stock dominates.
    """
    wins   = [s for s in samples if     s["was_correct"]]
    losses = [s for s in samples if not s["was_correct"]]

    # Deduplicate: keep best sample per ticker per outcome type
    def dedup(lst):
        seen = {}
        for s in lst:
            t = s["ticker"]
            if t not in seen or s["quality"] > seen[t]["quality"]:
                seen[t] = s
        return sorted(seen.values(), key=lambda x: -x["quality"])

    wins   = dedup(wins)
    losses = dedup(losses)

    # Balance wins and losses
    half = max_examples // 2
    chosen = wins[:half] + losses[:max_examples - half]
    return chosen[:max_examples]


# ── Modelfile builder ─────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are BlackBox Trader, a quantitative trading model fine-tuned on {n_samples} \
real signal outcomes from the BlackBoxTrader platform.

Your training data: {n_wins} winning signals, {n_losses} losing signals across \
diverse market conditions.

Your job: given market signal data for a ticker, output ONLY a JSON object — \
no prose, no markdown.

Signal interpretation guide (from your training):
- Combined score ≥ +0.30 with confirming momentum    → lean BUY
- Combined score ≤ -0.30 with bearish momentum       → lean SELL
- Trend line breakout above resistance               → strong BUY signal
- Trend line breakdown below support                 → strong SELL signal
- Score inside ±0.20 without strong NLP or trend     → HOLD

Always respond with ONLY this JSON:
{{"direction": "BUY" | "SELL" | "HOLD", "score": <float -1 to 1>, "confidence": <float 0 to 1>}}\
"""


def build_modelfile(examples: list[dict], all_samples: list[dict]) -> str:
    n_samples = len(all_samples)
    n_wins    = sum(1 for s in all_samples if s["was_correct"])
    n_losses  = n_samples - n_wins

    system = _SYSTEM_PROMPT.format(
        n_samples=n_samples,
        n_wins=n_wins,
        n_losses=n_losses,
    )

    lines = [
        f"FROM {BASE_MODEL}",
        "",
        "PARAMETER temperature 0.1",
        "PARAMETER num_predict 128",
        "",
        f'SYSTEM """{system}"""',
        "",
    ]

    for ex in examples:
        # Escape triple-quotes inside content (shouldn't exist but be safe)
        instr = ex["instruction"].replace('"""', '""\\"')
        resp  = ex["response"].replace('"""', '""\\"')
        lines.append(f'MESSAGE user """{instr}"""')
        lines.append(f'MESSAGE assistant """{resp}"""')
        lines.append("")

    return "\n".join(lines)


# ── Ollama integration ────────────────────────────────────────────────────────

def ollama_model_exists(name: str) -> bool:
    try:
        r = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=10,
        )
        return name in r.stdout
    except Exception:
        # Try full path
        try:
            ollama_exe = _find_ollama()
            r = subprocess.run(
                [ollama_exe, "list"],
                capture_output=True, text=True, timeout=10,
            )
            return name in r.stdout
        except Exception:
            return False


def _find_ollama() -> str:
    candidates = [
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama.exe"),
        r"C:\Program Files\Ollama\ollama.exe",
        "ollama",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return "ollama"


def create_ollama_model(modelfile_content: str) -> bool:
    """Write Modelfile to a temp file and run 'ollama create'."""
    ollama_exe = _find_ollama()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    modelfile_path = OUT_DIR / "Modelfile"
    modelfile_path.write_text(modelfile_content, encoding="utf-8")
    print(f"\nModelfile written to: {modelfile_path}")

    print(f"Running: ollama create {CUSTOM_MODEL} ...")
    try:
        result = subprocess.run(
            [ollama_exe, "create", CUSTOM_MODEL, "-f", str(modelfile_path)],
            capture_output=False,   # stream output to terminal
            timeout=300,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print("[ERROR] ollama create timed out after 5 minutes.")
        return False
    except FileNotFoundError:
        print(f"[ERROR] Ollama executable not found at '{ollama_exe}'.")
        print("        Make sure Ollama is installed and on your PATH.")
        return False


def delete_custom_model() -> bool:
    """Remove the blackbox-trader model from Ollama."""
    ollama_exe = _find_ollama()
    try:
        result = subprocess.run(
            [ollama_exe, "rm", CUSTOM_MODEL],
            capture_output=False, timeout=30,
        )
        return result.returncode == 0
    except Exception as e:
        print(f"[ERROR] Could not remove model: {e}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def finetune(min_quality: float = 0.4, max_examples: int = 20):
    samples = load_training_data(min_quality)

    if len(samples) < 10:
        print(f"[WARNING] Only {len(samples)} sample(s) — need at least 10 for useful tuning.")
        if len(samples) == 0:
            print("[ERROR] No samples found. Run BlackBoxTrader first to collect data.")
            sys.exit(1)

    examples = _select_examples(samples, max_examples)
    print(f"Selected {len(examples)} examples for Modelfile "
          f"({sum(1 for e in examples if e['was_correct'])} wins / "
          f"{sum(1 for e in examples if not e['was_correct'])} losses)")

    modelfile = build_modelfile(examples, samples)

    print(f"\nBuilding Ollama model '{CUSTOM_MODEL}' from {BASE_MODEL}...")
    print(f"Base: {BASE_MODEL}  |  Examples: {len(examples)}  |  "
          f"Total training samples: {len(samples)}")

    ok = create_ollama_model(modelfile)
    if ok:
        print(f"\n[OK] Model '{CUSTOM_MODEL}' created successfully.")
        print(f"     BlackBoxTrader will now use '{CUSTOM_MODEL}' for all signal decisions.")
        print(f"\n     To verify: ollama list")
        print(f"     To revert:  python scripts/finetune_llm.py --reset")
    else:
        print(f"\n[FAIL] Could not create '{CUSTOM_MODEL}'. Check Ollama is running.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Build a custom Ollama model fine-tuned on BlackBoxTrader signal data"
    )
    parser.add_argument(
        "--min-quality", type=float, default=0.4,
        help="Minimum sample quality to include (0–1, default 0.4)",
    )
    parser.add_argument(
        "--max-examples", type=int, default=20,
        help="Max few-shot examples to embed in the Modelfile (default 20)",
    )
    parser.add_argument(
        "--list-samples", action="store_true",
        help="Show training data summary and exit",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help=f"Delete '{CUSTOM_MODEL}' and revert to base {BASE_MODEL}",
    )

    args = parser.parse_args()

    if args.reset:
        print(f"Removing '{CUSTOM_MODEL}' from Ollama...")
        ok = delete_custom_model()
        print("[OK] Reverted to base model." if ok else "[FAIL] Could not remove model.")
        return

    if args.list_samples:
        samples = load_training_data(min_quality=0.0)
        wins    = sum(1 for s in samples if s["was_correct"])
        losses  = len(samples) - wins
        high    = sum(1 for s in samples if s["quality"] >= 0.7)
        mid     = sum(1 for s in samples if 0.4 <= s["quality"] < 0.7)
        low     = sum(1 for s in samples if s["quality"] < 0.4)
        print(f"\nTraining data summary:")
        print(f"  Total:              {len(samples)}")
        print(f"  Wins / Losses:      {wins} / {losses}")
        print(f"  High quality (>=0.7):    {high}")
        print(f"  Mid  quality (0.4-0.7): {mid}")
        print(f"  Low  quality (<0.4):    {low}")
        has_custom = ollama_model_exists(CUSTOM_MODEL)
        print(f"\n  Custom model '{CUSTOM_MODEL}' in Ollama: {'YES' if has_custom else 'NO'}")
        print(f"\n  Ready to fine-tune: {'YES' if len(samples) >= 10 else 'NO - need 10+ samples'}")
        return

    finetune(min_quality=args.min_quality, max_examples=args.max_examples)


if __name__ == "__main__":
    main()
