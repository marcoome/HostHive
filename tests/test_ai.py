"""Tests for the AI router -- /api/v1/ai."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tests.conftest import auth_header

from api.models.ai import AiSettings


# --------------------------------------------------------------------------
# POST /chat -- AI chat endpoint (mocked AI client)
# --------------------------------------------------------------------------


class TestAiChatEndpoint:
    async def test_ai_chat_endpoint(
        self, client, regular_user, user_token, db_session
    ):
        """Mock the AI client so the chat endpoint returns a response."""
        # Seed AI settings so the endpoint considers AI enabled
        ai_settings = AiSettings(
            provider="openai",
            model="gpt-4o",
            api_key_encrypted="fake-encrypted-key",
            is_enabled=True,
        )
        db_session.add(ai_settings)
        await db_session.commit()

        mock_ai_client = AsyncMock()
        mock_ai_client.chat.return_value = "Hello! How can I help you?"
        mock_ai_client.provider = "openai"
        mock_ai_client.model = "gpt-4o"
        mock_ai_client.estimate_cost.return_value = 0.001

        with patch(
            "api.routers.ai.get_ai_client_from_settings",
            return_value=mock_ai_client,
        ):
            resp = await client.post(
                "/api/v1/ai/chat",
                json={"message": "How do I add a domain?", "context": {}},
                headers=auth_header(user_token),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "response" in body
        assert body["response"] == "Hello! How can I help you?"
        assert "conversation_id" in body


# --------------------------------------------------------------------------
# GET /settings -- AI settings (admin only)
# --------------------------------------------------------------------------


class TestAiSettingsAdminOnly:
    async def test_ai_settings_admin_only(
        self, client, admin_user, admin_token
    ):
        resp = await client.get(
            "/api/v1/ai/settings",
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "provider" in body
        assert "is_enabled" in body

    async def test_ai_settings_non_admin_gets_403(
        self, client, regular_user, user_token
    ):
        resp = await client.get(
            "/api/v1/ai/settings",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 403


# --------------------------------------------------------------------------
# AI disabled returns feature disabled
# --------------------------------------------------------------------------


class TestAiDisabledReturnsFeatureDisabled:
    async def test_ai_disabled_returns_feature_disabled(
        self, client, regular_user, user_token
    ):
        """When no AI settings exist, chat should return 503 (service unavailable)."""
        resp = await client.post(
            "/api/v1/ai/chat",
            json={"message": "Hello", "context": {}},
            headers=auth_header(user_token),
        )
        assert resp.status_code == 503
        assert "not enabled" in resp.json()["detail"].lower() or "configure" in resp.json()["detail"].lower()


# --------------------------------------------------------------------------
# GET /conversations -- list conversations
# --------------------------------------------------------------------------


class TestAiConversationsList:
    async def test_ai_conversations_list(
        self, client, regular_user, user_token
    ):
        resp = await client.get(
            "/api/v1/ai/conversations",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert isinstance(body["items"], list)
