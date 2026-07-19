import os
from dotenv import load_dotenv

load_dotenv()

instance_connection_name = os.getenv("INSTANCE_CONNECTION_NAME")
if instance_connection_name:
    # Running on Cloud Run
    DB_HOST = f"/cloudsql/{instance_connection_name}"
else:
    # Running locally with Docker Compose
    DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY")