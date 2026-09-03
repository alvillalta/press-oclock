from app.core.config import settings
import psycopg

url = str(settings.SQLALCHEMY_DATABASE_URI).replace(
    "postgresql+psycopg://",
    "postgresql://"
)

conn = psycopg.connect(url)
cur = conn.cursor()

cur.execute("SELECT current_database(), current_schema()")
print("DB/SCHEMA:", cur.fetchone())

cur.execute("""
    SELECT table_schema, table_name
    FROM information_schema.tables
    WHERE table_name = 'user'
""")
print("USER TABLE:", cur.fetchall())

conn.close()