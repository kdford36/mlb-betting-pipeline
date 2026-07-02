import os 
from dotenv import load_dotenv
from sqlalchemy import create_engine, text 

load_dotenv()

def get_engine():
    url = (
        f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    return create_engine(url)

if __name__ == "__main__":
    engine = get_engine()
    with engine.connect() as conn: 
        result = conn.execute(text("SELECT version();"))
        print(result.fetchone())