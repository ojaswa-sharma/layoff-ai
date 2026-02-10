import asyncio
import logging
import gc

logger = logging.getLogger(__name__)

class BackgroundWorker:
    def __init__(self, max_workers=5, max_queue_size=100):
        self.queue = asyncio.Queue(maxsize=max_queue_size)
        self.max_workers = max_workers
        self.workers = []
        self.running = False

    async def start(self):
        if self.running:
            return
        self.running = True
        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker(i))
            self.workers.append(worker)
        logger.info(f"Started {self.max_workers} background workers with queue size {self.queue.maxsize}")

    async def stop(self):
        self.running = False
        # Wait for queue to empty
        if not self.queue.empty():
            logger.info(f"Waiting for {self.queue.qsize()} tasks to complete...")
            await self.queue.join()
        
        # Cancel workers
        for worker in self.workers:
            worker.cancel()
        
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers = []
        logger.info("Stopped background workers")

    async def add_task(self, func, *args, **kwargs):
        """
        Add a task to the queue.
        If the queue is full, this will block until a slot is available.
        This provides backpressure to prevent memory exhaustion.
        """
        try:
            await self.queue.put((func, args, kwargs))
            return True
        except Exception as e:
            logger.error(f"Failed to add task to queue: {e}")
            return False

    async def _worker(self, worker_id):
        logger.info(f"Worker {worker_id} started")
        while self.running:
            try:
                # Wait for a task
                func, args, kwargs = await self.queue.get()
                
                try:
                    # Execute the task
                    if asyncio.iscoroutinefunction(func):
                        await func(*args, **kwargs)
                    else:
                        func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"Error in background task (worker {worker_id}): {e}", exc_info=True)
                finally:
                    self.queue.task_done()
                    
                    # Explicitly clear references to help GC
                    del func
                    del args
                    del kwargs
                    
                    # Force garbage collection periodically or after large tasks
                    # This helps release memory immediately instead of waiting for Python's GC
                    gc.collect()
                    
            except asyncio.CancelledError:
                logger.info(f"Worker {worker_id} cancelled")
                break
            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}", exc_info=True)
                await asyncio.sleep(1)  # Prevent tight loop on error

# Global instance
worker_manager = BackgroundWorker(max_workers=5, max_queue_size=50)

def get_worker_manager():
    return worker_manager
