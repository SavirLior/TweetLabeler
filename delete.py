from pymongo import MongoClient

MONGO_URI = "mongodb+srv://edenoren772_db_user:Ofek772468@cluster0.hs9wlnh.mongodb.net/?appName=Cluster0"
MONGO_DB_NAME = "tweetlabeler"
MONGO_TWEETS_COLLECTION = "tweets"

client = MongoClient(MONGO_URI)
db = client[MONGO_DB_NAME]
collection = db[MONGO_TWEETS_COLLECTION]

count = collection.count_documents({"round": 4})
print(f"Found {count} tweets to delete.")

# Uncomment the next two lines to actually delete
result = collection.delete_many({"round": 4})
print(f"Deleted {result.deleted_count} tweets.")