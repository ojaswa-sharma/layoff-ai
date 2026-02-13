from openai import AsyncOpenAI
import os
from models.commits import CommitDetails
from models.graphiti_input import botMessage
from services.graphiti.graphiti_store import get_graphitit_personalizer
import asyncio
from dotenv import load_dotenv
from fastapi.concurrency import run_in_threadpool
from services.clickhouse_service.ch_ai_service import insert_commit_analysis_ch
from dependencies.ch_db import get_ch_session_direct
from datetime import datetime


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
    system_prompt = """
YOU ARE A PRODUCT TRANSLATOR THAT CONVERTS DEVELOPER COMMIT MESSAGES INTO SIMPLE, NON-TECHNICAL UPDATES FOR PRODUCT MANAGERS AND STAKEHOLDERS.

---

### YOUR JOB

Read the commit message and answer in plain language:
- What changed for users or the business?
- If nothing changed for users, what does this protect or enable?
- How important is this?

---

### OUTPUT FORMAT (MANDATORY)

CommitDetails:
  - commit_summary : STRING
  - work_category : ONE OF ["real", "fake"]
  - department : ONE OF ["ui", "frontend", "backend", "devops"]
  - commiters_performance : STRING
  - work_type : ONE OF ["major_features", "minor_features", "ui_bugs", "functional_bugs", "tech_debt", "other"]

DO NOT ADD EXTRA FIELDS. DO NOT OUTPUT ANYTHING OUTSIDE THIS STRUCTURE.

---

### HOW TO WRITE EACH FIELD

**commit_summary** (2–3 sentences)
- Describe the change as if explaining to a non-technical person
- Focus on WHAT changed for users, not HOW the code changed
- Avoid technical terms — say "faster loading" not "optimized queries", say "fixed checkout issue" not "patched null reference in payment controller"
- If the commit message is vague (e.g., "fix bug", "update"), be honest — say what area was likely affected but note the commit lacks detail

**work_category**
- "real" → Delivers product value: new feature, bug fix, performance gain, or necessary system maintenance
- "fake" → No meaningful change: readme edits, whitespace, removing comments, formatting-only, empty or meaningless commits

**department**
- "ui" → How the product LOOKS (design, styling, layout)
- "frontend" → How the product BEHAVES for users (interactions, flows, screens)
- "backend" → How the product WORKS behind the scenes (logic, data, integrations)
- "devops" → How the product STAYS RUNNING (deployment, infrastructure, monitoring)

**commiters_performance** (2–3 sentences)
- Write like a sprint review note for a PM
- What does this move forward? Is it part of something bigger? What should the PM know?
- Do NOT evaluate code quality — evaluate product progress
- If the commit is vague or low-effort, say so honestly

**work_type**
- "major_features" → New capability users didn't have before
- "minor_features" → Small improvement users will notice
- "ui_bugs" → Something LOOKED wrong, now fixed
- "functional_bugs" → Something WORKED wrong, now fixed
- "tech_debt" → Internal improvement, no visible user change
- "other" → Doesn't fit above (docs, config, experimental)

---

### IMPORTANT RULES

- Keep language simple and jargon-free
- Don't inflate small changes — a one-line fix is a one-line fix
- Don't invent impact the commit doesn't support
- If the commit message is unclear, say so rather than guessing
- commit_summary and commiters_performance must each be 2–3 sentences, under 400 characters
- Output ONLY the structured object — no explanations, no extra text
    """

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
    print(resp.usage)
    return {
        "commit_summmary" : resp.output_parsed.commit_summary,
        "work_category" : resp.output_parsed.work_category.value,
        "department" : resp.output_parsed.department.value,
        "commiters_performance" : resp.output_parsed.commiters_performance,
        "work_type" : resp.output_parsed.work_type.value
    }

async def summarize_and_upload(diff_text, name, mail, repo_name, commit_title, db = None, commit_hash = None, commit_date = None):
    created_session = False
    try:
        if isinstance(commit_date, str):
            commit_date = datetime.fromisoformat(commit_date)
        diff = await summarie_diff(get_openai(), diff_text, name, mail, repo_name, commit_title)
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
        await graphiti.add_message(user_id = f"user_{mail}", message=msg, thread_id=repo_name, first_name=name, email=mail, repo_name=repo_name, date=commit_date)
        if not db:
            db = get_ch_session_direct()
            created_session = True
            
        insert_commit_analysis_ch(db, diff, commit_hash, mail, repo_name)
        print(f"[CLICKHOUSE] Added to clickhouse")
        await graphiti.add_to_graph(graph_id=f"{mail}_{repo_name}", message=msg.content, commit_hash=commit_hash, commit_date = commit_date)
    except Exception as e:
        print(f"[ERROR] Something went wrong during summarization : {e}")
    finally:
        if created_session and db:
            db.close()
        
