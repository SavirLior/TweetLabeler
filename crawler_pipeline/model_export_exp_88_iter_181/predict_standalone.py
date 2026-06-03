import argparse
import csv
import json

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer


def read_texts(args):
    if args.text:
        return args.text

    if args.input_csv:
        with open(args.input_csv, newline="", encoding="utf-8-sig") as csv_file:
            reader = csv.DictReader(csv_file)
            if args.text_column not in reader.fieldnames:
                raise ValueError(f"Column '{args.text_column}' was not found in {args.input_csv}")
            return [row[args.text_column] for row in reader]

    raise ValueError("Provide --text or --input-csv")


def main():
    parser = argparse.ArgumentParser(description="Run an exported Fusion BERT multiclass model.")
    parser.add_argument("--model-dir", default="model", help="Path to the exported model directory.")
    parser.add_argument("--text", action="append", help="Text to classify. Can be repeated.")
    parser.add_argument("--input-csv", help="CSV file with a text column.")
    parser.add_argument("--text-column", default="text", help="Text column name for --input-csv.")
    parser.add_argument("--output-csv", help="Optional CSV path for predictions.")
    parser.add_argument("--threshold", type=float, default=0.5, help="Threshold for multilabel predictions.")
    args = parser.parse_args()

    with open(f"{args.model_dir}/fusion_model_metadata.json", encoding="utf-8") as metadata_file:
        metadata = json.load(metadata_file)

    labels = metadata["labels"]
    max_length = int(metadata.get("max_length", 128))
    temperature = max(float(metadata.get("temperature", 2.0)), 1e-6)
    texts = read_texts(args)

    tokenizer = AutoTokenizer.from_pretrained(args.model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(args.model_dir)
    model.eval()

    rows = []
    with torch.inference_mode():
        for text in texts:
            encoded = tokenizer(
                text,
                return_tensors="pt",
                padding="max_length",
                truncation=True,
                max_length=max_length,
            )
            logits = model(**encoded).logits
            if metadata.get("prediction_type") == "multi_label":
                probs = torch.sigmoid(logits / temperature)[0].tolist()
                predicted_labels = [
                    label for label, probability in zip(labels, probs)
                    if probability >= args.threshold
                ]
                predicted_index = int(torch.argmax(logits, dim=1).item())
                row = {
                    "text": text,
                    "predicted_labels": ",".join(predicted_labels),
                    "top_label": labels[predicted_index],
                    "top_probability": probs[predicted_index],
                }
            else:
                probs = torch.softmax(logits / temperature, dim=1)[0].tolist()
                predicted_index = int(torch.argmax(logits, dim=1).item())
                row = {
                    "text": text,
                    "predicted_label": labels[predicted_index],
                    "predicted_probability": probs[predicted_index],
                }
            for label, probability in zip(labels, probs):
                row[label] = probability
            rows.append(row)

    if args.output_csv:
        with open(args.output_csv, "w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        print(json.dumps(rows, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
