import csv
from pathlib import Path


PROCESSED_CSVS_DIR = Path(__file__).resolve().parent / "processed_csvs"


def count_tweets(csv_path: Path) -> int:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.reader(csv_file)
        next(reader, None)
        return sum(1 for row in reader if row)


def main() -> None:
    if not PROCESSED_CSVS_DIR.exists():
        raise FileNotFoundError(f"Directory not found: {PROCESSED_CSVS_DIR}")

    csv_files = sorted(PROCESSED_CSVS_DIR.glob("*.csv"))
    if not csv_files:
        print(f"No CSV files found in {PROCESSED_CSVS_DIR}")
        return

    total_rows = 0
    for csv_path in csv_files:
        tweet_count = count_tweets(csv_path)
        total_rows += tweet_count
        print(f"{csv_path.name}: {tweet_count}")

    print(f"Total tweets: {total_rows}")


if __name__ == "__main__":
    main()
