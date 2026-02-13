import time
from fastapi import Request

async def timer_middleware(request : Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    process_time = time.perf_counter() - start_time
    print(f"[TIMING] Overall operation took : {(process_time)*1000:.2f} ms")
    return response
