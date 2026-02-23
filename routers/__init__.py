from routers.bitbucket import router as bitbucket_router
from routers.github import router as github_router
from routers.users import router as users_router
from routers.plane import router as plane_router
from routers.jira import router as jira_router

_all = [
    bitbucket_router,
    github_router,
    users_router,
    plane_router,
    jira_router
]