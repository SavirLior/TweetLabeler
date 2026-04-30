import pandas as pd
import numpy as np

input_filename = 'extrenal_predictions/extrenal_predictions (13).csv'
output_filename = 'Taklid2_uncertain_tweets_max089.csv'

try:
    df = pd.read_csv(input_filename)
    
    prob_cols = ['label_Irrelevant', 'label_Salafi jihadi', 'label_Salafi taklidi']
    
    df['max_prob'] = df[prob_cols].max(axis=1)
    
    filtered_df = df[df['max_prob'] <= 0.89].copy()
    
    best_label = filtered_df[prob_cols].idxmax(axis=1).str.replace('label_', '')
    
    filtered_df['model_decision'] = np.where(
        filtered_df['max_prob'] < 0.5,
        "No decision, maximum is " + best_label,
        best_label
    )
    
    filtered_df['uncertainty_score'] = filtered_df[prob_cols].apply(lambda x: min(abs(x - 0.5)), axis=1)
    
    filtered_df.to_csv(output_filename, index=False, encoding='utf-8-sig')
    print(f"Success! Saved {len(filtered_df)} tweets to '{output_filename}'")

except Exception as e:
    print(f"Error: {e}")