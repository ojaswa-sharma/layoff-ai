import asyncio
from services.kafka.background_kafka_consuer import BackgroundKafkaConsumer
import os
from dotenv import load_dotenv

load_dotenv()

async def main():
    consumer = BackgroundKafkaConsumer()
    await consumer.startup()
    try:
        count = 0
        while True:
            await asyncio.sleep(1)
            free = await consumer._get_semaphore()
            if free == 5:
                if count < 5:
                    count += 1
                else:
                    continue
            else:
                count = 0
            print(f"[SEMAPHORE] : CURRENT SEMAPHORE COUNT : {free}")
    except KeyboardInterrupt:
        print("[SHUTDOWN] Received exit signal")
    finally:
        await consumer.stop()

if __name__ == "__main__":
    asyncio.run(main())
