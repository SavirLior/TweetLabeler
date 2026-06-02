# Fusion Exported Model

This archive contains a Hugging Face `AutoModelForSequenceClassification` model, tokenizer files, label metadata, and a small prediction script.

The model files are in `model/`.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-standalone.txt
```

On Linux/macOS, activate with `source .venv/bin/activate`.

## Predict One Or More Texts

```bash
python predict_standalone.py --text "example text"
python predict_standalone.py --text "first text" --text "second text"
```

## Predict From CSV

```bash
python predict_standalone.py --input-csv input.csv --text-column text --output-csv predictions.csv
```
