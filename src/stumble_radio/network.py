import asyncio
from urllib.parse import urlsplit

from .api import BOOTSTRAP

RETRY_BASE_SECONDS = 1
RETRY_MAX_SECONDS = 30
NETWORK_POLL_SECONDS = 5


def retry_delay(attempt: int) -> int:
    return min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * 2 ** min(max(attempt - 1, 0), 5))


async def internet_available(stream_url: str) -> bool:
    """Check reachability after failure, without downloading audio or directory data."""
    stream = urlsplit(stream_url)
    targets = {
        (stream.hostname, stream.port or (443 if stream.scheme == "https" else 80)),
        (urlsplit(BOOTSTRAP).hostname, 443),
    }

    async def reachable(host, port):
        writer = None
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3)
            return True
        except (OSError, TimeoutError):
            return False
        finally:
            if writer:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass

    tasks = [asyncio.create_task(reachable(host, port)) for host, port in targets if host]
    try:
        for result in asyncio.as_completed(tasks):
            if await result:
                return True
        return False
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
