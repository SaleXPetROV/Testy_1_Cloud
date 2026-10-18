"""
Database connection and initialization
"""
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
# Connection pool tuned for high concurrency (~20k active users). See
# server.py for the rationale behind each option — keep both in sync.
# Env-configurable so small single-node deployments can cap the socket count
# and avoid OOM-crashing mongod.
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(
    mongo_url,
    maxPoolSize=int(os.environ.get('MONGO_MAX_POOL_SIZE', '100')),
    minPoolSize=int(os.environ.get('MONGO_MIN_POOL_SIZE', '5')),
    maxIdleTimeMS=60000,
    waitQueueTimeoutMS=10000,
    serverSelectionTimeoutMS=int(os.environ.get('MONGO_SERVER_SELECTION_TIMEOUT_MS', '5000')),
    connectTimeoutMS=10000,
    retryWrites=True,
)
db = client[os.environ['DB_NAME']]
from core.pii_crypto import wrap_database as _wrap_pii
db = _wrap_pii(db)   # same encryption proxy as server.db


def get_db():
    """Get database instance"""
    return db


def get_client():
    """Get MongoDB client"""
    return client
