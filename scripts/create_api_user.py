import argparse
import psycopg2
import os
import sys

def load_env_file(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

load_env_file()

# Add parent directory to path to import auth
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))
from auth import hash_password

def main():
    parser = argparse.ArgumentParser(description="Create an API user")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", default="viewer", choices=["viewer", "admin"])
    args = parser.parse_args()

    # DB Connection
    db_url = os.getenv("DATABASE_URL", "").strip().strip('"').strip("'")
    if db_url:
        conn = psycopg2.connect(db_url)
    else:
        conn = psycopg2.connect(
            dbname=os.getenv("PGDATABASE", "oee_db"),
            user=os.getenv("PGUSER", "harshchanchlani"),
            password=os.getenv("PGPASSWORD", ""),
            host=os.getenv("PGHOST", "localhost"),
            port=os.getenv("PGPORT", "5432")
        )
    cur = conn.cursor()

    hashed = hash_password(args.password)
    
    try:
        cur.execute(
            "INSERT INTO api_users (username, hashed_password, role) VALUES (%s, %s, %s)",
            (args.username, hashed, args.role)
        )
        conn.commit()
        print(f"✅ User '{args.username}' created successfully as '{args.role}'.")
        
        jwt_secret = os.getenv("JWT_SECRET_KEY", "CHANGE_ME_USE_OPENSSL_RAND_HEX_32")
        if jwt_secret == "CHANGE_ME_USE_OPENSSL_RAND_HEX_32":
            print("⚠️ WARNING: JWT_SECRET_KEY is using the default placeholder. Change it in .env!")
            
    except Exception as e:
        print(f"❌ Error creating user: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    main()
