import pandas as pd
import json
import re
import datetime


input_filename = 'dataset_tweet-scraper_2026-01-17_19-15-43-328.json' 



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

# ==========================================
# 3. טעינה ועיבוד
# ==========================================

print(f"📂 טוען את הקובץ: {input_filename}...")

try:
    with open(input_filename, 'r', encoding='utf-8') as f:
        data = json.load(f)
except FileNotFoundError:
    print(f"❌ שגיאה: לא מצאתי את הקובץ '{input_filename}'.")
    exit()

processed_rows = []
skipped_arabic_count = 0

print(f"🔄 מעבד {len(data)} ציוצים...")

for item in data:
    if not isinstance(item, dict):
        continue
        
    # --- בדיקה 1: שפת הציוץ הראשי ---
    if item.get('lang') == 'ar':
        skipped_arabic_count += 1
        continue

    # מחפשים את אובייקט הריטוויט (כדי לבדוק גם אותו וגם לשלוף טקסט)
    rt_obj = item.get('retweet') or item.get('retweetedStatus') or item.get('retweeted_status')

    # --- בדיקה 2: שפת הריטוויט (הבקשה שלך) ---
    if rt_obj and isinstance(rt_obj, dict):
        # אם הציוץ המקורי שעשו עליו ריטוויט הוא בערבית - זורקים
        if rt_obj.get('lang') == 'ar':
            skipped_arabic_count += 1
            continue

    # ==========================================================
    # שליפת הטקסט (הלוגיקה שעבדה לנו מקודם)
    # ==========================================================
    final_user_text = ""
    is_retweet = False

    if rt_obj and isinstance(rt_obj, dict):
        # לוקחים את הטקסט המלא מתוך הריטוויט
        final_user_text = rt_obj.get('fullText') or rt_obj.get('text') or rt_obj.get('full_text')
        is_retweet = True
    else:
        # זה לא ריטוויט, לוקחים את הטקסט הרגיל
        final_user_text = item.get('fullText') or item.get('text') or item.get('full_text')
        is_retweet = False

    # אם אין טקסט בכלל, מדלגים
    if not final_user_text:
        continue

    # ==========================================================
    # טיפול ב-Quote (ציטוט)
    # ==========================================================
    combined_text = ""
    is_quote = False
    quote_obj = item.get('quote') or item.get('quoted_status') or item.get('quotedTweet')

    if quote_obj:
        quote_content = quote_obj.get('fullText') or quote_obj.get('text') or quote_obj.get('full_text')
        quote_author = quote_obj.get('author', {}).get('userName', 'Unknown')
        
        # בונוס: בדיקת שפה גם לציטוט (אם הציטוט בערבית - נזרוק גם?)
        # כרגע שמתי בהערה, אם תרצה תוריד את ה-#
        # if quote_obj.get('lang') == 'ar':
        #    skipped_arabic_count += 1
        #    continue

        if quote_content:
            is_quote = True
            combined_text = (
                f'Original Tweet (by @{quote_author}):\n'
                f'"{quote_content}"\n\n'
                f'--------------\n\n'
                f'User Reply:\n'
                f'{final_user_text}'
            )

    # ==========================================================
    # בניית הטקסט הסופי
    # ==========================================================
    if not is_quote:
        if is_retweet:
            combined_text = f'[Retweeted]\n"{final_user_text}"'
        else:
            combined_text = final_user_text

    # ניקוי סופי
    clean_combined_text = clean_text(combined_text)

    if clean_combined_text:
        processed_rows.append({
            "username": item.get('author', {}).get('userName', 'Unknown'),
            "date": format_date(item.get('createdAt', '')),
            "full_display_text": clean_combined_text
        })

# ==========================================
# 4. שמירה לקבצים
# ==========================================

df = pd.DataFrame(processed_rows)

if df.empty:
    print("⚠️ הקובץ יצא ריק.")
else:
    file_text_only = "text_only_no_api.csv"
    
    df_text_only = df[['full_display_text']].rename(columns={'full_display_text': 'text'})
    df_text_only.insert(0, 'id', range(1, len(df_text_only) + 1))
    
    df_text_only.to_csv(file_text_only, index=False, encoding='utf-8-sig')
    
    print("-" * 50)
    print(f"✅ הצלחה! הקובץ '{file_text_only}' מוכן.")
    print(f"📥 סה\"כ נשמרו: {len(df)}")
    print(f"🗑️ סוננו בגלל ערבית (כולל ריטוויטים): {skipped_arabic_count}")
    print("-" * 50)