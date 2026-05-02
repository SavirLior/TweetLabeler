import pandas as pd
import numpy as np
import os
import glob

# ==========================================
# הגדרות
# ==========================================
input_dir = 'external_predictions_multiclassR4'
output_dir = 'processed_csvs'
significance_level = 0.99975 # <--- שנה את רמת המובהקות כאן
# ==========================================

os.makedirs(output_dir, exist_ok=True)

csv_files = glob.glob(os.path.join(input_dir, '*.csv'))
prob_cols = ['label_Irrelevant', 'label_Salafi jihadi', 'label_Salafi taklidi']

# הופך את 0.89 ל-'089' עבור שם הקובץ
sig_str = str(significance_level).replace('.', '')

for file_path in csv_files:
    filename = os.path.basename(file_path)
    name, ext = os.path.splitext(filename)
    
    # הוספת רמת המובהקות לשם הקובץ בצורה דינמית
    output_filename = os.path.join(output_dir, f"{name}_max{sig_str}{ext}")

    try:
        df = pd.read_csv(file_path)
        
        df['max_prob'] = df[prob_cols].max(axis=1)
        
        # סינון לפי משתנה רמת המובהקות ולא מספר קבוע
        filtered_df = df[df['max_prob'] <= significance_level].copy()
        
        if not filtered_df.empty:
            best_label = filtered_df[prob_cols].idxmax(axis=1).str.replace('label_', '')
            filtered_df['model_decision'] = np.where(
                filtered_df['max_prob'] < 0.5,
                "No decision, maximum is " + best_label,
                best_label
            )
            
            filtered_df.to_csv(output_filename, index=False)
            print(f"Successfully processed and saved: {output_filename}")
        else:
            print(f"Skipped {filename} - no rows matched the criteria.")
            
    except Exception as e:
        print(f"Error processing {filename}: {e}")