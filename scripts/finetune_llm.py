"""
Fine-tune a local LLM on BlackBoxTrader trade outcome data using LoRA.

Usage:
    cd BlackBoxTrader
    python scripts/finetune_llm.py [--model MODEL] [--epochs N] [--min-quality 0.5]

This script:
  1. Reads training samples from the SQLite database (llm_training_sample table)
  2. Fine-tunes a small HuggingFace model with LoRA (parameter-efficient, runs on CPU/GPU)
  3. Saves the adapter to data/models/blackbox_llm_adapter/
  4. Optionally converts to GGUF for use with Ollama (requires llama.cpp)

Requirements (install separately if needed):
    pip install peft datasets accelerate bitsandbytes

Recommended base models (small, fast, instruction-tuned):
    - microsoft/Phi-3-mini-4k-instruct  (3.8B, best quality)
    - TinyLlama/TinyLlama-1.1B-Chat-v1.0 (1.1B, fastest)
    - Qwen/Qwen2-1.5B-Instruct           (1.5B, good balance)

The adapter is NOT a standalone model — it is applied on top of the base model.
Minimum recommended samples: 50 (more = better; quality > 0.5 preferred).
"""

import sys
import os
import argparse
import json
import sqlite3
from pathlib import Path

ROOT   = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "backend" / "blackbox.db"
OUT_DIR = ROOT / "data" / "models" / "blackbox_llm_adapter"


def load_training_data(min_quality: float = 0.5) -> list[dict]:
    """Load samples from SQLite, filter by quality threshold."""
    if not DB_PATH.exists():
        print(f"[ERROR] Database not found at {DB_PATH}")
        print("       Start BlackBoxTrader first so the DB is created.")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.execute(
        "SELECT instruction, response, quality, ticker, pnl_pct FROM llm_training_sample "
        "WHERE quality >= ? ORDER BY quality DESC",
        (min_quality,),
    )
    rows = cursor.fetchall()
    conn.close()

    samples = [
        {"instruction": row[0], "response": row[1], "quality": row[2]}
        for row in rows
    ]
    print(f"Loaded {len(samples)} training samples (min_quality={min_quality})")
    return samples


def format_for_instruction_tuning(sample: dict, tokenizer) -> dict:
    """Format sample into the model's chat template."""
    messages = [
        {"role": "system", "content": "You are a quantitative trading model that makes precise buy/sell/hold decisions."},
        {"role": "user",   "content": sample["instruction"]},
        {"role": "assistant", "content": sample["response"]},
    ]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    return {"text": text}


