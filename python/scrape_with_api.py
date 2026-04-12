import pandas as pd
from apify_client import ApifyClient
import re
import datetime

APIFY_TOKEN = "TOKEN"
USERNAMES = [
"@mk_muwahid",
"@ImamZayd",
"@Alien_Zaki",
"@james3562675626",
"@AbuIdrees",
"@SeekIstighfar",
"@zeyyxx_",
"@mk_muwahid",
"@bintabdirahman2",


]

MAX_TWEETS_PER_USER = 50

# ==========================================
# 2. Helper Functions
# ==========================================

def clean_text(text):
    if not isinstance(text, str):
        return ""
    
    # Remove URLs
    text = re.sub(r'http\S+', '', text).strip()
    
    # Remove [Retweeted] tag
    text = re.sub(r'\[Retweeted\]', '', text, flags=re.IGNORECASE)
    
    # Remove emojis and non-English characters (keep only ASCII)
    text = text.encode('ascii', 'ignore').decode('ascii')
    
    return text.strip()

def format_date(date_str):
    try:
        dt = datetime.datetime.strptime(date_str, '%a %b %d %H:%M:%S %z %Y')
        return dt.strftime('%d/%m/%Y %H:%M')
    except:
        return date_str

def get_best_text(tweet_obj):
    """
    Function that catches the longest text within the object
    """
    if not isinstance(tweet_obj, dict):
        return ""

    candidates = []
    # Check standard fields
    candidates.append(tweet_obj.get('fullText'))
    candidates.append(tweet_obj.get('text'))
    candidates.append(tweet_obj.get('full_text'))

    # Check inside extended_tweet
    if 'extended_tweet' in tweet_obj:
        candidates.append(tweet_obj['extended_tweet'].get('full_text'))
    
    # Check inside legacy
    if 'legacy' in tweet_obj:
        candidates.append(tweet_obj['legacy'].get('full_text'))
        candidates.append(tweet_obj['legacy'].get('text'))

    # Filtering: discard None and pick the longest one
    valid_texts = [t for t in candidates if t and isinstance(t, str)]
    
    if not valid_texts:
        return ""
    
    return max(valid_texts, key=len)

# ==========================================
# 3. Running the Apify Actor (Fixed Part)
# ==========================================

print("🚀 Starting the Apify actor... This will take time depending on the amount.")

try:
    client = ApifyClient(APIFY_TOKEN)

    # ✅ Fix: using twitterHandles as it appears in the interface that worked for you
    run_input = {
        "twitterHandles": USERNAMES,
        "maxItems": MAX_TWEETS_PER_USER * len(USERNAMES),
        "sort": "Latest",
        "tweetLanguage": "en",  # Helps pre-filter irrelevant languages
        "includeSearchTerms": False,
        "onlyImage": False,
        "onlyQuote": False,
        "onlyTwitterBlue": False,
        "onlyVerifiedUsers": False,
        "onlyVideo": False,
        "customMapFunction": "(object) => { return {...object} }"
    }

    print(f"📡 Sending request for users: {USERNAMES}")

    run = client.actor("apidojo/tweet-scraper").call(run_input=run_input)
    
    print("✅ Scraping finished! Downloading data...")
    
    dataset_items = client.dataset(run["defaultDatasetId"]).list_items().items

except Exception as e:
    print(f"❌ Error running Apify: {e}")
    exit()

# ==========================================
# 4. Data Processing (Your logic)
# ==========================================

processed_rows = []
skipped_arabic_count = 0

print(f"📂 Processing {len(dataset_items)} tweets...")

for item in dataset_items:
    if not isinstance(item, dict):
        continue

    # --- Language filter 1: Main tweet ---
    if item.get('lang') == 'ar':
        skipped_arabic_count += 1
        continue

    # --- Identify retweet and main text ---
    rt_obj = item.get('retweet') or item.get('retweetedStatus') or item.get('retweeted_status') or item.get('retweetedTweet')

    # --- Language filter 2: Retweet content ---
    if rt_obj and isinstance(rt_obj, dict):
        if rt_obj.get('lang') == 'ar':
            skipped_arabic_count += 1
            continue

    # Extracting the text
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

    # --- Handling Quotes ---
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

    # --- Building the final text ---
    if not is_quote:
        if is_retweet:
            combined_text = f'[Retweeted]\n"{final_user_text}"'
        else:
            combined_text = final_user_text

    # Cleaning
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
# 5. Saving to files
# ==========================================

df = pd.DataFrame(processed_rows)

if df.empty:
    print("⚠️ No data found (or everything was filtered).")
else:
    # File 1: Full
    file_full = "twitter_data_full_ALL3.csv"
    df.to_csv(file_full, index=False, encoding='utf-8-sig')
    print(f"✅ Full file created: {file_full}")

    # File 2: Text only for the website
    file_text_only = "twitter_text_only_ALL3.csv"
    df_text_only = df[['full_display_text']].rename(columns={'full_display_text': 'text'})
    
    df_text_only.to_csv(file_text_only, index=False, encoding='utf-8-sig')
    
    print("-" * 50)
    print(f"✅ Website file created: {file_text_only}")
    print(f"📥 Total saved: {len(df)}")
    print(f"🗑️ Filtered (Arabic): {skipped_arabic_count}")
    print("-" * 50)