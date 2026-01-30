from fastapi import APIRouter, Request
from models.commits import Commit
from typing import List
from services.git_diff import fetch_git_diff


router = APIRouter(prefix="/github")


@router.post("/webhook")
async def webhook_github(request: Request):
    ...
    request_data = await request.json()
    # compare_url = request_data["compare"]
    # diff_text = await fetch_git_diff(compare_url)

    # for commit in request_data["commits"]:
    #     commit_hash = commit["id"][:12]
    #     commit_model = Commit(
    #         commit_hash=commit_hash,
    #         message=commit["message"],
    #         author=commit["author"]["name"],
    #         email=commit["author"]["email"],
    #         date=commit["timestamp"],
    #         repository_name=request_data["repository"]["name"],
    #         repository_url=request_data["repository"]["url"],
    #         diff=diff_text
    #     )
        # print(commit_model)
    
    print("--------------------------------")
    print(request_data)
    
    return {"message": request_data}

