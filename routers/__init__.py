from routers.bitbucket import router as bitbucket_router
from routers.github import router as github_router
from routers.users import router as users_router

_all = [
    bitbucket_router,
    github_router,
    users_router
]