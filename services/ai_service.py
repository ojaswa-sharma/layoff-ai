from openai import AsyncOpenAI
import os
from models.commits import CommitDetails
from services.zep_store import get_personalizer, botMessage
import asyncio

_client = None

def get_openai():
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.getenv("OPENAI_KEY"))
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

    YOU MUST OUTPUT **ONE AND ONLY ONE OBJECT** WITH THE FOLLOWING STRUCTURE:

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

    #### WORK CATEGORY
    - "real" → MEANINGFUL, NECESSARY, OR IMPACTFUL ENGINEERING WORK
    - "fake" → COSMETIC, TRIVIAL, REDUNDANT, OR OVERSTATED WORK WITH LOW VALUE

    #### DEPARTMENT
    - "ui" → STYLING, LAYOUT, VISUAL ELEMENTS, DESIGN SYSTEMS
    - "frontend" → CLIENT-SIDE LOGIC, STATE MANAGEMENT, USER FLOWS
    - "backend" → APIS, DATABASES, BUSINESS LOGIC, SERVICES
    - "devops" → CI/CD, INFRASTRUCTURE, DEPLOYMENTS, MONITORING

    #### WORK TYPE
    - "major_features" → LARGE, CORE FUNCTIONALITY OR SYSTEM CHANGES
    - "minor_features" → SMALL ADDITIONS OR INCREMENTAL ENHANCEMENTS
    - "ui_bugs" → VISUAL, CSS, LAYOUT, OR RESPONSIVENESS BUGS
    - "functional_bugs" → BROKEN LOGIC, ERRORS, CRASHES, INCORRECT BEHAVIOR
    - "tech_debt" → REFACTORING, CLEANUP, PERFORMANCE, TESTS
    - "other" → DOES NOT CLEARLY MATCH THE ABOVE TYPES

    ---

    ### CHAIN OF THOUGHTS (INTERNAL — MUST FOLLOW STRICTLY)

    1. UNDERSTAND  
    READ THE COMMIT MESSAGE AND IDENTIFY THE ACTUAL CHANGE

    2. BASICS  
    IDENTIFY WHICH PART OF THE SYSTEM WAS TOUCHED (UI / FE / BE / DEVOPS)

    3. BREAK DOWN  
    DETERMINE WHETHER THIS IS FEATURE WORK, BUG FIXING, OR TECH DEBT

    4. ANALYZE  
    ASSESS IMPACT VS NOISE — IS THIS SUBSTANTIVE OR COSMETIC?

    5. BUILD  
    WRITE A CLEAR, ONE-SENTENCE COMMIT SUMMARY

    6. EDGE CASES  
    IF THE COMMIT IS VAGUE, INFLATED, OR LOW IMPACT → MARK AS "fake"

    7. FINAL ANSWER  
    OUTPUT THE STRUCTURED OBJECT ONLY

    ---

    ### COMMITTER PERFORMANCE RULES

    - BE DIRECT AND PROFESSIONAL
    - EVALUATE ENGINEERING VALUE AND CLARITY
    - DO NOT PRAISE LOW-IMPACT OR COSMETIC WORK

    EXAMPLES OF PERFORMANCE TEXT:
    - "Strong contribution addressing a meaningful backend issue."
    - "Minor UI change with limited engineering impact."
    - "Low-value refactor presented as significant work."

    ---

    ### FEW-SHOT EXAMPLES

    INPUT:
    "Fix broken API response when user session expires"

    OUTPUT:
    CommitDetails:
    - commit_summary: "Fixed API response handling for expired user sessions"
    - work_category: "real"
    - department: "backend"
    - commiters_performance: "Clear and valuable fix resolving a real functional bug."
    - work_type: "functional_bugs"

    ---

    INPUT:
    "Adjusted button colors and spacing"

    OUTPUT:
    CommitDetails:
    - commit_summary: "Adjusted button colors and spacing"
    - work_category: "fake"
    - department: "ui"
    - commiters_performance: "Cosmetic UI change with minimal functional value."
    - work_type: "ui_bugs"

    ---

    ### WHAT NOT TO DO (NEGATIVE PROMPT)

    NEVER DO THE FOLLOWING:
    - NEVER OUTPUT TEXT OUTSIDE THE STRUCTURED OBJECT
    - NEVER INVENT WORK THAT IS NOT PRESENT IN THE COMMIT
    - NEVER USE ENUM VALUES OUTSIDE THE DEFINED LISTS
    - NEVER CLASSIFY COSMETIC WORK AS MAJOR FEATURES
    - NEVER BE OVERLY GENEROUS IN PERFORMANCE EVALUATION
    - NEVER ASK QUESTIONS OR REQUEST MORE INFORMATION
    - NEVER OUTPUT MULTIPLE OBJECTS
    - NEVER EXPLAIN YOUR REASONING

    STRICT COMPLIANCE IS REQUIRED AT ALL TIMES.

    </SYSTEM_PROMPT>

    """

    resp = await openai.responses.parse(
        model="gpt-4.1-nano",
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

async def summarize_and_upload(diff_text, name, mail, repo_name, commit_title, db):
    diff = await summarie_diff(get_openai(), diff_text, name, mail, repo_name, commit_title)
    diff["mail"] = mail
    diff["repo_name"] = repo_name
    zep = get_personalizer()
    msg = botMessage(role = "assistant", content=f"""
        # WORK DONE BY YOU({name}) FOR THIS COMMIT:             

        # Commit summary:
            {diff.get("commit_summmary")}

        # Department:
            {diff.get("department")}

        # Commiter's performance:
            {diff.get("commiters_performance")}

        # Diff:
            {diff_text}
        """)
    await asyncio.gather(zep.add_message(user_id = f"user_{mail}", message=msg, thread_id=repo_name, first_name=name, email=mail, repo_name=repo_name),
                         asyncio.to_thread(db.commit_summary.insert_one,diff)
                         )

