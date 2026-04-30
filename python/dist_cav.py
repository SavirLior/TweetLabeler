import pandas as pd

input_file = 'extrenal_predictions_Eli1.csv'

try:
    df = pd.read_csv(input_file)
    df.columns = df.columns.str.strip()
    
    target_col = 'label_Salafi jihadi'
    prob_cols = ['label_Irrelevant', 'label_Salafi jihadi', 'label_Salafi taklidi']

    for col in prob_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    def determine_decision(row):
        if pd.isna(row[target_col]): return 'error'
        if row[target_col] > 0.5: return 'jihad'
        if all(row[c] <= 0.5 for c in prob_cols): return 'no_decision'
        

    df['model_decision'] = df.apply(determine_decision, axis=1)
    
    # Counting results
    j_count = (df['model_decision'] == 'jihad').sum()
    non_count = (df['model_decision'] == 'no_decision').sum()
    
    # Setting the labels for the CSV
    df['model_decision'] = df['model_decision'].replace({
        'no_decision': 'המודל לא הצליח לקבל החלטה',
        'jihad': 'jihad'
    })

    # Dynamic filename
    output_file = f"check_part1_jihad_afterCheck_j-{j_count}_non-{non_count}.csv"
    
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"Success! File saved as: {output_file}")

except Exception as e:
    print(f"Error: {e}")