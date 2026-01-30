import aiohttp

async def fetch_git_diff(url):
    diff_url = f"{url}.diff"
    print(diff_url)
    headers = {
        "User-Agent": "layoff-ai",
        "Accept": "application/vnd.github.v3.diff",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(diff_url) as response:
            return await response.text()
