import aiohttp
import os

_client = None

def init_auth_client():
    global _client
    if _client:
        return
    connector = aiohttp.TCPConnector(
        limit=100,
        limit_per_host=20,
        ttl_dns_cache=300,
        ssl=False
    )
    _client = aiohttp.ClientSession(
        base_url=os.getenv("AUTH_SERVICE_BASE"),
        connector=connector,
        timeout=aiohttp.ClientTimeout(
            total=10,
            connect=2,
            sock_read=5
        )
    )

async def stop_session():
    global _client
    if not _client:
        return
    await _client.close()

def get_client():
    if not _client:
        init_auth_client()
    return _client