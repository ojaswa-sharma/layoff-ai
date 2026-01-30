from fastapi import FastAPI
from routers import _all
from contextlib import asynccontextmanager
from services.db import init_mongo
from dotenv import load_dotenv



app = FastAPI()

def startup_():
    init_mongo()

async def lifespan(app : FastAPI):
    load_dotenv()
    print(f"[LIFESPAN] Initializing app")
    startup_()
    print(f"[LIFESPAN] Event complete")
    yield
    print(f"[LIFESPAN] Ending")

for _router in _all:
    app.include_router(_router)
