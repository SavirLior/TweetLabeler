import pandas as pd

# Load the source CSV
df = pd.read_csv('tweets_from_the_site.csv')

# Filter by 'Salafi jihadi' and select only text and label columns
# Note: Ensure 'text' and 'Final Decision' match your actual column headers
filtered_data = df[df['Final Decision'] == 'Salafi jihadi'][['Text', 'Final Decision']]

# Save to the destination CSV
filtered_data.to_csv('destination.csv', index=False)