from pathlib import Path

import psycopg
from dotenv import load_dotenv

# Read connection settings from .env beside this script.
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

# psycopg reads the PGHOST, PGPORT, PGDATABASE,
# PGUSER, and PGPASSWORD environment variables.
with psycopg.connect(connect_timeout=10) as connection:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), current_user;"
        )
        database, user = cursor.fetchone()

        print("Connection successful!")
        print(f"Database: {database}")
        print(f"User: {user}")
