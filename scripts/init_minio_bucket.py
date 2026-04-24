import boto3
import os

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

def main():
    s3 = boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT", "http://localhost:9000"),
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        aws_secret_access_key=os.getenv("MINIO_SECRET_KEY", "minioadmin123"),
    )
    bucket = os.getenv("DATALAKE_BUCKET", "oee-datalake")
    try:
        existing = [b["Name"] for b in s3.list_buckets()["Buckets"]]
        if bucket not in existing:
            s3.create_bucket(Bucket=bucket)
            print(f"✅ Created bucket: {bucket}")
        else:
            print(f"ℹ️ Bucket already exists: {bucket}")
    except Exception as e:
        print(f"❌ Error initializing MinIO: {e}")

if __name__ == "__main__":
    main()
