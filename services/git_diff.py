import aiohttp

async def fetch_git_diff(url):
    diff_url = f"{url}.diff"
    print(diff_url)
    async with aiohttp.ClientSession() as session:
        async with session.get(diff_url) as response:
            return await response.text()
