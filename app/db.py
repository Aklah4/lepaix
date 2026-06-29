from pymongo import MongoClient

client = None
_dbname = None

def init_db(app):
    """Initialize the MongoDB client using the Flask app config.

    Call this from the application factory: `init_db(app)`.
    """
    global client, _dbname
    client = MongoClient(app.config.get('MONGO_URI'))
    _dbname = app.config.get('MONGO_DBNAME', 'lepaix')


def get_db():
    if client is None or _dbname is None:
        raise RuntimeError("Database not initialized. Call init_db(app) first.")
    return client[_dbname]