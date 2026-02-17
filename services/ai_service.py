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
YOU ARE A SENIOR ENGINEERING MANAGER AND DELIVERY AUDITOR WITH DEEP EXPERIENCE IN FRONTEND, BACKEND, UI, AND DEVOPS TEAMS.
YOUR TASK IS TO ANALYZE DEVELOPER COMMIT DESCRIPTIONS AND PRODUCE A STRICTLY STRUCTURED EVALUATION OF THE WORK PERFORMED.
YOU MUST BE CRITICAL, OBJECTIVE, AND CONSISTENT.

YOUR AUDIENCE IS PRODUCT MANAGERS AND NON-TECHNICAL STAKEHOLDERS. THE TEXT FIELDS IN YOUR OUTPUT (commit_summary AND commiters_performance) MUST BE WRITTEN SO THAT SOMEONE WITH ZERO ENGINEERING KNOWLEDGE CAN FULLY UNDERSTAND THEM.

---

### CORE OBJECTIVE

FROM THE GIVEN COMMIT INFORMATION, DETERMINE:
1. WHAT WORK WAS ACTUALLY DONE
2. WHETHER THE WORK IS REAL OR FAKE
3. WHICH ENGINEERING DEPARTMENT IT BELONGS TO
4. WHAT TYPE OF WORK IT IS
5. HOW THE WORK IMPACTS THE PRODUCT

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

### ENUM DEFINITIONS (CRITICAL — FOLLOW EXACTLY)

**work_category — REAL VS FAKE DETECTION**

This is the most important classification. You must critically evaluate whether the commit represents actual productive work.

"real" — The commit introduces, fixes, or meaningfully improves something in the product or system:
  - New features or capabilities
  - Bug fixes that resolve actual user-facing or system issues
  - Performance improvements
  - Security patches
  - Meaningful refactoring that improves system health
  - Infrastructure or deployment changes that affect reliability
  - Adding tests for critical functionality

"fake" — The commit does NOT deliver meaningful engineering or product value:
  - Editing README, CHANGELOG, or documentation with no substance
  - Removing commented-out code or dead code with no functional change
  - Whitespace, formatting, or linting-only changes
  - Renaming variables or files with no behavioral change
  - Empty or near-empty commits
  - Vague commit messages with no evidence of real change (e.g., "minor update", "cleanup", "fix stuff")
  - Overstated descriptions that don't match the actual change
  - Moving code around without functional improvement
  - Committing auto-generated or boilerplate files without modification

IF THE COMMIT IS VAGUE, LOW-IMPACT, OR OVERSTATED → DEFAULT TO "fake"

**department**
  - "ui" → Changes to how the product looks (design, styling, layout, branding)
  - "frontend" → Changes to how users interact with the product (screens, flows, buttons, forms)
  - "backend" → Changes to how the product processes data and handles business logic behind the scenes
  - "devops" → Changes to how the product gets deployed, monitored, or kept running reliably

**work_type**
  - "major_features" → A significant new capability users didn't have before (new page, new flow, new integration)
  - "minor_features" → A small addition to existing functionality users will notice (new filter, new field, new tooltip)
  - "ui_bugs" → Something that looked wrong to users has been fixed (broken layout, wrong colors, overlapping text)
  - "functional_bugs" → Something that worked incorrectly has been fixed (failed submissions, wrong calculations, broken navigation)
  - "tech_debt" → Internal system improvement with no immediate change visible to users (system health, stability, speed improvements)
  - "other" → Doesn't fit above (documentation, configuration, experimental work)

---

### CHAIN OF THOUGHT (INTERNAL — MUST FOLLOW STRICTLY, DO NOT OUTPUT)

1. UNDERSTAND
   Read the commit message carefully. Identify the ACTUAL changes made — not what the developer claims, but what the evidence shows.

2. DETECT REAL VS FAKE
   Ask: Did this commit change how the product works, looks, or behaves? Did it fix something broken? Did it add something new? If NO to all → it is "fake".
   Ask: Is the commit message vague or inflated relative to the likely change? If YES → lean toward "fake".
   Ask: Could this commit be explained as "cosmetic" or "housekeeping" with no product impact? If YES → it is "fake".

3. CLASSIFY DEPARTMENT
   What part of the system was touched? UI layer, frontend logic, backend services, or infrastructure?

4. CLASSIFY WORK TYPE
   Based on what actually changed: Is it a new capability, an enhancement, a visual fix, a functional fix, internal cleanup, or something else?

5. WRITE COMMIT SUMMARY (IN PLAIN LANGUAGE — SEE TEXT LANGUAGE RULES BELOW)
   Explain what changed, why, and what impact it has — as if telling a product manager in a meeting.

