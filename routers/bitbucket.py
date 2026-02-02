from fastapi import APIRouter, Request

router = APIRouter(prefix="/bitbucket")


@router.post('/webhook')
async def hook_bitbucket(
    request : Request
):
    print(await request.json())