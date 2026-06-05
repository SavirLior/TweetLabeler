# Database schema for the article

This file explains the article-ready schema diagram in `database_schema_article.svg`.

## Main schema to show in the article

The central database is MongoDB database `tweetlabeler`. For the article, the most important part is the annotation workflow:

- `users`: application users, with `username`, hashed `password`, and `role` (`admin` or `student`).
- `tweets`: the main annotation collection. Each document stores the tweet text, assignment state, student labels, final label, conflict metadata, round number, and optional Fusion/BERT model prediction metadata.

The key relationship is logical rather than relational: `tweets.assignedTo[]`, `tweets.annotations{username: label}`, `tweets.annotationFeatures{username: reasons[]}`, and `tweets.annotationTimestamps{username: timestamp}` all use `users.username`.

## Model fields

Fusion/BERT outputs are stored on tweet documents when imported into the annotation workflow:

- `model_decision`
- `modelProbabilities`

These fields allow the admin dashboard to compare model predictions with final human decisions.

## Crawler extension

The current system also includes crawler/discovery collections:

- `crawler_runs`: one crawler execution, including keywords, params, counts, and errors.
- `crawler_users`: normalized X/Twitter users discovered by the crawler, with current status and latest score.
- `crawler_user_runs`: per-user result for a specific crawler run.
- `crawler_tweet_evidence`: tweet-level evidence, including model label, confidence, probabilities, source metadata, and optional admin label.

For the article, this layer can be shown as an optional extension unless the paper discusses automatic user discovery in detail.

## Generated images

Use `database_schema_article.png` or `database_schema_article.svg` in the article.

![TweetLabeler MongoDB schema](database_schema_article.svg)
