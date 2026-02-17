# from openai import AsyncOpenAI
from langfuse.openai import AsyncOpenAI
from openai import APIStatusError
import os
from models.commits import CommitDetails
from models.graphiti_input import botMessage
from services.graphiti.graphiti_store import get_graphitit_personalizer
import asyncio
from dotenv import load_dotenv
from services.clickhouse_service.ch_ai_service import insert_commit_analysis_ch
from dependencies.ch_db import get_ch_session_direct
from datetime import datetime
from misc.prompts import summarizer_prompt

load_dotenv()

_client = None

def get_openai():
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OpenAI API key not found. Please set either OPENAI_KEY or OPENAI_API_KEY environment variable."
            )
        _client = AsyncOpenAI(api_key=api_key)
    return _client

async def summarie_diff(openai:AsyncOpenAI, diff_text, name, mail, repo_name, commit_title):
    user_prompt =f"""
    Summarize this commit, be precise, and calculative. The goal is to determine whether the developer is doing his work properly.
    # Diff text:
    {diff_text}

    # Commit title:
    {commit_title}

    # Repo Name:
    {repo_name}
    """
    system_prompt = summarizer_prompt
    for _retry in range(int(os.getenv("OPENAI_RETRIES", 30))):
        try:
            resp = await openai.responses.parse(
                model="gpt-5-nano",
                reasoning={"effort" : "minimal"},
                input=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                ],
                text_format=CommitDetails,
            )
            return {
                "commit_summmary" : resp.output_parsed.commit_summary,
                "work_category" : resp.output_parsed.work_category.value,
                "department" : resp.output_parsed.department.value,
                "commiters_performance" : resp.output_parsed.commiters_performance,
                "work_type" : resp.output_parsed.work_type.value
            }
        except APIStatusError as e:
            if e.status_code == 429:
                await asyncio.sleep(60)

    return {
        "commit_summmary" : "Failed",
        "work_category" : "Failed",
        "department" : "Failed",
        "commiters_performance" : "Failed",
        "work_type" : "Failed"
    }


async def summarize_and_upload(diff_text, name, mail, repo_name, commit_title, db = None, commit_hash = None, commit_date = None, additions = 0, deletions = 0):
    created_session = False
    try:
        if isinstance(commit_date, str):
            commit_date = datetime.fromisoformat(commit_date)
        diff = await summarie_diff(get_openai(), diff_text, name, mail, repo_name, commit_title)
        diff["commit_hash"]  = commit_hash
        diff["commit_title"] = commit_title
        diff["commit_date"]  = commit_date
        diff["additions"]    = additions
        diff["deletions"]    = deletions

        graphiti = get_graphitit_personalizer()
        msg = botMessage(role="norole", content=f"""
    Repository: {repo_name}
    Developer: {name}
    Commit hash : {commit_hash}

    Commit Summary:
    {diff.get("commit_summmary")}

    Performance Assessment:
    {diff.get("commiters_performance")}
    """)
        print(f"[DEBUG] Extraction successful, moving to db and zep")
        if diff.get("work_type") != "Failed":
            await graphiti.add_message(user_id = f"user_{mail}", message=msg, thread_id=repo_name, first_name=name, email=mail, repo_name=repo_name, date=commit_date)
        if not db:
            db = get_ch_session_direct()
            created_session = True
            
        _ = await asyncio.to_thread(insert_commit_analysis_ch, db, diff, commit_hash, mail, repo_name)
        print(f"[CLICKHOUSE] Added to clickhouse")

        # if diff.get("work_type") != "Failed":
        #     await graphiti.add_to_graph(graph_id=f"{mail}_{repo_name}", message=msg.content, commit_hash=commit_hash, commit_date = commit_date)
    except Exception as e:
        print(f"[ERROR] Something went wrong during summarization : {e}")
    finally:
        if created_session and db:
            db.close()
        
