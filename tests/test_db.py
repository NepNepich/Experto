import asyncio
from database import check_database_connection

async def main():
    try:
        await check_database_connection()
        print("✅ Database connection OK")
    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())