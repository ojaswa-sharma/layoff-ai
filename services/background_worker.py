import asyncio
import logging

logger = logging.getLogger(__name__)

class BackgroundWorker:
    def __init__(self, max_workers: int = 5, max_queue_size: int = 100, max_concurrent_tasks: int | None = None):
        self.queue = asyncio.Queue(maxsize=max_queue_size)
        self.max_workers = max_workers
        self.sem = asyncio.Semaphore(max_concurrent_tasks or max_workers)
        self.workers: list[asyncio.Task] = []
        self.running = False

    async def start(self):
        if self.running:
            return
        self.running = True
        for i in range(self.max_workers):
            t = asyncio.create_task(self._worker(i), name=f"bg-worker-{i}")
            self.workers.append(t)
        logger.info("Started %d workers (queue=%d, concurrent=%d)",
                    self.max_workers, self.queue.maxsize, self.sem._value)

    async def stop(self):
        if not self.running:
            return

        await self.queue.join()

        self.running = False
        for _ in range(len(self.workers)):
            await self.queue.put(None)

        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
        logger.info("Stopped background workers")

    async def add_task(self, func, *args, **kwargs) -> bool:
        """
        Backpressure is enforced by bounded queue.
        IMPORTANT: keep args small (IDs, not big objects).
        """
        try:
            await self.queue.put((func, args, kwargs))
            return True
        except Exception:
            logger.exception("Failed to enqueue task")
            return False

    async def _execute(self, func, args, kwargs):
        async with self.sem:
            result = func(*args, **kwargs)
            if asyncio.iscoroutine(result):
                await result

    async def _worker(self, worker_id: int):
        logger.info("Worker %d started", worker_id)
        while True:
            item = await self.queue.get()
            if item is None:
                self.queue.task_done()
                logger.info("Worker %d exiting", worker_id)
                break

            func, args, kwargs = item
            try:
                await self._execute(func, args, kwargs)
            except Exception:
                logger.exception("Error in background task (worker %d)", worker_id)
            finally:
                self.queue.task_done()


worker_manager = BackgroundWorker(
    max_workers=10,
    max_queue_size=500,
    max_concurrent_tasks=5,
)

def get_worker_manager():
    return worker_manager
