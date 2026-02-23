from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import users_router
from contextlib import asynccontextmanager
# from services.db import init_mongo
from dotenv import load_dotenv
from services.graphiti.init_client import init_graphiti, get_graphiti
from dependencies.ch_db import init_ch_engine
from services.auth.auth_client import init_auth_client, stop_session
from middlewares.timer import timer_middleware


async def lifespan(app : FastAPI):
    load_dotenv()
    print(f"[LIFESPAN] Initializing app")
    init_graphiti()
    init_ch_engine()
    _graphiti = get_graphiti()
    await _graphiti.build_indices_and_constraints()
    init_auth_client()
    print(f"[LIFESPAN] Event complete")
    yield
    await stop_session()
    print(f"[LIFESPAN] Ending")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# app.middleware("timer")(timer_middleware)

app.include_router(users_router)

print(f"[MAIN] App initialized from house-of-apps-ai-engineering-manager")