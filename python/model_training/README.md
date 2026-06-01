# Tweet Classifier Training

Local training pipeline for the three final labels:

- `Irrelevant`
- `Salafi jihadi`
- `Salafi taklidi`

The goal is to optimize for `Salafi jihadi` recall while tracking precision, macro F1, and confusion with `Salafi taklidi`.

## 1. Prepare Data

For the final manually resolved `ELI + site5` dataset:

```bash
python3 python/model_training/prepare_final_dataset.py
```

Outputs are written to `python/model_training/data_final/`.

Current final split:

- train: 1459 rows
- validation: 258 rows
- test: 429 rows
- canonical labels: `Irrelevant=1176`, `Salafi taklidi=581`, `Salafi jihadi=389`
- no blank labels and no repeated normalized text with conflicting labels

For the older raw five-file site dataset:

```bash
python3 python/model_training/prepare_dataset.py
```

Outputs are written to `python/model_training/data/`:

- `train.csv`
- `validation.csv`
- `test.csv`
- `canonical_dataset.csv`
- `label_conflicts_for_review.csv`
- `dataset_summary.json`

The split is stratified by label and grouped by `normalized_text` to prevent leakage.
`model_text` contains Twitter-style preprocessing: URLs become `HTTPURL`, and mentions become `@USER`.

## 2. Install ML Dependencies

```bash
python3 -m pip install -r python/model_training/requirements-ml.txt
```

## 3. Train Baseline

```bash
python3 python/model_training/train_baseline.py --run-name baseline_logistic_v1
```

Artifacts are written to `python/model_training/runs/<run_name>/`.
For logistic regression, the run also tunes a `Salafi jihadi` threshold on validation with default target recall `0.80` and minimum precision `0.60`, then applies it to test.

## 4. Train Transformer

Recommended first GPU run on the final resolved dataset:

```bash
python3 python/model_training/train_transformer.py \
  --data-dir python/model_training/data_final \
  --run-name twitter_roberta_final_v1 \
  --model-name cardiffnlp/twitter-roberta-base \
  --jihadi-weights 1.4,1.6,1.8,2.0 \
  --min-precision 0.55 \
  --target-recall 0.80 \
  --max-length 256 \
  --epochs 4 \
  --learning-rate 2e-5 \
  --batch-size 8 \
  --eval-batch-size 16
```

If the GPU has enough memory, try `--batch-size 16 --eval-batch-size 32`.

Check whether PyTorch sees the GPU:

```bash
python3 -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no cuda')"
```

Generic command:

```bash
python3 python/model_training/train_transformer.py --run-name twitter_roberta_v1
```

Default model: `cardiffnlp/twitter-roberta-base`.

Fallback if the Twitter model is unavailable:

```bash
python3 python/model_training/train_transformer.py --run-name roberta_v1 --model-name roberta-base
```

The script sweeps `Salafi jihadi` weights `1.6,2.0,2.4,2.8`, tunes a `Salafi jihadi` threshold for each candidate on validation, selects the best checkpoint by thresholded validation `Salafi jihadi F2` subject to precision `>=0.60`, and evaluates the selected model once on test.

Smoke test without full training:

```bash
python3 python/model_training/train_transformer.py \
  --run-name transformer_smoke \
  --jihadi-weights 1.8 \
  --max-steps 1
```

## 5. Predict a CSV

```bash
python3 python/model_training/predict_csv.py \
  --model-dir python/model_training/runs/twitter_roberta_v1/jihadi_weight_2_10/best_model \
  --input-csv input.csv \
  --text-column text \
  --jihadi-threshold 0.35 \
  --output-csv predictions.csv
```

By default, prediction also applies Twitter preprocessing to the input text. Use `--no-twitter-preprocess` only when the input column is already normalized.

## 6. Error Analysis

```bash
python3 python/model_training/analyze_errors.py \
  --predictions-csv python/model_training/runs/baseline_logistic_v2/test_predictions.csv \
  --output-dir python/model_training/runs/baseline_logistic_v2/error_analysis
```

For thresholded decisions:

```bash
python3 python/model_training/analyze_errors.py \
  --predictions-csv python/model_training/runs/baseline_logistic_v2/test_threshold_predictions.csv \
  --prediction-column threshold_prediction \
  --output-dir python/model_training/runs/baseline_logistic_v2/threshold_error_analysis
```
