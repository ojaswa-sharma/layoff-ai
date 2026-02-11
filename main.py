from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import _all, users_router
from contextlib import asynccontextmanager
# from services.db import init_mongo
from dotenv import load_dotenv
from services.graphiti.init_client import init_graphiti, get_graphiti
from dependencies.ch_db import init_ch_engine

# def startup_():
#     init_mongo()

async def lifespan(app : FastAPI):
    load_dotenv()
    print(f"[LIFESPAN] Initializing app")
    init_graphiti()
    init_ch_engine()
    _graphiti = get_graphiti()
    await _graphiti.build_indices_and_constraints()
    print(f"[LIFESPAN] Event complete")
    yield
    print(f"[LIFESPAN] Ending")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users_router)

print(f"[MAIN] App initialized from house-of-apps-ai-engineering-manager")
