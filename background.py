from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import _all, github_router, bitbucket_router
from contextlib import asynccontextmanager
# from services.db import init_mongo
from dotenv import load_dotenv
from services.graphiti.init_client import init_graphiti, get_graphiti
from dependencies.ch_db import init_ch_engine
from services.background_worker import get_worker_manager

# def startup_():
#     init_mongo()

async def lifespan(app : FastAPI):

    load_dotenv()
    print(f"[LIFESPAN] Initializing app")
    # startup_()
    init_graphiti()
    init_ch_engine()
    _graphiti = get_graphiti()
    await _graphiti.build_indices_and_constraints()
    
    # Start background workers
    worker_manager = get_worker_manager()
    await worker_manager.start()
    
    print(f"[LIFESPAN] Event complete")
    yield
    print(f"[LIFESPAN] Ending")
    
    # Stop background workers
    await worker_manager.stop()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for _router in [github_router, bitbucket_router]:
    app.include_router(_router)

print(f"[MAIN] App initialized from house-of-apps-ai-engineering-manager")

