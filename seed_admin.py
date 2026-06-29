import argparse
import os
from argparse import ArgumentParser
from getpass import getpass
from pathlib import Path

import bcrypt
from pymongo import MongoClient

from config import Config

BASE_DIR = Path(__file__).resolve().parent
DOTENV_PATH = BASE_DIR / ".env"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    with path.open("r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


def get_mongo_settings() -> tuple[str, str]:
    config = Config()
    uri = os.environ.get("MONGO_URI") or config.MONGO_URI
    dbname = os.environ.get("MONGO_DBNAME") or config.MONGO_DBNAME
    return uri, dbname


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_admin(db, username: str, password: str) -> str:
    hashed_password = hash_password(password)
    result = db.admins.update_one(
        {"username": username},
        {"$set": {"username": username, "password": hashed_password}},
        upsert=True,
    )

    if result.upserted_id is not None:
        return str(result.upserted_id)

    existing = db.admins.find_one({"username": username}, {"_id": 1})
    return str(existing["_id"])


def parse_args() -> argparse.Namespace:
    parser = ArgumentParser(description="Seed or update the admin login user in MongoDB.")
    parser.add_argument("-u", "--username", default=os.environ.get("ADMIN_USERNAME", "admin"), help="Admin username")
    parser.add_argument("-p", "--password", help="Admin password. If omitted, the script will prompt for one.")
    parser.add_argument("--uri", help="MongoDB URI override")
    parser.add_argument("--dbname", help="MongoDB database name override")
    return parser.parse_args()


def main() -> None:
    load_dotenv(DOTENV_PATH)
    args = parse_args()

    password = args.password or getpass("Admin password: ")
    if not password:
        raise SystemExit("A password is required to seed the admin user.")

    uri = args.uri or os.environ.get("MONGO_URI")
    dbname = args.dbname or os.environ.get("MONGO_DBNAME")
    if not uri or not dbname:
        uri, dbname = get_mongo_settings()

    client = MongoClient(uri)
    db = client[dbname]

    admin_id = create_admin(db, args.username, password)
    print(f"Admin user '{args.username}' seeded into database '{dbname}' with id {admin_id}.")


if __name__ == "__main__":
    main()
