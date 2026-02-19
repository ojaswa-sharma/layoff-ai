import asyncio
from services.kafka.background_kafka_consuer import BackgroundKafkaConsumer
import os
from dotenv import load_dotenv
import warnings
import gc

warnings.filterwarnings(
    "ignore",
    message="Pydantic serializer warnings:",
)
warnings.filterwarnings(
    "ignore",
    message="Invalid duplicate_name",
)



load_dotenv()

async def main():
    consumer = BackgroundKafkaConsumer()
    await consumer.startup()
    try:
        count = 0
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("[SHUTDOWN] Received exit signal")
    finally:
        await consumer.stop()

if __name__ == "__main__":
    asyncio.run(main())
