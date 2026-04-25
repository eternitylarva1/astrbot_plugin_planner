"""API Client for Schedule App Backend."""

import aiohttp
import logging
from typing import Any, Optional, List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class ApiClient:
    """HTTP API client for schedule_app backend."""

    def __init__(self, base_url: str = "http://localhost:8080"):
        """Initialize API client.

        Args:
            base_url: Base URL of schedule_app backend
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=30)

    def _url(self, path: str) -> str:
        """Build full URL."""
        return f"{self.base_url}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """Make HTTP request to API.

        Returns:
            Response data dict, or None on error
        """
        url = self._url(path)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method,
                    url,
                    json=json_data,
                    params=params,
                    timeout=self.timeout,
                ) as resp:
                    if resp.status == 204:
                        return {}
                    data = await resp.json()
                    if data.get("code") == 0 or resp.status == 200:
                        return data.get("data", data)
                    else:
                        error_msg = data.get("message", f"API error {resp.status}")
                        logger.error(f"API {method} {url} failed: {error_msg}")
                        return None
        except aiohttp.ClientError as e:
            logger.error(f"Network error calling {method} {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error calling {method} {url}: {e}")
            return None

    async def get_events(self, date_filter: str = "today") -> Optional[List[Dict]]:
        """Get events by date filter.

        Args:
            date_filter: today|week|month|all|YYYY-MM-DD|YYYY-MM

        Returns:
            List of event dicts
        """
        result = await self._request("GET", "/api/events", params={"date": date_filter})
        return result if isinstance(result, list) else None

    async def create_event(self, event_data: Dict) -> Optional[Dict]:
        """Create event.

        Args:
            event_data: Event fields (title, start_time, end_time, category_id, etc.)

        Returns:
            Created event dict
        """
        return await self._request("POST", "/api/events", json_data=event_data)

    async def update_event(self, event_id: int, event_data: Dict) -> Optional[Dict]:
        """Update event.

        Args:
            event_id: Event ID
            event_data: Updated event fields

        Returns:
            Updated event dict
        """
        return await self._request(
            "PUT", f"/api/events/{event_id}", json_data=event_data
        )

    async def delete_event(self, event_id: int) -> bool:
        """Delete event.

        Args:
            event_id: Event ID

        Returns:
            True if deleted
        """
        result = await self._request("DELETE", f"/api/events/{event_id}")
        return result is not None

    async def complete_event(self, event_id: int) -> Optional[Dict]:
        """Mark event as complete.

        Args:
            event_id: Event ID

        Returns:
            Updated event dict
        """
        return await self._request("PUT", f"/api/events/{event_id}/complete")

    async def uncomplete_event(self, event_id: int) -> Optional[Dict]:
        """Mark event back to pending.

        Args:
            event_id: Event ID

        Returns:
            Updated event dict
        """
        return await self._request("PUT", f"/api/events/{event_id}/uncomplete")

    async def get_categories(self) -> List[Dict]:
        """Get event categories.

        Returns:
            List of category dicts
        """
        result = await self._request("GET", "/api/categories")
        return result if isinstance(result, list) else []

    async def get_goals(self, horizon: Optional[str] = None) -> Optional[List[Dict]]:
        """Get goals.

        Args:
            horizon: short|semester|long or None for all

        Returns:
            List of goal dicts
        """
        params = {"horizon": horizon} if horizon else None
        result = await self._request("GET", "/api/goals", params=params)
        return result if isinstance(result, list) else None

    async def create_goal(self, goal_data: Dict) -> Optional[Dict]:
        """Create goal.

        Args:
            goal_data: Goal fields (title, horizon, description, etc.)

        Returns:
            Created goal dict
        """
        return await self._request("POST", "/api/goals", json_data=goal_data)

    async def update_goal(self, goal_id: int, goal_data: Dict) -> Optional[Dict]:
        """Update goal.

        Args:
            goal_id: Goal ID
            goal_data: Updated goal fields

        Returns:
            Updated goal dict
        """
        return await self._request("PUT", f"/api/goals/{goal_id}", json_data=goal_data)

    async def delete_goal(self, goal_id: int) -> bool:
        """Delete goal.

        Args:
            goal_id: Goal ID

        Returns:
            True if deleted
        """
        result = await self._request("DELETE", f"/api/goals/{goal_id}")
        return result is not None

    async def get_goal_tree(self, goal_id: int) -> Optional[Dict]:
        """Get goal with full subtask tree.

        Args:
            goal_id: Goal ID

        Returns:
            Goal tree dict
        """
        return await self._request("GET", f"/api/goals/{goal_id}/tree")

    async def get_goal_subtasks(self, goal_id: int) -> Optional[List[Dict]]:
        """Get direct subtasks of a goal.

        Args:
            goal_id: Goal ID

        Returns:
            List of subtask dicts
        """
        result = await self._request("GET", f"/api/goals/{goal_id}/subtasks")
        return result if isinstance(result, list) else None

    async def get_stats(self, date_filter: str = "today") -> Optional[Dict]:
        """Get event statistics.

        Args:
            date_filter: today|week|month

        Returns:
            Stats dict
        """
        return await self._request("GET", "/api/stats", params={"date": date_filter})

    async def llm_chat(self, text: str) -> Optional[Dict]:
        """Parse natural language to event data (no create).

        Args:
            text: User input text

        Returns:
            Parsed event data dict
        """
        return await self._request("POST", "/api/llm/chat", json_data={"text": text})

    async def llm_create(self, text: str) -> Optional[List[Dict]]:
        """Parse natural language and create event.

        Args:
            text: User input text

        Returns:
            List of created event dicts
        """
        result = await self._request(
            "POST", "/api/llm/create", json_data={"text": text}
        )
        return result if isinstance(result, list) else None

    async def llm_command(self, text: str, dry_run: bool = False) -> Optional[Dict]:
        """Execute unified natural language command.

        Args:
            text: User command text
            dry_run: If True, only return plan without executing

        Returns:
            Command result dict
        """
        return await self._request(
            "POST", "/api/llm/command", json_data={"text": text, "dry_run": dry_run}
        )

    async def llm_breakdown(
        self, text: str, horizon: str = "short", self_description: str = ""
    ) -> Optional[Dict]:
        """Break down task into subtasks.

        Args:
            text: Task description
            horizon: short|semester|long
            self_description: User self description for context

        Returns:
            Breakdown result dict with subtasks
        """
        return await self._request(
            "POST",
            "/api/llm/breakdown",
            json_data={
                "text": text,
                "horizon": horizon,
                "self_description": self_description,
            },
        )

    async def ai_discuss_goal(
        self,
        goal_content: str,
        user_input: str,
        conversation_history: List[Dict],
    ) -> Optional[Dict]:
        """AI conversational goal breakdown.

        Args:
            goal_content: Initial goal description
            user_input: User's latest input
            conversation_history: Previous conversation messages

        Returns:
            AI response dict
        """
        return await self._request(
            "POST",
            "/api/goals/ai/discuss",
            json_data={
                "goal_content": goal_content,
                "user_input": user_input,
                "conversation_history": conversation_history,
            },
        )

    async def get_settings(self) -> Optional[Dict[str, str]]:
        """Get all settings.

        Returns:
            Dict of setting key -> value
        """
        return await self._request("GET", "/api/settings")

    async def update_setting(self, key: str, value: str) -> bool:
        """Update a setting.

        Args:
            key: Setting key
            value: Setting value

        Returns:
            True if updated
        """
        result = await self._request(
            "PUT", f"/api/settings/{key}", json_data={"value": value}
        )
        return result is not None


_api_client: Optional[ApiClient] = None


def get_api_client(base_url: str = "http://localhost:8080") -> ApiClient:
    """Get or create global API client instance."""
    global _api_client
    if _api_client is None:
        _api_client = ApiClient(base_url)
    return _api_client


def init_api_client(base_url: str) -> ApiClient:
    """Initialize API client with specific base URL."""
    global _api_client
    _api_client = ApiClient(base_url)
    return _api_client