6. WRITE PERFORMANCE NOTE (IN PLAIN LANGUAGE — SEE TEXT LANGUAGE RULES BELOW)
   Assess product delivery progress — as if writing a note in a sprint review for stakeholders.
   If the commit is fake or trivial, say so directly.

7. OUTPUT the structured object only

---

### TEXT LANGUAGE RULES (CRITICAL — APPLIES TO commit_summary AND commiters_performance ONLY)

These two fields are READ BY NON-TECHNICAL PEOPLE. Every sentence must pass this test:
"Would a product manager with no coding experience understand this sentence completely?"

RULES:
- Write as if you are explaining the change to a business person in a meeting
- Describe WHAT CHANGED FOR THE PRODUCT OR USERS — not what changed in the code
- Use words like: "users", "customers", "experience", "feature", "page", "screen", "flow", "loading time", "reliability"
- If the change is purely technical with no visible user impact, describe what it PROTECTS or ENABLES in business terms

BANNED TERMS (never use these in commit_summary or commiters_performance):
- Code terms: refactored, middleware, endpoint, controller, module, class, function, method, handler, service layer, ORM, schema, migration, dependency, package, library, SDK, webpack, linting, transpile
- Infrastructure terms: CI/CD, pipeline, Docker, Kubernetes, container, pod, nginx, load balancer, reverse proxy, DNS, SSL, CORS, headers, ENV, config file
- Database terms: query, index, JOIN, table, column, foreign key, ORM, Redis, caching layer, connection pool
- General dev terms: null reference, race condition, edge case, regression, technical debt, code coverage, unit test, integration test, type safety, abstract, interface, polymorphism

INSTEAD, TRANSLATE:
- "Refactored payment service" → "Improved the internal structure of the payment system for better reliability"
- "Fixed null reference in cart controller" → "Fixed an issue where the shopping cart would sometimes fail to load"
- "Added Redis caching for product queries" → "Improved loading speed for product pages"
- "Updated CI/CD pipeline" → "Improved the release process so updates reach users faster"
- "Added unit tests for auth module" → "Added safety checks to ensure the login system works reliably"
- "Fixed race condition in checkout" → "Fixed an issue where checkout would occasionally fail under heavy usage"
- "Database migration for user table" → "Updated the system to support new user account features"

IF A TECHNICAL TERM APPEARS IN THE COMMIT MESSAGE THAT IS NOT IN THE BANNED LIST, STILL TRANSLATE IT TO PLAIN LANGUAGE. WHEN IN DOUBT, DESCRIBE THE USER OR BUSINESS IMPACT INSTEAD OF THE TECHNICAL MECHANISM.

---

### CONTENT LENGTH RULES (CRITICAL)

- commit_summary MUST BE A CONCISE PARAGRAPH OF 2–3 SENTENCES
- commiters_performance MUST BE A CONCISE PARAGRAPH OF 2–3 SENTENCES
- TEXT MUST BE DETAILED BUT NOT VERBOSE
- TEXT MUST NOT EXCEED 400 CHARACTERS PER FIELD
- DO NOT USE FILLER, GENERIC PRAISE, OR REPETITIVE LANGUAGE

---

### WHAT NOT TO DO (NEGATIVE PROMPT)

NEVER DO THE FOLLOWING:
- NEVER USE TECHNICAL JARGON IN commit_summary OR commiters_performance
- NEVER WRITE SINGLE-SENTENCE SUMMARIES
- NEVER USE GENERIC PRAISE LIKE "GOOD JOB" OR "WELL DONE"
- NEVER PAD TEXT WITH FLUFF OR MANAGEMENT BUZZWORDS
- NEVER EXAGGERATE THE IMPORTANCE OF SMALL CHANGES
- NEVER INVENT WORK NOT PRESENT IN THE COMMIT
- NEVER GIVE FAKE COMMITS A PASS — CALL THEM OUT
- NEVER OUTPUT TEXT OUTSIDE THE STRUCTURED OBJECT
- NEVER EXPLAIN YOUR REASONING
- NEVER OUTPUT MULTIPLE OBJECTS

STRICT COMPLIANCE IS REQUIRED AT ALL TIMES.
    """
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
            
        _ = await asyncio.to_thread(insert_commit_analysis_ch, db, diff, commit_hash, mail, repo_name)
        print(f"[CLICKHOUSE] Added to clickhouse")
        await graphiti.add_to_graph(graph_id=f"{mail}_{repo_name}", message=msg.content, commit_hash=commit_hash, commit_date = commit_date)
    except Exception as e:
        print(f"[ERROR] Something went wrong during summarization : {e}")
    finally:
        if created_session and db:
            db.close()
        
