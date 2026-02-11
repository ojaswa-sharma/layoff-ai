import asyncio
import logging
from aiokafka import AIOKafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
import os
import json

logger = logging.getLogger(__name__)


class BackgroundProducer:
    def __init__(self):
        self.KAFKA_BROKER = os.getenv("KAFKA_BROKER", "91.99.230.218:9092")
        self._producer = AIOKafkaProducer(bootstrap_servers=self.KAFKA_BROKER)
        self._started = False

    async def ensure_topic(self, topic="ems-commits"):
        """Check if topic exists; create if missing"""
        admin_client = KafkaAdminClient(bootstrap_servers=self.KAFKA_BROKER)
        existing_topics = admin_client.list_topics()
        if topic not in existing_topics:
            logger.info(f"Topic '{topic}' not found, creating it...")
            new_topic = NewTopic(
                name=topic,
                num_partitions=1,
                replication_factor=1
            )
            admin_client.create_topics(new_topics=[new_topic], validate_only=False)
            logger.info(f"Topic '{topic}' created")
        admin_client.close()

    async def start(self, topic="ems-commits"):
        if not self._started:
            await self.ensure_topic(topic)
            await self._producer.start()
            self._started = True
            logger.info("Kafka producer started")

    async def stop(self):
        if self._started:
            await self._producer.stop()
            self._started = False
            logger.info("Kafka producer stopped")

    async def add_task(self, data, topic="ems-commits"):
        if not self._started:
            await self.start(topic)

        try:
            if not isinstance(data, str):
                json_data = json.dumps(data).encode()
            else:
                json_data = data.encode()
            await self._producer.send_and_wait(topic=topic, value=json_data)
            logger.info(f"Task sent to Kafka topic {topic}")
        except Exception as e:
            logger.error(f"Failed to send task to Kafka: {e}")


async def main():
    producer = BackgroundProducer()
    await producer.start()

    await producer.add_task({"repo": "example", "commit": "abc123"})
    
    await producer.stop()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    asyncio.run(main())
