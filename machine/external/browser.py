"""
Browser automation service — connects to anti-detect browser profiles via CDP.

Uses local browser API to launch profiles and Playwright to automate them.
Playwright runs synchronously in a thread to avoid Windows asyncio subprocess issues.
"""

import asyncio
import logging
import sys

import httpx
from playwright.sync_api import sync_playwright

# Python 3.14 on Windows: asyncio.new_event_loop() defaults to SelectorEventLoop
# which doesn't support subprocess. Playwright needs ProactorEventLoop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from core.exceptions.http import ExternalAPIException
from core.settings import get_settings

logger = logging.getLogger(__name__)

class BrowserService:
    """Manages browser profile connections via local API + Playwright CDP."""

    @classmethod
    async def _api_get(cls, path: str) -> dict:
        """GET request to local browser API."""
        url = f"{get_settings().BROWSER_API_URL.rstrip('/')}{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            raise ExternalAPIException(
                detail=f"Browser API error: {resp.status_code} {resp.text[:200]}"
            )
        return resp.json()

    @classmethod
    async def _api_post(cls, path: str, body: dict | None = None) -> dict:
        """POST request to local browser API."""
        url = f"{get_settings().BROWSER_API_URL.rstrip('/')}{path}"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=body or {})
        if resp.status_code != 200:
            raise ExternalAPIException(
                detail=f"Browser API error: {resp.status_code} {resp.text[:200]}"
            )
        return resp.json()

    @classmethod
    async def launch_profile(cls, profile_id: str) -> dict:
        """Launch a browser profile and return connection info.

        If the profile is already running, fetches its status instead.
        """
        url = f"{get_settings().BROWSER_API_URL.rstrip('/')}/profiles/{profile_id}/launch"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json={})

        if resp.status_code == 200:
            data = resp.json()
            logger.info("Launched profile %s: %s", profile_id, data)
            return data

        # Profile already running — get status instead
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        already_open = "already" in str(body.get("error", "")).lower()
        if resp.status_code == 400 and already_open:
            logger.info("Profile %s already open — fetching status", profile_id)
            return await cls.get_profile_status(profile_id)

        raise ExternalAPIException(
            detail=f"Browser API error: {resp.status_code} {resp.text[:200]}"
        )

    @classmethod
    async def close_profile(cls, profile_id: str) -> dict:
        """Close a running browser profile."""
        data = await cls._api_post(f"/profiles/{profile_id}/close")
        logger.info("Closed profile %s", profile_id)
        return data

    @classmethod
    async def get_profile_status(cls, profile_id: str) -> dict:
        """Check if a profile is running."""
        return await cls._api_get(f"/profiles/{profile_id}/status")

    @classmethod
    async def get_cdp_endpoint(cls, profile_id: str) -> str:
        """Launch profile and resolve the CDP WebSocket endpoint URL.

        Returns:
            WebSocket URL string (e.g. ws://127.0.0.1:9227/devtools/browser/...).
        """
        try:
            launch_resp = await cls.launch_profile(profile_id)
        except httpx.ConnectError:
            raise ExternalAPIException(
                detail="Browser manager is not running. Start it first."
            )

        # Response may nest actual data under "data" key
        launch_data = launch_resp.get("data", launch_resp)

        # Try direct WebSocket endpoint fields first
        ws_endpoint = (
            launch_data.get("wsEndpoint")
            or launch_data.get("ws")
            or launch_data.get("browserWSEndpoint")
            or launch_data.get("automation", {}).get("wsEndpoint")
        )
        if ws_endpoint:
            return ws_endpoint

        # Get port and fetch real WS URL from /json/version
        port = launch_data.get("port") or launch_data.get("debugPort")
        if not port:
            debug_url = launch_data.get("debugUrl", "")
            if debug_url:
                port = int(debug_url.rstrip("/").rsplit(":", 1)[-1])

        if not port:
            raise ExternalAPIException(
                detail=f"No CDP endpoint in launch response: {launch_resp}"
            )

        # Fetch webSocketDebuggerUrl from Chrome DevTools
        url = f"http://127.0.0.1:{port}/json/version"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
        except httpx.ConnectError:
            raise ExternalAPIException(
                detail=f"Browser profile not reachable on port {port}. "
                       f"Make sure the browser manager is running and the profile is open."
            )
        if resp.status_code != 200:
            raise ExternalAPIException(
                detail=f"Failed to get CDP info from port {port}: {resp.status_code}"
            )
        data = resp.json()
        ws_url = data.get("webSocketDebuggerUrl", "")
        if not ws_url:
            raise ExternalAPIException(
                detail=f"No webSocketDebuggerUrl in /json/version: {data}"
            )
        logger.info("Resolved CDP endpoint: %s", ws_url)
        return ws_url

    @staticmethod
    def connect_sync(ws_endpoint: str):
        """Connect Playwright (sync) to a CDP endpoint.

        Returns:
            Tuple of (playwright_instance, browser, context, page).
            Caller must call pw.stop() when done.
        """
        pw = sync_playwright().start()
        try:
            browser = pw.chromium.connect_over_cdp(ws_endpoint)
            contexts = browser.contexts
            if contexts:
                context = contexts[0]
                pages = context.pages
                page = pages[0] if pages else context.new_page()
            else:
                context = browser.new_context()
                page = context.new_page()
            return pw, browser, context, page
        except Exception as e:
            pw.stop()
            raise ExternalAPIException(detail=f"Playwright CDP connection failed: {e}")
