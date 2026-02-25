"""
Project context definitions for repository-level awareness.

Maps repository names to descriptions so the AI can evaluate commits
with knowledge of what each project is actually about.

To add a new project, simply add an entry to PROJECT_CONTEXT below.
Keys should be lowercase repo names (without the org/workspace prefix).
"""

PROJECT_CONTEXT = {
    # ── House of Apps — AI Engineering Manager ────────────────────────
    "house-of-apps-ai-engineering-manager": {
        "description": (
            "AI-powered engineering manager that monitors developer activity "
            "across GitHub and Bitbucket repositories. It automatically reviews "
            "every commit in real-time, classifies the work as real or unproductive, "
            "identifies which team (UI, frontend, backend, or devops) it belongs to, "
            "and generates plain-language summaries that non-technical stakeholders "
            "can understand. The product gives engineering managers and product managers "
            "full visibility into what developers are actually delivering — including "
            "individual performance assessments, project-level insights, and historical "
            "contribution tracking. When a new repository is connected, the system "
            "automatically catches up on past commits so nothing is missed."
            "This is a backend AI assistant side repository for the Eazy Chatbot product"
            "This is our in house product ."
        ),
        "tech_stack": (
            "Python 3.11, FastAPI with Uvicorn/Gunicorn, OpenAI API, "
            "ClickHouse (via SQLAlchemy + clickhouse-sqlalchemy), "
            "Graphiti Core with FalkorDB (knowledge graph), "
            "Apache Kafka (aiokafka) for async commit processing, "
            "GitHub & Bitbucket webhook integrations, Docker"
        ),
    },
    # ── Eazy Chatbot — AI Assistant ─────────────────────────────────────
    "isometrik-aws-orchestrator-multi-agent": {
    "description": (
        "zAIn — an AI-powered concierge chatbot embedded in the Eazy Life super-app. "
        "It lets end users discover nearby stores, search and browse products, manage "
        "a shopping cart, select delivery addresses and payment methods, and place "
        "orders — all through natural-language conversation. The system covers six "
        "service categories: Food & Restaurants, Groceries, Pharmacies, Healthcare, "
        "Home Services, and Retail Shopping. For healthcare and pharmacy orders it "
        "also handles prescription uploads. For home services it supports staff "
        "selection, service-type choice (in-call, out-call, tele-call), and "
        "appointment scheduling. Under the hood a multi-agent supervisor architecture "
        "routes each user request to the right specialist agent (store search, product "
        "search, cart, address, payment, ordering, or service booking) so the "
        "conversation feels seamless. Responses stream back in real time via SSE, and "
        "long-term user memory powered by Zep Cloud enables personalised "
        "recommendations based on weather, time of day, and past preferences."
        "This is a backend AI assistant side repository for the Eazy Chatbot product"
        "This is for client  Eazy Life super-app"
    ),
    "tech_stack": (
        "Python 3.11+ FastAPI backend,AWS Agent squad framework, OpenAI GPT-4o-mini / GPT-4.1-mini, "
        "Hawk Search API, Zep Cloud (memory & personalisation), Eazy Appside API's "
        "PostgreSQL + Alembic migrations, Langfuse observability"
    ),
    },
    # ── New Kommerce & QYKLY — Corporate Gifting Platform ────────────────────────────
    "vybe-ai-frontend": {
        "description": (
            "Vybe is a corporate gifting platform that helps businesses give thoughtful, on-brand gifts at scale. "
            "It is used by HR for employee recognition and morale, by Marketing for events and swag, by Sales for client gifting, and by Customer Success to strengthen relationships. "
            "Users can browse and search a product catalog, build carts, request quotations, place orders, and manage proforma invoices, favorites, delivery addresses, and company and team settings. "
            "The product supports personalized and bulk gifting, multi-language experiences, and a visual page builder so teams can customize landing and marketing pages. "
            "Behind the scenes it connects to a central API for catalog, orders, and accounts, and uses search and analytics to power discovery and insights."
            "This is a frontend repository for the Vybe AI product."
            "This is for client  New Kommerce & QYKLY "
        ),
        "tech_stack": (
            "TypeScript, Next.js 14, React 18, Redux Toolkit with RTK Query, Tailwind CSS, Radix UI, "
            "@measured/puck page builder, Typesense search, Rudderstack analytics, Google OAuth, "
            "i18next and next-i18n-router (EN/FR/IT), react-hook-form with Zod, Framer Motion, "
            "REST API backend (e.g. api.qykly.com), Google Maps API, ipinfo.io"
        ),
    },
    "house-of-apps-legal-ai-fast-api": {
    "description": (
        "This product is the backend for the House of Apps Legal AI platform, which helps law firms and legal practices manage their operations in one place. "
        "Staff and admins use it to manage organizations, teams, and permissions; to store and manage clients (individuals and companies) with contacts, addresses, lead intake, and optional automatic client data enrichment; and to track matters as projects with billing, team assignments, and practice areas. "
        "Clients can be given secure portal access, and the system supports custom field definitions so each organization can tailor how they capture data for companies, contacts, and leads. "
        "Behind the scenes it handles authentication and sessions, audit logging, file uploads via presigned URLs, and optional integrations with external services for identity and enrichment."
        "This is for our  in house product Legal AI"
    ),
    "tech_stack": (
        "Python 3.13, FastAPI, Pydantic Settings, asyncpg, PostgreSQL, pgvector, Supabase Auth, "
        "OpenAI client, Typesense, SlowAPI, JWT middleware, Datadog ddtrace, boto3 (AWS S3 / Cloudflare R2), "
        "Isometrik API (optional), pytest, pytest-asyncio, pytest-cov"
    ),
}
    # ── If you want to add more repos below follow the format below ─────────────────────────────────────────
    #"repository_name": {
    #    "description": (
    #        "Description of the repository"
    #    ),
    #    "tech_stack": (
    #        "Tech stack of the repository"
    #    ),
    #},
}


def get_project_context(repo_name: str) -> str:
    """
    Look up project context for a given repo name.

    Performs a case-insensitive partial match so that:
      - "My-Ecommerce-App"          matches "my-ecommerce-app"
      - "org/my-ecommerce-app"      matches "my-ecommerce-app"
      - "my-ecommerce-app-backend"  matches "my-ecommerce-app"

    Returns a formatted context string, or a fallback message if no match.
    """
    repo_lower = repo_name.lower().strip()

    for key, ctx in PROJECT_CONTEXT.items():
        key_lower = key.lower()
        if key_lower in repo_lower or repo_lower in key_lower:
            parts = [f"Project: {key}"]
            if ctx.get("description"):
                parts.append(f"About: {ctx['description']}")
            if ctx.get("tech_stack"):
                parts.append(f"Tech Stack: {ctx['tech_stack']}")
            return "\n".join(parts)

    return "No project context available for this repository."
