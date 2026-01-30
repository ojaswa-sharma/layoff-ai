from fastapi import FastAPI
from routers import _all


app = FastAPI()

for _router in _all:
    app.include_router(_router)

