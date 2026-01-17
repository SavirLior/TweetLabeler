import pandas as pd
import re
import os

# --- 1. הגדרות תיקיות ---
input_folder = 'data'      # התיקייה ממנה קוראים את הקבצים
output_folder = 'output'   # התיקייה אליה שומרים את התוצאות

# יצירת תיקיית הפלט אם היא לא קיימת
if not os.path.exists(output_folder):
    os.makedirs(output_folder)
    print(f"📁 נוצרה תיקייה חדשה: {output_folder}")

# --- 2. פונקציות עזר ---

def clean_links(text):
    """מוחקת קישורים (http/https) מהטקסט"""
    if not isinstance(text, str):
        return ""
    return re.sub(r'http\S+', '', text).strip()

def get_output_filename(original_filename):
    """
    הופך את השם: TwExport_Username_Posts.csv
    לשם: Username.csv
    """
    new_name = original_filename.replace('TwExport_', '').replace('_Posts.csv', '.csv')
    return new_name

# --- 3. המנוע הראשי (לולאה על כל הקבצים) ---

# קבלת רשימת כל הקבצים בתיקיית ה-data שמסתיימים ב-csv
files = [f for f in os.listdir(input_folder) if f.endswith('.csv')]

if not files:
    print(f"⚠️ לא נמצאו קבצי CSV בתיקייה '{input_folder}'.")
    exit()

print(f"🚀 מתחיל לעבד {len(files)} קבצים...")
print("-" * 50)

for filename in files:
    input_path = os.path.join(input_folder, filename)
    
    # חישוב שם הקובץ החדש (רק שם המשתמש)
    new_filename = get_output_filename(filename)
    output_path = os.path.join(output_folder, new_filename)
    
    print(f"🔄 מעבד את: {filename}...")

    try:
        df = pd.read_csv(input_path)
    except Exception as e:
        print(f"❌ שגיאה בטעינת הקובץ {filename}: {e}")
        continue

    final_data_list = []
    skip_next = False 

    # --- לוגיקת העיבוד (אותה לוגיקה כמו מקודם) ---
    for i in range(len(df)):
        
        if skip_next:
            skip_next = False
            continue

        row = df.iloc[i]
        row_type = str(row['Type']).strip()
        user_text = str(row['Text']).strip()
        
        if row_type == 'Quoted':
            continue

        full_text = ""
        context_found = False

        # בדיקת הקשר (ציטוט בשורה הבאה)
        if i + 1 < len(df):
            next_row = df.iloc[i+1]
            if str(next_row['Type']).strip() == 'Quoted':
                quote_text = str(next_row['Text']).strip()
                full_text = f'הציוץ המקורי (ציטוט):\n"{quote_text}"\n\n--------------\n\nתגובת המשתמש:\n{user_text}'
                context_found = True
                skip_next = True

        # אם לא היה ציטוט
        if not context_found:
            if row_type == 'Retweet':
                full_text = f'[משתמש עשה ריטוויט]\n"{user_text}"'
            else:
                full_text = user_text

        # ניקוי
        clean_text = clean_links(full_text)

        final_data_list.append({
            "id": len(final_data_list) + 1,
            "text": clean_text
        })

    # --- שמירה לקובץ בודד בתיקיית ה-Output ---
    if final_data_list:
        df_final = pd.DataFrame(final_data_list)
        df_final.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"✅ נשמר כ: {new_filename} ({len(df_final)} ציוצים)")
    else:
        print(f"⚠️ הקובץ {filename} עובד אך לא הניב תוצאות.")

print("-" * 50)
print(f"🏁 הסתיים העיבוד של כל הקבצים.")