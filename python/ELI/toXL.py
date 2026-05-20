import pandas as pd

input_file = 'tweetsfromsite_1_3_4_test4_minus_filtered_plus_sg_no_blank.csv'
output_file = 'all_tweets.xlsx'

try:
    df = pd.read_csv(input_file, encoding='utf-8-sig')
except UnicodeDecodeError:
    try:
        df = pd.read_csv(input_file, encoding='cp1255', encoding_errors='replace')
    except:
        df = pd.read_csv(input_file)

df.to_excel(output_file, index=False)
print(f"File saved as: {output_file}")
