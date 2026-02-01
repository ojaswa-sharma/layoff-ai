from fastapi import APIRouter, Request, Depends, HTTPException
from models.commits import Commit
from typing import List
from services.git_diff import fetch_diff_from_webhook, count_diff_stats
import os
from services.db import get_mongo_db
from services.ai_service import summarize_and_upload
import asyncio

router = APIRouter(prefix="/github")

@router.post("/webhook")
async def webhook_github(request: Request, mongo=Depends(get_mongo_db)):
    try:
        request_data = await request.json()
        installation_id = request_data["installation"]["id"]
        app_id = os.getenv("APP_ID")
        
        pem_path = os.getenv("GITHUB_PEM_PATH", "isometrik.pem")
        
        with open(pem_path, 'r') as file:
            pem_data = file.read()
        
        collected = []
        repo_full_name = request_data["repository"]["full_name"]
        
        for commit in request_data["commits"]:
            full_commit_hash = commit["id"] 
            commit_hash = commit["id"][:12] 
            
            commit_api_url = f"https://api.github.com/repos/{repo_full_name}/commits/{full_commit_hash}"
            
            diff_text = await fetch_diff_from_webhook(
                commit_api_url, installation_id, app_id, pem_data
            )
            
            commit_model = Commit(
                commit_hash=commit_hash,
                message=commit["message"],
                author=commit["author"]["name"],
                email=commit["author"]["email"],
                date=commit["timestamp"],
                repository_name=request_data["repository"]["name"],
                repository_url=request_data["repository"]["html_url"],
                diff=diff_text,
                installation_id=installation_id,
                changes=count_diff_stats(diff_text=diff_text)
            )
            collected.append(commit_model.model_dump())
            asyncio.create_task(summarize_and_upload(diff_text,
                                            commit["author"]["name"],
                                            commit["author"]["email"],
                                            request_data["repository"]["name"],
                                            commit["message"],
                                            mongo,
                                            commit_hash=commit_hash
                                            ))

        if collected:
            mongo.commits.insert_many(collected)

        return {
            "message": "Webhook processed successfully", 
            "commits_count": len(collected)
        }
        
    except KeyError as e:
        print(e)
        raise HTTPException(status_code=400, detail=f"Missing required field: {str(e)}")
    except FileNotFoundError:
        print("DIDNT FIND THE PEMFILE")
        raise HTTPException(status_code=500, detail="PEM file not found")
    except Exception as e:
        print(e)
        raise HTTPException(status_code=500, detail=f"Error processing webhook: {str(e)}")