from fastapi import APIRouter, Request

router = APIRouter(prefix="/github")


@router.post("/webhook")
async def webhook_github(request: Request):
    ...
    request_data = await request.json()
    print(request_data)
    return {"message": request_data}

print("router.routes")