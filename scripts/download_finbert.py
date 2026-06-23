"""Download ProsusAI/finbert from HuggingFace to data/models/finbert/."""
import os
from pathlib import Path

MODEL_DIR = Path(__file__).parents[1] / "data" / "models" / "finbert"

def download():
    print(f"Downloading FinBERT to {MODEL_DIR} ...")
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
    model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")
    tokenizer.save_pretrained(str(MODEL_DIR))
    model.save_pretrained(str(MODEL_DIR))
    print(f"FinBERT saved to {MODEL_DIR}")
    print("Model size: ~440MB")

if __name__ == "__main__":
    download()
