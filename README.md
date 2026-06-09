# TweetLabeler

מערכת לתיוג ציוצים, יחד עם pipeline לזחילה מ-Twitter/X דרך Apify, הרצת מודל סיווג מקומי, ושמירת תוצאות ב-MongoDB.

## מה יש בפרויקט

- אתר תיוג: React/Vite בצד לקוח ו-Flask בצד שרת.
- MongoDB: שמירת נתוני האתר והזחלן.
- Crawler pipeline: שליפת ציוצים לפי מילות מפתח, סינון/ניקוי טקסט, פרדיקציה עם המודל, ואז deep dive על משתמשים חשודים.
- מודל מקומי שמחזיר את הלייבלים `Salafi jihadi`, `Salafi taklidi`, ו-`Irrelevant`.

## קובץ env

צריך קובץ `.env` בשורש הפרויקט:

```bash
MONGO_URI=your_mongo_connection_string
MONGO_DB_NAME=tweetlabeler
APIFY_API_TOKEN=your_apify_token
```

לא להעלות את `.env` לגיט. הוא מיועד לסודות מקומיים בלבד.

## התקנת תלויות

לתפעול האתר בלבד:

```bash
python3 -m pip install -r requirements.txt
npm install
```

לתפעול הזחלן והמודל:

```bash
python3 -m pip install -r requirements-crawler.txt
```

הפרדה חשובה: `requirements.txt` נשאר קל בשביל Docker של האתר. `requirements-crawler.txt` כולל `torch`, `transformers` ו-`apify-client`.

## הרצת האתר

עם Docker:

```bash
docker compose up --build
```

האתר יעלה ב:

```text
http://localhost:8080
```

לעצירה:

```bash
docker compose down
```

אם פורט `8080` תפוס:

```bash
lsof -i :8080
kill <PID>
```

או אם זה Docker מהפרויקט:

```bash
docker compose down
```

## הרצת הזחלן

לפני הרצה ודא ש-`.env` מלא, ושהמודל נמצא כאן:

```text
crawler_pipeline/model_export_exp_76_iter_153/model/
```

בתיקייה הזאת צריכים להיות קבצי HuggingFace, כולל למשל:

```text
config.json
tokenizer.json / tokenizer files
pytorch_model.bin
```

צריך לבחור מילות מפתח להרצה. `jihad` כאן היא דוגמה בלבד, ואפשר להחליף אותה בכל keywords שרוצים לבדוק.

הרצה רגילה לדוגמה עם מילת מפתח אחת:

```bash
python3 -m crawler_pipeline.twitter_crawler jihad
```

דוגמה עם כמה מילות מפתח:

```bash
python3 -m crawler_pipeline.twitter_crawler jihad shahid khilafah
```

אפשר להגביל ידנית את כמות ציוצי ה-keyword discovery בהרצה נקודתית:

```bash
python3 -m crawler_pipeline.twitter_crawler jihad --discovery-limit 15
```

מה שזה עושה:

1. שולף ציוצים לפי מילות המפתח שהוגדרו. ברירת המחדל היא עד 100 ציוצי discovery.
2. מנקה את הטקסט באותו פורמט של הסקריפט הישן `scrape_with_api`.
3. מריץ את המודל על ציוצי ה-discovery.
4. אם ציוץ discovery מסווג כ-`Salafi jihadi` בהסתברות מעל 70%, הזחלן מבצע deep dive על המשתמש. ציוץ שמסווג `Salafi taklidi` לא מפעיל deep dive.
5. לכל משתמש חשוד נשלפים עד 150 ציוצים raw מפרופיל המשתמש.
6. ציוצים בערבית, ריקים, או באורך עד 3 תווים אחרי ניקוי לא נכנסים למודל.
7. כל הציוצים התקינים שנשארו נכנסים למודל.
8. התוצאות נשמרות ב-MongoDB.

אפשר לשנות פרמטרים:

```bash
python3 -m crawler_pipeline.twitter_crawler jihad shahid --discovery-limit 50 --profile-limit 100 --min-profile-tweets 100 --min-positive-tweets 8 --ratio 0.12
```

ברירות המחדל המרכזיות:

- `discovery_limit = 100`
- `positive_ratio_threshold = 0.12`
- `min_positive_tweets = 8`
- `min_profile_evaluated_tweets = 100`
- `trigger_jihadi_probability_threshold = 0.70`
- `profile_overfetch_multiplier = 1.5`
- `profile raw fetch = 150` כש-`profile-limit` הוא 100

כל ברירות המחדל של הזחלן מרוכזות בקובץ:

```text
crawler_pipeline/config.py
```

למשל, כדי לשנות את כמות ציוצי ה-keyword discovery שמשתמשים בה כברירת מחדל, משנים שם את:

```python
DEFAULT_DISCOVERY_LIMIT = 100
```

משתמש יסווג `salafi_jihadi` רק אם כל התנאים מתקיימים:

- לפחות 100 ציוצי profile נקיים נכנסו למודל.
- לפחות 8 מתוכם סווגו `Salafi jihadi`.
- היחס החיובי הוא לפחות `0.12`.

אם למשתמש יש פחות מ-100 ציוצים נקיים שנכנסו למודל, הסטטוס שלו יהיה `insufficient_data`.

## מה נשמר במונגו

הזחלן משתמש ב-collections חדשים ונפרדים, ולא משנה את `tweets` ו-`users` של אתר התיוג.

- `crawler_runs`: ריצה מלאה של הזחלן, כולל keywords, params, counts, status, errors.
- `crawler_users`: המצב האחרון של כל משתמש שנבדק.
- `crawler_user_runs`: היסטוריה של deep dives לכל משתמש.
- `crawler_tweet_evidence`: ציוצים שנכנסו כראיות למשתמשים שעברו deep dive, כולל טקסט נקי, prediction, metadata קומפקטי, וסוג evidence.

לא נשמרים כל ציוצי ה-keyword discovery השליליים.

## בדיקות

בדיקת קומפילציה:

```bash
python3 -m py_compile crawler_pipeline/*.py
```

הרצת unit tests:

```bash
python3 -m unittest discover -s crawler_pipeline -p 'test_*.py'
```

בדיקת טעינת מודל קצרה:

```bash
python3 - <<'PY'
from crawler_pipeline.twitter_crawler import get_local_classifier

classifier = get_local_classifier()
print("Device:", classifier.device)
print("Labels:", classifier.labels)
print(classifier.predict(["This is a normal test tweet."])[0])
PY
```

## ניקוי מקום ב-Docker

אם מתקבלת שגיאה כמו `no space left on device`, בדרך כלל Docker Desktop מלא ב-build cache.

בדיקת נפח:

```bash
docker system df
```

ניקוי build cache:

```bash
docker builder prune
```
