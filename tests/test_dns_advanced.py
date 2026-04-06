"""Tests for advanced DNS features -- cluster nodes, cluster sync, Cloudflare, DNSSEC."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import auth_header


# --------------------------------------------------------------------------
# POST /cluster/nodes -- add cluster node
# --------------------------------------------------------------------------


class TestDnsClusterAddNode:
    async def test_cluster_add_node(self, client, admin_user, admin_token, db_session):
        """Admin should be able to add a DNS cluster node."""
        resp = await client.post(
            "/api/v1/dns/cluster/nodes",
            json={
                "hostname": "ns2.example.com",
                "ip_address": "10.0.0.2",
                "port": 53,
                "api_url": "https://ns2.example.com:8443/api/v1",
                "api_key": "secret-cluster-key-123",
                "role": "slave",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["hostname"] == "ns2.example.com"
        assert body["ip_address"] == "10.0.0.2"
        assert body["role"] == "slave"
        assert body["is_active"] is True
        assert "id" in body

    async def test_cluster_add_node_duplicate_rejected(
        self, client, admin_user, admin_token, db_session
    ):
        """Adding a node with a duplicate hostname should return 409."""
        node_data = {
            "hostname": "ns3-dup.example.com",
            "ip_address": "10.0.0.3",
            "port": 53,
            "api_url": "https://ns3.example.com:8443/api/v1",
            "api_key": "secret-key-456",
            "role": "slave",
        }
        resp1 = await client.post(
            "/api/v1/dns/cluster/nodes",
            json=node_data,
            headers=auth_header(admin_token),
        )
        assert resp1.status_code == 201

        resp2 = await client.post(
            "/api/v1/dns/cluster/nodes",
            json=node_data,
            headers=auth_header(admin_token),
        )
        assert resp2.status_code == 409

    async def test_cluster_add_node_requires_admin(
        self, client, regular_user, user_token
    ):
        """Non-admin users should be rejected."""
        resp = await client.post(
            "/api/v1/dns/cluster/nodes",
            json={
                "hostname": "ns99.example.com",
                "ip_address": "10.0.0.99",
                "port": 53,
                "api_url": "https://ns99.example.com:8443/api/v1",
                "api_key": "key-789",
                "role": "slave",
            },
            headers=auth_header(user_token),
        )
        assert resp.status_code == 403


# --------------------------------------------------------------------------
# POST /cluster/sync -- trigger cluster sync
# --------------------------------------------------------------------------


class TestDnsClusterSync:
    async def test_cluster_sync(self, client, admin_user, admin_token, db_session):
        """Triggering a cluster sync should sync all active zones to slave nodes."""
        with patch(
            "api.routers.dns.push_zone_to_all_nodes",
            new_callable=AsyncMock,
            return_value=[{"node": "ns2.example.com", "success": True}],
        ):
            resp = await client.post(
                "/api/v1/dns/cluster/sync",
                headers=auth_header(admin_token),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "zones_synced" in body
        assert "results" in body
        assert isinstance(body["results"], list)

    async def test_cluster_sync_requires_admin(self, client, regular_user, user_token):
        """Non-admin users should be rejected."""
        resp = await client.post(
            "/api/v1/dns/cluster/sync",
            headers=auth_header(user_token),
        )
        assert resp.status_code == 403


# --------------------------------------------------------------------------
# POST /zones/{zone_id}/cloudflare/enable
# --------------------------------------------------------------------------


class TestCloudflareEnable:
    async def test_cloudflare_enable(self, client, admin_user, admin_token, db_session):
        """Enabling Cloudflare for a zone should store encrypted credentials."""
        from api.models.dns_zones import DnsZone

        # Create a zone first
        zone = DnsZone(
            user_id=admin_user.id,
            zone_name="cf-test.example.com",
        )
        db_session.add(zone)
        await db_session.flush()
        await db_session.refresh(zone)

        resp = await client.post(
            f"/api/v1/dns/zones/{zone.id}/cloudflare/enable",
            json={
                "api_key": "cf-api-key-abc123",
                "email": "admin@example.com",
                "cf_zone_id": "cf-zone-id-xyz",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["cloudflare_enabled"] is True

        # Verify status shows enabled
        status_resp = await client.get(
            f"/api/v1/dns/zones/{zone.id}/cloudflare/status",
            headers=auth_header(admin_token),
        )
        assert status_resp.status_code == 200
        status_body = status_resp.json()
        assert status_body["enabled"] is True
        assert status_body["cf_zone_id"] == "cf-zone-id-xyz"
        assert status_body["email"] == "admin@example.com"

    async def test_cloudflare_enable_zone_not_found(self, client, admin_user, admin_token):
        """Enabling CF on a nonexistent zone should return 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.post(
            f"/api/v1/dns/zones/{fake_id}/cloudflare/enable",
            json={
                "api_key": "key",
                "email": "a@b.com",
                "cf_zone_id": "zid",
            },
            headers=auth_header(admin_token),
        )
        assert resp.status_code == 404


# --------------------------------------------------------------------------
# DNSSEC enable (model-level test since no dedicated endpoint yet)
# --------------------------------------------------------------------------


class TestDnssecEnable:
    async def test_dnssec_enable(self, client, admin_user, admin_token, db_session):
        """DNSSEC fields on a zone should be settable and readable via the zone detail endpoint."""
        from api.models.dns_zones import DnsZone

        zone = DnsZone(
            user_id=admin_user.id,
            zone_name="dnssec-test.example.com",
            dnssec_enabled=True,
            dnssec_algorithm="ECDSAP256SHA256",
            ds_record="12345 13 2 AABBCCDD...",
        )
        db_session.add(zone)
        await db_session.flush()
        await db_session.refresh(zone)

        # Read the zone back via the API
        with patch("api.routers.dns._sync_zone_to_bind", new_callable=AsyncMock, return_value=None):
            resp = await client.get(
                f"/api/v1/dns/zones/{zone.id}",
                headers=auth_header(admin_token),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["dnssec_enabled"] is True
        assert body["dnssec_algorithm"] == "ECDSAP256SHA256"
        assert body["ds_record"] == "12345 13 2 AABBCCDD..."

    async def test_dnssec_defaults_to_disabled(self, client, admin_user, admin_token, db_session):
        """New zones should have DNSSEC disabled by default."""
        from api.models.dns_zones import DnsZone

        zone = DnsZone(
            user_id=admin_user.id,
            zone_name="no-dnssec.example.com",
        )
        db_session.add(zone)
        await db_session.flush()
        await db_session.refresh(zone)

        with patch("api.routers.dns._sync_zone_to_bind", new_callable=AsyncMock, return_value=None):
            resp = await client.get(
                f"/api/v1/dns/zones/{zone.id}",
                headers=auth_header(admin_token),
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["dnssec_enabled"] is False
