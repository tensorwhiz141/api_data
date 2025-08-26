from pymongo import MongoClient
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Use environment variable for Mongo URI; fallback to local for dev (no hardcoded secrets)
MONGO_URI = (
    os.getenv("MONGODB_URL")
    or os.getenv("MONGODB_URI")
    or os.getenv("MONGO_URI")
    or "mongodb://localhost:27017/"
)

# Print the MongoDB URI being used (for debugging)
print(f"Connecting to MongoDB with URI: {MONGO_URI}")

# Connect to MongoDB
client = MongoClient(MONGO_URI)

# Test the connection
try:
    # The ismaster command is cheap and does not require auth
    client.admin.command('ismaster')
    print("MongoDB connection successful!")
except Exception as e:
    print(f"MongoDB connection failed: {e}")

db = client["gurukul"]

# Define collections based on actual database structure
user_collection = db["user_data"]  # For storing chat messages
user_data_collection = db["User"]  # For storing user information
subjects_collection = db["subjects"]  # For storing subject information
lectures_collection = db["lectures"]  # For storing lecture information

# Keep these for backward compatibility
pdf_collection = db["pdf_collection"]
image_collection = db["image_collection"]
tests_collection = db["tests_collection"]

# Print available collections for debugging
print("\nCollections in database:")
try:
    for collection in db.list_collection_names():
        print(f" - {collection}")
except Exception as e:
    print(f"Error listing collections: {e}")
