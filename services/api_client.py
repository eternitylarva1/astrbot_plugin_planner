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
                    content_type = resp.headers.get("Content-Type", "")
                    try:
                        data = await resp.json()
                    except Exception:
                        # 响应不是 JSON（如 500 HTML 错误页），读文本
                        text = await resp.text()
                        logger.error(f"API {method} {url} returned non-JSON {resp.status}: {text[:200]}")
                        return None
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

    # ==================== Events History and Recovery ====================

    async def get_deleted_events(self) -> Optional[List[Dict]]:
        """Get list of deleted events that can be restored."""
        result = await self._request("GET", "/api/deleted-events")
        return result if isinstance(result, list) else None

    async def restore_deleted_event(self, event_id: int) -> Optional[Dict]:
        """Restore a deleted event."""
        return await self._request("POST", f"/api/deleted-events/{event_id}/restore")

    async def permanent_delete_event(self, event_id: int) -> bool:
        """Permanently delete an event from backup."""
        result = await self._request("DELETE", f"/api/deleted-events/{event_id}")
        return result is not None

    async def get_event_history(self) -> Optional[List[Dict]]:
        """Get all event history."""
        result = await self._request("GET", "/api/event-history")
        return result if isinstance(result, list) else None

    async def get_event_modifications(self) -> Optional[List[Dict]]:
        """Get event modification history for undo."""
        result = await self._request("GET", "/api/event-modifications")
        return result if isinstance(result, list) else None

    async def undo_event_modification(self, modification_id: int) -> Optional[Dict]:
        """Restore event to previous state."""
        return await self._request("POST", f"/api/event-modifications/{modification_id}/undo")

    # ==================== Goals Extended ====================

    async def get_goal_conversations(self, goal_id: int) -> Optional[List[Dict]]:
        """Get conversation history for a goal."""
        result = await self._request("GET", f"/api/goals/{goal_id}/conversations")
        return result if isinstance(result, list) else None

    async def add_goal_conversation(self, goal_id: int, role: str, content: str) -> Optional[Dict]:
        """Add a conversation message to a goal."""
        return await self._request(
            "POST", f"/api/goals/{goal_id}/conversations",
            json_data={"role": role, "content": content}
        )

    async def get_goal_deliverables(self, goal_id: int) -> Optional[List[Dict]]:
        """Get deliverables for a goal."""
        result = await self._request("GET", f"/api/goals/{goal_id}/deliverables")
        return result if isinstance(result, list) else None

    async def create_goal_deliverable(self, goal_id: int, deliverable_data: Dict) -> Optional[Dict]:
        """Create a deliverable for a goal."""
        return await self._request(
            "POST", f"/api/goals/{goal_id}/deliverables",
            json_data=deliverable_data
        )

    async def update_goal_deliverable(self, deliverable_id: int, data: Dict) -> Optional[Dict]:
        """Update a goal deliverable."""
        return await self._request(
            "PUT", f"/api/goals/deliverables/{deliverable_id}",
            json_data=data
        )

    async def delete_goal_deliverable(self, deliverable_id: int) -> bool:
        """Delete a goal deliverable."""
        result = await self._request("DELETE", f"/api/goals/deliverables/{deliverable_id}")
        return result is not None

    async def ai_reschedule(self, goal_content: str) -> Optional[Dict]:
        """AI global rescheduling."""
        return await self._request(
            "POST", "/api/goals/ai/reschedule",
            json_data={"goal_content": goal_content}
        )

    # ==================== AI Providers ====================

    async def get_ai_providers(self) -> Optional[List[Dict]]:
        """Get all AI provider configurations."""
        result = await self._request("GET", "/api/ai-providers")
        return result if isinstance(result, list) else None

    async def create_ai_provider(self, provider_data: Dict) -> Optional[Dict]:
        """Create a new AI provider configuration."""
        return await self._request("POST", "/api/ai-providers", json_data=provider_data)

    async def update_ai_provider(self, provider_id: int, data: Dict) -> Optional[Dict]:
        """Update an AI provider configuration."""
        return await self._request("PUT", f"/api/ai-providers/{provider_id}", json_data=data)

    async def delete_ai_provider(self, provider_id: int) -> bool:
        """Delete an AI provider configuration."""
        result = await self._request("DELETE", f"/api/ai-providers/{provider_id}")
        return result is not None

    async def activate_ai_provider(self, provider_id: int) -> Optional[Dict]:
        """Activate an AI provider configuration."""
        return await self._request("PUT", f"/api/ai-providers/{provider_id}/activate")

    # ==================== Expenses ====================

    async def get_expenses(self, date_filter: str = "month") -> Optional[List[Dict]]:
        """Get expenses by date filter."""
        result = await self._request("GET", "/api/expenses", params={"date": date_filter})
        return result if isinstance(result, list) else None

    async def create_expense(self, expense_data: Dict) -> Optional[Dict]:
        """Create an expense record."""
        return await self._request("POST", "/api/expenses", json_data=expense_data)

    async def update_expense(self, expense_id: int, expense_data: Dict) -> Optional[Dict]:
        """Update an expense record."""
        return await self._request("PUT", f"/api/expenses/{expense_id}", json_data=expense_data)

    async def delete_expense(self, expense_id: int) -> bool:
        """Delete an expense (soft delete)."""
        result = await self._request("DELETE", f"/api/expenses/{expense_id}")
        return result is not None

    async def get_expense_stats(self, date_filter: str = "month") -> Optional[Dict]:
        """Get expense statistics."""
        return await self._request("GET", "/api/expenses/stats", params={"date": date_filter})

    async def get_expense_categories(self) -> Optional[List[Dict]]:
        """Get expense categories."""
        result = await self._request("GET", "/api/expenses/categories")
        return result if isinstance(result, list) else None

    async def create_expense_category(self, category_data: Dict) -> Optional[Dict]:
        """Create an expense category."""
        return await self._request("POST", "/api/expenses/categories", json_data=category_data)

    # ==================== Budgets ====================

    async def get_budgets(self) -> Optional[List[Dict]]:
        """Get all budgets with spent/remaining stats."""
        result = await self._request("GET", "/api/budgets")
        return result if isinstance(result, list) else None

    async def create_budget(self, budget_data: Dict) -> Optional[Dict]:
        """Create a new budget."""
        return await self._request("POST", "/api/budgets", json_data=budget_data)

    async def get_budget(self, budget_id: int) -> Optional[Dict]:
        """Get a single budget with stats."""
        return await self._request("GET", f"/api/budgets/{budget_id}")

    async def update_budget(self, budget_id: int, budget_data: Dict) -> Optional[Dict]:
        """Update a budget."""
        return await self._request("PUT", f"/api/budgets/{budget_id}", json_data=budget_data)

    async def delete_budget(self, budget_id: int) -> bool:
        """Delete a budget."""
        result = await self._request("DELETE", f"/api/budgets/{budget_id}")
        return result is not None

    async def get_budget_expenses(self, budget_id: int) -> Optional[List[Dict]]:
        """Get expenses for a specific budget."""
        result = await self._request("GET", f"/api/budgets/{budget_id}/expenses")
        return result if isinstance(result, list) else None

    async def get_budget_templates(self) -> Optional[List[Dict]]:
        """Get budget templates."""
        result = await self._request("GET", "/api/budget-templates")
        return result if isinstance(result, list) else None

    async def create_budget_template(self, template_data: Dict) -> Optional[Dict]:
        """Create a budget template."""
        return await self._request("POST", "/api/budget-templates", json_data=template_data)

    # ==================== Notes ====================

    async def get_notes(self) -> Optional[List[Dict]]:
        """Get all notes."""
        result = await self._request("GET", "/api/notes")
        return result if isinstance(result, list) else None

    async def create_note(self, note_data: Dict) -> Optional[Dict]:
        """Create a new note."""
        return await self._request("POST", "/api/notes", json_data=note_data)

    async def get_note(self, note_id: int) -> Optional[Dict]:
        """Get a single note."""
        return await self._request("GET", f"/api/notes/{note_id}")

    async def update_note(self, note_id: int, note_data: Dict) -> Optional[Dict]:
        """Update a note."""
        return await self._request("PUT", f"/api/notes/{note_id}", json_data=note_data)

    async def delete_note(self, note_id: int) -> bool:
        """Delete a note."""
        result = await self._request("DELETE", f"/api/notes/{note_id}")
        return result is not None

    async def get_note_conversations(self, note_id: int) -> Optional[List[Dict]]:
        """Get conversation history for a note."""
        result = await self._request("GET", f"/api/notes/{note_id}/conversations")
        return result if isinstance(result, list) else None

    async def chat_note(self, note_id: int, user_input: str) -> Optional[Dict]:
        """Chat with AI about a note."""
        return await self._request(
            "POST", f"/api/notes/{note_id}/chat",
            json_data={"user_input": user_input}
        )

    async def delete_note_conversations(self, note_id: int) -> bool:
        """Clear conversation history for a note."""
        result = await self._request("DELETE", f"/api/notes/{note_id}/conversations")
        return result is not None

    # ==================== Note Groups ====================

    async def get_note_groups(self) -> Optional[List[Dict]]:
        """Get note groups."""
        result = await self._request("GET", "/api/note-groups")
        return result if isinstance(result, list) else None

    async def create_note_group(self, group_data: Dict) -> Optional[Dict]:
        """Create a note group."""
        return await self._request("POST", "/api/note-groups", json_data=group_data)

    async def update_note_group(self, group_id: int, group_data: Dict) -> Optional[Dict]:
        """Update a note group."""
        return await self._request("PUT", f"/api/note-groups/{group_id}", json_data=group_data)

    async def delete_note_group(self, group_id: int) -> bool:
        """Delete a note group."""
        result = await self._request("DELETE", f"/api/note-groups/{group_id}")
        return result is not None

    # ==================== User Contexts ====================

    async def get_user_contexts(self) -> Optional[List[Dict]]:
        """Get all user contexts."""
        result = await self._request("GET", "/api/user-contexts")
        return result if isinstance(result, list) else None

    async def create_user_context(self, context_data: Dict) -> Optional[Dict]:
        """Create a user context."""
        return await self._request("POST", "/api/user-contexts", json_data=context_data)

    async def update_user_context(self, context_id: int, context_data: Dict) -> Optional[Dict]:
        """Update a user context."""
        return await self._request("PUT", f"/api/user-contexts/{context_id}", json_data=context_data)

    async def delete_user_context(self, context_id: int) -> bool:
        """Delete a user context."""
        result = await self._request("DELETE", f"/api/user-contexts/{context_id}")
        return result is not None

    async def reorder_user_contexts(self, context_ids: List[int]) -> bool:
        """Reorder user contexts."""
        result = await self._request("PUT", "/api/user-contexts/reorder", json_data={"context_ids": context_ids})
        return result is not None

    # ==================== Settings Extended ====================

    async def cleanup_test_entries(self) -> bool:
        """Cleanup test entries."""
        result = await self._request("POST", "/api/settings/cleanup_test_entries")
        return result is not None

    # ==================== LLM Extended ====================

    async def llm_parse_expense(self, text: str) -> Optional[Dict]:
        """Parse natural language expense record."""
        return await self._request("POST", "/api/llm/parse_expense", json_data={"text": text})

    async def llm_agent_command(self, text: str) -> Optional[Dict]:
        """Execute multi-round agent command (query → operate).

        Allows LLM to first query events/expenses then perform operations
        in a single call. Supports complex tasks like "把今天没完成的推到明天".

        Args:
            text: User command text

        Returns:
            Command result dict with operations performed
        """
        return await self._request("POST", "/api/llm/agent-command", json_data={"text": text})

    async def search(self, query: str) -> Optional[Dict]:
        """Global search across events, notes, and goals.

        Args:
            query: Search keyword

        Returns:
            Dict with events, notes, goals arrays
        """
        return await self._request("GET", "/api/search", params={"q": query})


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
