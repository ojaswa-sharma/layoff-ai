import asyncio
from aiokafka import AIOKafkaConsumer
from services.ai_service import summarize_and_upload
from dependencies.json_encoder import DateTimeEncoder, datetime_decoder
import json
import os
import uvloop

class BackgroundKafkaConsumer:
    def __init__(self):
        BROKER = os.getenv("KAFKA_BROKER", "91.99.230.218:9092")
        TOPIC = "ems-commits"
        GROUP_ID = os.getenv("KAFKA_GROUPID","ems")
        self._consumer = AIOKafkaConsumer(
            TOPIC,
            bootstrap_servers=BROKER,
            group_id=GROUP_ID,
            auto_offset_reset="earliest"
        )
        self._running = False
        self._worker_task = None
        self._semaphore = asyncio.Semaphore(int(os.getenv("SEMAPHORE_SIZE", 5)))
        self._tasks = set()
    
    async def startup(self):
        if self._running:
            return
        await self._consumer.start()
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
        print("[STARTUP] Consumer started")

    async def stop(self):
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                print("[SHUTDOWN] Consumer task shut down successfully")

        while self._tasks:
            print(f"[WAITING] SHUTDOWN PENDING BECAUSE OF PENDING TASKS : {5-self._semaphore._value}")
            await asyncio.sleep(0.1)
        await self._consumer.stop()
        print("[SHUTDOWN] Kafka consumer stopped")

    async def _worker(self):
        try:
            async for msg in self._consumer:
                if not self._running:
                    break
                commit_json = json.loads(msg.value.decode(), object_hook=datetime_decoder)
                await self._semaphore.acquire()
                task = asyncio.create_task(self._execute(commit_json))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        except asyncio.CancelledError:
            pass
    
    async def _execute(self, data):
        # async with self._semaphore:
        try:
            await summarize_and_upload(*data)
        except Exception as e:
            print(f"[ERROR] Error while summarizing : {e}")
        finally:
            self._semaphore.release()
    
    async def _get_semaphore(self):
        return self._semaphore._value

if __name__ == "__main__":
    from services.kafka.background_kafka_worker import BackgroundProducer
    async def test():
        consumer = BackgroundKafkaConsumer()
        await consumer.startup()
        producer = BackgroundProducer()
        await producer.start()
        await producer.add_task({"repo": "example", "commit": "abc123"})
        await asyncio.sleep(2)
        await consumer.stop()
        await producer.stop()

    asyncio.run(test())