def finetune(
    base_model: str = "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
    epochs: int = 3,
    min_quality: float = 0.5,
    batch_size: int = 2,
    lr: float = 2e-4,
):
    # ── Import heavy dependencies ─────────────────────────────────────────
    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForCausalLM, TrainingArguments, Trainer, DataCollatorForLanguageModeling
        from peft import LoraConfig, get_peft_model, TaskType
        from datasets import Dataset
    except ImportError as e:
        print(f"[ERROR] Missing dependency: {e}")
        print("Install with: pip install peft datasets accelerate transformers torch")
        sys.exit(1)

    samples = load_training_data(min_quality)
    if len(samples) < 10:
        print(f"[WARNING] Only {len(samples)} samples — fine-tuning with very little data.")
        print("         Trade more to collect better training data.")
        if len(samples) == 0:
            print("[ERROR] No samples found. Cannot proceed.")
            sys.exit(1)

    print(f"\nLoading base model: {base_model}")
    print("(First run downloads from HuggingFace — may take a few minutes)\n")

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=torch.float32,  # float32 for CPU; use float16 if you have a GPU
        device_map="auto",
        trust_remote_code=True,
    )

    # ── LoRA config ───────────────────────────────────────────────────────
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=8,                # LoRA rank — 8 is a good default
        lora_alpha=16,
        target_modules=["q_proj", "v_proj"],  # attention layers
        lora_dropout=0.05,
        bias="none",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # ── Dataset ───────────────────────────────────────────────────────────
    formatted = [format_for_instruction_tuning(s, tokenizer) for s in samples]
    dataset   = Dataset.from_list(formatted)

    def tokenize(batch):
        return tokenizer(
            batch["text"],
            truncation=True,
            max_length=512,
            padding="max_length",
        )

    tokenized = dataset.map(tokenize, batched=True, remove_columns=["text"])
    tokenized = tokenized.train_test_split(test_size=0.1, seed=42)

    # ── Training ──────────────────────────────────────────────────────────
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(OUT_DIR),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        learning_rate=lr,
        warmup_ratio=0.1,
        weight_decay=0.01,
        logging_steps=10,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        report_to="none",   # no wandb/tensorboard needed
        fp16=False,         # set True if GPU available
        dataloader_num_workers=0,  # Windows compatibility
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["test"],
        data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False),
    )

    print(f"\nStarting LoRA fine-tuning on {len(tokenized['train'])} samples...")
    print(f"Epochs: {epochs}  |  Batch size: {batch_size}  |  LR: {lr}")
    print("(CPU training is slow — expect 10-60 min depending on dataset size)\n")

    trainer.train()

    # ── Save adapter ──────────────────────────────────────────────────────
    model.save_pretrained(str(OUT_DIR))
    tokenizer.save_pretrained(str(OUT_DIR))

    # Save metadata
    meta = {
        "base_model": base_model,
        "samples": len(samples),
        "epochs": epochs,
        "min_quality": min_quality,
        "adapter_path": str(OUT_DIR),
    }
    with open(OUT_DIR / "finetune_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n✓ Fine-tuning complete!")
    print(f"  Adapter saved to: {OUT_DIR}")
    print(f"\nTo use the adapter with Ollama:")
    print("  1. Install llama.cpp: pip install llama-cpp-python")
    print("  2. Run: python scripts/convert_to_gguf.py  (coming soon)")
    print("\nTo load the adapter directly in Python:")
    print("  from peft import PeftModel")
    print(f"  model = PeftModel.from_pretrained(base_model, '{OUT_DIR}')")


def main():
    parser = argparse.ArgumentParser(description="Fine-tune local LLM on BlackBoxTrader trade data")
    parser.add_argument("--model",       default="TinyLlama/TinyLlama-1.1B-Chat-v1.0", help="HuggingFace base model")
    parser.add_argument("--epochs",      type=int,   default=3,   help="Training epochs")
    parser.add_argument("--min-quality", type=float, default=0.5, help="Minimum sample quality (0-1)")
    parser.add_argument("--batch-size",  type=int,   default=2,   help="Training batch size")
    parser.add_argument("--lr",          type=float, default=2e-4, help="Learning rate")
    parser.add_argument("--list-samples", action="store_true", help="List sample counts and exit")

    args = parser.parse_args()

    if args.list_samples:
        samples = load_training_data(min_quality=0.0)
        by_quality = {"high (≥0.7)": 0, "medium (0.5-0.7)": 0, "low (<0.5)": 0}
        for s in samples:
            if s["quality"] >= 0.7: by_quality["high (≥0.7)"] += 1
            elif s["quality"] >= 0.5: by_quality["medium (0.5-0.7)"] += 1
            else: by_quality["low (<0.5)"] += 1
        print(f"\nTraining data summary:")
        print(f"  Total: {len(samples)}")
        for k, v in by_quality.items():
            print(f"  {k}: {v}")
        print(f"\nRecommendation: fine-tune when you have ≥50 high-quality samples.")
        return

    finetune(
        base_model=args.model,
        epochs=args.epochs,
        min_quality=args.min_quality,
        batch_size=args.batch_size,
        lr=args.lr,
    )


if __name__ == "__main__":
    main()
