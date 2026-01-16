import pandas as pd
import json
import re
import os

# --- 1. הגדרות ---
# שנה כאן את שם הקובץ שקיבלת מהתוסף
input_filename = 'TwExport_nav09284172_Posts.csv'

# שם הקובץ שיוצא לאתר
output_filename = 'tweets_for_website.json'

# --- 2. פונקציות עזר ---

def clean_links(text):
    """מוחקת קישורים (http/https) מהטקסט"""
    if not isinstance(text, str):
        return ""
    # הסרת כתובות אינטרנט
    return re.sub(r'http\S+', '', text).strip()

# --- 3. הטעינה והעיבוד ---

try:
    df = pd.read_csv(input_filename)
    print(f"📂 טענתי בהצלחה {len(df)} שורות.")
except FileNotFoundError:
    print(f"❌ שגיאה: לא מצאתי את הקובץ '{input_filename}'. בדוק את השם והתיקייה.")
    exit()

final_data_list = []
skip_next = False # משתנה עזר לדילוג על שורות שכבר חיברנו

# עוברים על הטבלה שורה-שורה
for i in range(len(df)):
    
    # אם השורה הזו היא ציטוט שכבר השתמשנו בו בסיבוב הקודם -> מדלגים
    if skip_next:
        skip_next = False
        continue

    row = df.iloc[i]
    row_type = str(row['Type']).strip()
    user_text = str(row['Text']).strip()
    
    # אנחנו מעבדים רק ציוצים, תגובות או ריטוויטים (לא שורות שהן רק ציטוט בפני עצמן)
    if row_type == 'Quoted':
        continue

    # --- בדיקת הקשר (Context) ---
    full_text = ""
    context_found = False

    # מסתכלים על השורה הבאה לראות אם היא הציטוט של השורה הנוכחית
    if i + 1 < len(df):
        next_row = df.iloc[i+1]
        if str(next_row['Type']).strip() == 'Quoted':
            # מצאנו ציטוט!
            quote_text = str(next_row['Text']).strip()
            
            # בניית הטקסט המשולב
            full_text = f'הציוץ המקורי (ציטוט):\n"{quote_text}"\n\n--------------\n\nתגובת המשתמש:\n{user_text}'
            
            context_found = True
            skip_next = True # מסמנים לדלג על השורה הבאה

    # אם לא היה ציטוט, נבדוק אם זה סתם ריטוויט או ציוץ רגיל
    if not context_found:
        if row_type == 'Retweet':
            full_text = f'[משתמש עשה ריטוויט]\n"{user_text}"'
        else:
            full_text = user_text

    # --- 4. ניקוי וסיום ---
    
    # מנקים קישורים מהתוצאה הסופית
    clean_text = clean_links(full_text)

    # הוספה לרשימה הסופית
    final_data_list.append({
        "id": len(final_data_list) + 1,
        "text": clean_text
    })

# --- 5. שמירה לקובץ JSON ---

with open(output_filename, 'w', encoding='utf-8') as f:
    json.dump(final_data_list, f, ensure_ascii=False, indent=4)

print("-" * 50)
print(f"✅ הסקריפט סיים בהצלחה!")
print(f"נוצר קובץ חדש בשם: {output_filename}")
print(f"הוא מכיל {len(final_data_list)} ציוצים מוכנים לאתר.")
print("-" * 50)