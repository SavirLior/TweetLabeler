import pandas as pd

df = pd.read_csv("tweets_labels_detailed_2026-03-21 (1).csv")
df_filtered = df[['Text', 'Final Decision']]
df_filtered.to_csv("filtered_tweets.csv", index=False, encoding="utf-8-sig")