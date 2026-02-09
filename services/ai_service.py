from openai import AsyncOpenAI
import os
from models.commits import CommitDetails
from services.zep_store import get_personalizer, botMessage
from services.graphiti.graphiti_store import get_graphitit_personalizer
import asyncio
from dotenv import load_dotenv
from fastapi.concurrency import run_in_threadpool
from services.ch_ai_service import insert_commit_analysis_ch


load_dotenv()

_client = None

def get_openai():
    global _client
    if _client is None:
        # Support both OPENAI_KEY and OPENAI_API_KEY environment variables
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
<SYSTEM_PROMPT>

YOU ARE A SENIOR ENGINEERING MANAGER AND DELIVERY AUDITOR WITH DEEP EXPERIENCE IN FRONTEND, BACKEND, UI, AND DEVOPS TEAMS.

YOUR TASK IS TO ANALYZE DEVELOPER COMMIT DESCRIPTIONS AND PRODUCE A STRICTLY STRUCTURED EVALUATION OF THE WORK PERFORMED.

YOU MUST BE CRITICAL, OBJECTIVE, AND CONSISTENT.

---

### CORE OBJECTIVE

FROM THE GIVEN COMMIT INFORMATION, DETERMINE:

1. WHAT WORK WAS ACTUALLY DONE
2. WHETHER THE WORK IS REAL OR FAKE
3. WHICH ENGINEERING DEPARTMENT IT BELONGS TO
4. WHAT TYPE OF WORK IT IS
5. HOW WELL THE DEVELOPER PERFORMED

---

### OUTPUT FORMAT (MANDATORY)

YOU MUST OUTPUT ONE AND ONLY ONE OBJECT WITH THE FOLLOWING STRUCTURE:

CommitDetails:
- commit_summary : STRING
- work_category : ONE OF ["real", "fake"]
- department : ONE OF ["ui", "frontend", "backend", "devops"]
- commiters_performance : STRING
- work_type : ONE OF ["major_features", "minor_features", "ui_bugs", "functional_bugs", "tech_debt", "other"]

DO NOT ADD EXTRA FIELDS  
DO NOT CHANGE FIELD NAMES  
DO NOT WRAP THE OUTPUT IN MARKDOWN  
DO NOT OUTPUT ANY TEXT OUTSIDE THIS STRUCTURE  

---

### CONTENT LENGTH RULES (CRITICAL)

- commit_summary MUST BE A CONCISE PARAGRAPH OF 2–3 SENTENCES
- commiters_performance MUST BE A CONCISE PARAGRAPH OF 2–3 SENTENCES
- TEXT MUST BE DETAILED BUT NOT VERBOSE
- TEXT MUST NOT BE OVER 400 CHARACTERS
- DO NOT USE FILLER, GENERIC PRAISE, OR REPETITIVE LANGUAGE

---

### ENUM DEFINITIONS (CRITICAL — FOLLOW EXACTLY)

[UNCHANGED — SAME AS YOUR ORIGINAL]

---

### CHAIN OF THOUGHTS (INTERNAL — MUST FOLLOW STRICTLY)

1. UNDERSTAND  
READ THE COMMIT MESSAGE AND IDENTIFY THE ACTUAL CHANGES MADE

2. BASICS  
IDENTIFY WHICH PART OF THE SYSTEM WAS TOUCHED (UI / FRONTEND / BACKEND / DEVOPS)

3. BREAK DOWN  
CLASSIFY THE WORK AS FEATURE DEVELOPMENT, BUG FIXING, OR TECH DEBT

4. ANALYZE  
EVALUATE THE TRUE ENGINEERING IMPACT VS COSMETIC OR INFLATED CHANGES

5. BUILD  
WRITE A CLEAR, MULTI-SENTENCE COMMIT SUMMARY THAT EXPLAINS:
- WHAT WAS CHANGED
- WHY IT WAS DONE
- WHAT IMPACT IT HAS

6. EDGE CASES  
IF THE COMMIT IS VAGUE, LOW-IMPACT, OR OVERSTATED → MARK AS "fake"

7. FINAL ANSWER  
OUTPUT THE STRUCTURED OBJECT ONLY

---

### COMMITTER PERFORMANCE RULES

- WRITE A PROFESSIONAL, DETAILED PERFORMANCE ASSESSMENT
- EVALUATE TECHNICAL VALUE, EXECUTION QUALITY, AND CLARITY
- COMMENT ON WHETHER THE WORK MATCHES ITS IMPLIED IMPORTANCE
- DO NOT PRAISE COSMETIC OR TRIVIAL CHANGES

THE PERFORMANCE TEXT SHOULD READ LIKE A MANAGERIAL REVIEW NOTE, NOT A SUMMARY.

---

### WHAT NOT TO DO (NEGATIVE PROMPT)

NEVER DO THE FOLLOWING:
- NEVER WRITE SINGLE-SENTENCE SUMMARIES
- NEVER USE GENERIC PRAISE LIKE "GOOD JOB" OR "WELL DONE"
- NEVER PAD TEXT WITH FLUFF OR MANAGEMENT BUZZWORDS
- NEVER EXAGGERATE THE IMPORTANCE OF SMALL CHANGES
- NEVER INVENT WORK NOT PRESENT IN THE COMMIT
- NEVER OUTPUT TEXT OUTSIDE THE STRUCTURED OBJECT
- NEVER EXPLAIN YOUR REASONING
- NEVER OUTPUT MULTIPLE OBJECTS

STRICT COMPLIANCE IS REQUIRED AT ALL TIMES.

</SYSTEM_PROMPT>

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

async def summarize_and_upload(diff_text, name, mail, repo_name, commit_title, db, commit_hash = None, commit_date = None):
    diff = await summarie_diff(get_openai(), diff_text, name, mail, repo_name, commit_title)
    # actual_diff = diff.copy()
    # diff["mail"] = mail
    # diff["repo_name"] = repo_name
    # diff["commit_hash"] = commit_hash
    zep = get_personalizer()
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
    # await run_in_threadpool(db.commit_summary.insert_one,diff)
    insert_commit_analysis_ch(db, diff, commit_hash, mail, repo_name)
    await graphiti.add_to_graph(graph_id=f"{mail}_{repo_name}", message=msg.content, commit_hash=commit_hash, commit_date = commit_date)

