import pandas as pd

input_file = 'filtered_salafi_jihadi.csv'
output_file = 'filtered_salafi_jihadi.xlsx'

try:
    df = pd.read_csv(input_file, encoding='utf-8-sig')
except UnicodeDecodeError:
    try:
        df = pd.read_csv(input_file, encoding='cp1255', encoding_errors='replace')
    except:
        df = pd.read_csv(input_file)

df.to_excel(output_file, index=False)
print(f"File saved as: {output_file}")
