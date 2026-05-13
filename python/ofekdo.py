import pandas as pd
from sklearn.metrics import classification_report, accuracy_score, confusion_matrix

input_path = 'external_predictions4/extrenal_predictions_ELI2.csv'
output_csv_path = 'model_estimation.csv'
report_txt_path = 'evaluation_report.txt'

# Read file
try:
    df = pd.read_csv(input_path, encoding='utf-8-sig')
except UnicodeDecodeError:
    df = pd.read_csv(input_path, encoding='cp1255', encoding_errors='replace')

# Clean formatting artifacts
df = df.replace('_x000D_', '', regex=True)

# Define columns
model_cols = ['label_Salafi jihadi', 'label_Salafi taklidi', 'label_Irrelevant']

# Extract predictions, confidence, and real labels
df['model_decision'] = df[model_cols].idxmax(axis=1)
df['confidence_score'] = df[model_cols].max(axis=1)
df['Real_label'] = df['label']

# Error and length analysis
df['is_error'] = df['Real_label'] != df['model_decision']
df['text_length'] = df['text'].astype(str).apply(len)

# Sort by errors first, then by how confident the model was in its error
df_sorted = df.sort_values(by=['is_error', 'confidence_score'], ascending=[False, False])

# Save the detailed CSV
final_df = df_sorted[['text', 'Real_label', 'model_decision', 'confidence_score', 'text_length', 'is_error']]
final_df.to_csv(output_csv_path, index=False, encoding='utf-8-sig')

# Generate Metrics
accuracy = accuracy_score(df['Real_label'], df['model_decision'])
report = classification_report(df['Real_label'], df['model_decision'])
conf_matrix = confusion_matrix(df['Real_label'], df['model_decision'])
labels_order = sorted(df['Real_label'].dropna().unique())

# Save metrics to a text file instead of stdout
with open(report_txt_path, 'w', encoding='utf-8') as f:
    f.write("=== Model Evaluation Report ===\n\n")
    f.write(f"Overall Accuracy: {accuracy:.4f}\n\n")
    
    f.write("--- Classification Report ---\n")
    f.write(report)
    f.write("\n\n")
    
    f.write("--- Confusion Matrix ---\n")
    f.write(f"Labels Order: {labels_order}\n")
    f.write(str(conf_matrix))
    f.write("\n\n")
    
    f.write("--- Errors by True Category ---\n")
    error_counts = df[df['is_error']]['Real_label'].value_counts()
    f.write(error_counts.to_string())