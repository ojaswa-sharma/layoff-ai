from services.kafka.background_kafka_consuer import BackgroundKafkaConsumer
from services.kafka.background_kafka_worker import BackgroundProducer

_consumer = None
_producer = None

def get_kafka_producer():
    global _producer
    if not _producer:
        _producer = BackgroundProducer()
    return _producer

def get_kafka_consumer():
    global _consumer
    if not _consumer:
        _consumer = BackgroundKafkaConsumer()
    return _consumer