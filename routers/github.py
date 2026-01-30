from fastapi import APIRouter, Request
from models.commits import Commit
from typing import List
from services.git_diff import fetch_diff_from_webhook
import os

router = APIRouter(prefix="/github")


@router.post("/webhook")
async def webhook_github(request: Request):
    request_data = await request.json()
    compare_url = request_data["compare"]
    installation_id = request_data["installation"]["id"]
    app_id = os.getenv("APP_ID")
    with open("isometrik.pem", 'r') as file:
        pem_data = file.read()
    diff_text = await fetch_diff_from_webhook(compare_url, installation_id, app_id, pem_data)

    for commit in request_data["commits"]:
        commit_hash = commit["id"][:12]
        commit_model = Commit(
            commit_hash=commit_hash,
            message=commit["message"],
            author=commit["author"]["name"],
            email=commit["author"]["email"],
            date=commit["timestamp"],
            repository_name=request_data["repository"]["name"],
            repository_url=request_data["repository"]["url"],
            diff=diff_text,
            installation_id=installation_id
        )
    
    return {"message": request_data}

