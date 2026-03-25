import pandas as pd

df = pd.read_csv("tweets_from_the_site.csv")
df_filtered = df[['Text', 'Final Decision']]
df_filtered.to_csv("filtered_tweets.csv", index=False, encoding="utf-8-sig")