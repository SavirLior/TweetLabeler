import pandas as pd
from apify_client import ApifyClient
import re
import datetime

# ==========================================
# 1. הגדרות
# ==========================================

# ⚠️ אבטחה: החלף את הטוקן הזה בחדש שיצרת (הקודם נחשף)
APIFY_TOKEN = 'TOKEN'  

USERNAMES = [
   "MAkhtar59405"
]

MAX_TWEETS_PER_USER = 20

# ==========================================
# 2. פונקציות עזר
# ==========================================

def clean_text(text):
    if not isinstance(text, str):
        return ""
    text = re.sub(r'http\S+', '', text).strip()
    return text

def format_date(date_str):
    try:
        dt = datetime.datetime.strptime(date_str, '%a %b %d %H:%M:%S %z %Y')
        return dt.strftime('%d/%m/%Y %H:%M')
    except:
        return date_str

def get_best_text(tweet_obj):
    """
    הפונקציה שצדה את הטקסט הכי ארוך בתוך האובייקט
    """
    if not isinstance(tweet_obj, dict):
        return ""

    candidates = []
    # בדיקה בשדות הרגילים
    candidates.append(tweet_obj.get('fullText'))
    candidates.append(tweet_obj.get('text'))
    candidates.append(tweet_obj.get('full_text'))

    # בדיקה בתוך extended_tweet
    if 'extended_tweet' in tweet_obj:
        candidates.append(tweet_obj['extended_tweet'].get('full_text'))
    
    # בדיקה בתוך legacy
    if 'legacy' in tweet_obj:
        candidates.append(tweet_obj['legacy'].get('full_text'))
        candidates.append(tweet_obj['legacy'].get('text'))

    # סינון: זורקים None ובוחרים את הכי ארוך
    valid_texts = [t for t in candidates if t and isinstance(t, str)]
    
    if not valid_texts:
        return ""
    
    return max(valid_texts, key=len)

# ==========================================
# 3. הפעלת הרובוט של Apify (החלק שתוקן)
# ==========================================

print("🚀 מתחיל בהרצת הרובוט של Apify... זה יקח זמן בהתאם לכמות.")

try:
    client = ApifyClient(APIFY_TOKEN)

    # ✅ התיקון: שימוש ב-twitterHandles כפי שמופיע בממשק שעבד לך
    run_input = {
        "twitterHandles": USERNAMES,
        "maxItems": MAX_TWEETS_PER_USER * len(USERNAMES),
        "sort": "Latest",
        "tweetLanguage": "en",  # עוזר לסנן מראש שפות לא רלוונטיות
        "includeSearchTerms": False,
        "onlyImage": False,
        "onlyQuote": False,
        "onlyTwitterBlue": False,
        "onlyVerifiedUsers": False,
        "onlyVideo": False,
        "customMapFunction": "(object) => { return {...object} }"
    }

    print(f"📡 שולח בקשה עבור המשתמשים: {USERNAMES}")

    run = client.actor("apidojo/tweet-scraper").call(run_input=run_input)
    
    print("✅ הסריקה הסתיימה! מוריד נתונים...")
    
    dataset_items = client.dataset(run["defaultDatasetId"]).list_items().items

except Exception as e:
    print(f"❌ שגיאה בהרצת Apify: {e}")
    exit()

# ==========================================
# 4. עיבוד הנתונים (הלוגיקה שלך)
# ==========================================

processed_rows = []
skipped_arabic_count = 0

print(f"📂 מעבד {len(dataset_items)} ציוצים...")

for item in dataset_items:
    if not isinstance(item, dict):
        continue

    # --- פילטר שפה 1: ציוץ ראשי ---
    if item.get('lang') == 'ar':
        skipped_arabic_count += 1
        continue

    # --- זיהוי ריטוויט וטקסט ראשי ---
    rt_obj = item.get('retweet') or item.get('retweetedStatus') or item.get('retweeted_status') or item.get('retweetedTweet')

    # --- פילטר שפה 2: תוכן הריטוויט ---
    if rt_obj and isinstance(rt_obj, dict):
        if rt_obj.get('lang') == 'ar':
            skipped_arabic_count += 1
            continue

    # שליפת הטקסט
    final_user_text = ""
    is_retweet = False

    if rt_obj and isinstance(rt_obj, dict):
        final_user_text = get_best_text(rt_obj)
        is_retweet = True
    else:
        final_user_text = get_best_text(item)
        is_retweet = False

    if not final_user_text:
        continue

    # --- טיפול ב-Quote (ציטוט) ---
    combined_text = ""
    is_quote = False
    quote_obj = item.get('quote') or item.get('quoted_status') or item.get('quotedTweet')

    if quote_obj:
        quote_content = get_best_text(quote_obj)
        
        if quote_obj.get('lang') == 'ar': continue

        if quote_content:
            is_quote = True
            combined_text = (
                f'""{quote_content}"\n"\n'
                f'--------------\n\n'
                f'{final_user_text}'
            )

    # --- בניית הטקסט הסופי ---
    if not is_quote:
        if is_retweet:
            combined_text = f'[Retweeted]\n"{final_user_text}"'
        else:
            combined_text = final_user_text

    # ניקוי
    clean_combined_text = clean_text(combined_text)

    if clean_combined_text:
        user_name = item.get('author', {}).get('userName', 'Unknown')
        created_at = format_date(item.get('createdAt', ''))
        
        processed_rows.append({
            "username": user_name,
            "date": created_at,
            "full_display_text": clean_combined_text
        })

# ==========================================
# 5. שמירה לקבצים
# ==========================================

df = pd.DataFrame(processed_rows)

if df.empty:
    print("⚠️ לא נמצאו נתונים (או שהכל סונן).")
else:
    # קובץ 1: מלא
    file_full = "twitter_data_full.csv"
    df.to_csv(file_full, index=False, encoding='utf-8-sig')
    print(f"✅ נוצר קובץ מלא: {file_full}")

    # קובץ 2: טקסט בלבד לאתר
    file_text_only = "twitter_text_only_with_api.csv"
    df_text_only = df[['full_display_text']].rename(columns={'full_display_text': 'text'})
    
    df_text_only.to_csv(file_text_only, index=False, encoding='utf-8-sig')
    
    print("-" * 50)
    print(f"✅ נוצר קובץ לאתר: {file_text_only}")
    print(f"📥 סה\"כ נשמרו: {len(df)}")
    print(f"🗑️ סוננו (ערבית): {skipped_arabic_count}")
    print("-" * 50)