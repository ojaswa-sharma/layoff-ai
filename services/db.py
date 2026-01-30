from pymongo import MongoClient
import os

mongo_db = None

def init_mongo():
    global mongo_db
    client = MongoClient(host = os.getenv("MONGO_URL"))
    mongo_db = client["dev-tracker"]

def get_mongo_db():
    global mongo_db
    return mongo_db    