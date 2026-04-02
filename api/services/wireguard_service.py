"""WireGuard VPN peer management service.

All wg commands are executed via subprocess with explicit argument lists
(no shell=True) to avoid injection risks.
"""

from __future__ import annotations

import base64
import io
import logging
import re
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("hosthive.wireguard")

_WG_CONF_PATH = Path("/etc/wireguard/wg0.conf")


@dataclass
class WireguardPeer:
    """Representation of a single WireGuard peer."""

    name: str
    public_key: str
    allowed_ips: str
    private_key: str = ""
    preshared_key: str = ""
    endpoint: str = ""


class WireguardService:
    """Manage WireGuard peers via config-file editing and wg utilities."""

    def __init__(
        self,
        endpoint: str,
        listen_port: int = 51820,
        address_range: str = "10.0.0.0/24",
        conf_path: Optional[Path] = None,
    ) -> None:
        self._endpoint = endpoint
        self._listen_port = listen_port
        self._address_range = address_range
        self._conf_path = conf_path or _WG_CONF_PATH

    # ------------------------------------------------------------------
    # Key generation
    # ------------------------------------------------------------------

    @staticmethod
    def generate_keypair() -> Dict[str, str]:
        """Generate a WireGuard private/public key pair.

        Returns dict with ``private_key`` and ``public_key``.
        """
        result = subprocess.run(
            ["wg", "genkey"],
            capture_output=True,
            text=True,
            check=True,
        )
        private_key = result.stdout.strip()

        result = subprocess.run(
            ["wg", "pubkey"],
            input=private_key,
            capture_output=True,
            text=True,
            check=True,
        )
        public_key = result.stdout.strip()

        return {"private_key": private_key, "public_key": public_key}

    # ------------------------------------------------------------------
    # Peer management
    # ------------------------------------------------------------------

    def create_peer(self, name: str, allowed_ips: str) -> WireguardPeer:
        """Generate keys, add the peer to wg0.conf, and reload the interface."""
        keys = self.generate_keypair()
        peer = WireguardPeer(
            name=name,
            public_key=keys["public_key"],
            private_key=keys["private_key"],
            allowed_ips=allowed_ips,
        )

        # Append [Peer] block to the config file
        block = textwrap.dedent(f"""\

            # Peer: {name}
            [Peer]
            PublicKey = {peer.public_key}
            AllowedIPs = {allowed_ips}
        """)

        with open(self._conf_path, "a") as f:
            f.write(block)

        self._reload_interface()
        logger.info("Created WireGuard peer %s (%s)", name, peer.public_key[:8])
        return peer

    def delete_peer(self, public_key: str) -> bool:
        """Remove a peer from wg0.conf by public key and reload."""
        if not self._conf_path.exists():
            return False

        content = self._conf_path.read_text()
        # Match the [Peer] block containing the given PublicKey
        pattern = re.compile(
            r"(# Peer:.*\n)?\[Peer\]\n"
            r"PublicKey\s*=\s*" + re.escape(public_key) + r"\n"
            r"(?:.*\n)*?(?=\[|\Z)",
            re.MULTILINE,
        )
        new_content, count = pattern.subn("", content)
        if count == 0:
            logger.warning("Peer with key %s not found in config", public_key[:8])
            return False

        self._conf_path.write_text(new_content)
        self._reload_interface()
        logger.info("Deleted WireGuard peer %s", public_key[:8])
        return True

    def list_peers(self) -> List[Dict[str, Any]]:
        """Parse ``wg show wg0`` output and return peer information."""
        try:
            result = subprocess.run(
                ["wg", "show", "wg0", "dump"],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            logger.warning("Failed to run wg show — interface may not be up")
            return []

        peers: List[Dict[str, Any]] = []
        lines = result.stdout.strip().splitlines()
        # First line is the interface itself; skip it
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) >= 4:
                peers.append({
                    "public_key": parts[0],
                    "endpoint": parts[2] if parts[2] != "(none)" else None,
                    "allowed_ips": parts[3],
                    "latest_handshake": parts[4] if len(parts) > 4 else None,
                    "transfer_rx": parts[5] if len(parts) > 5 else None,
                    "transfer_tx": parts[6] if len(parts) > 6 else None,
                })

        return peers

    def generate_client_config(self, peer: WireguardPeer) -> str:
        """Generate a WireGuard client configuration string."""
        # Read the server public key from the running interface
        server_pubkey = self._get_server_public_key()

        return textwrap.dedent(f"""\
            [Interface]
            PrivateKey = {peer.private_key}
            Address = {peer.allowed_ips}
            DNS = 1.1.1.1, 1.0.0.1

            [Peer]
            PublicKey = {server_pubkey}
            Endpoint = {self._endpoint}:{self._listen_port}
            AllowedIPs = 0.0.0.0/0, ::/0
            PersistentKeepalive = 25
        """)

    @staticmethod
    def generate_qr_code(config: str) -> str:
        """Generate a QR code PNG for *config* and return it as base64.

        Uses the ``qrcode`` library if available; otherwise falls back to
        a minimal manual generation using ``subprocess`` and the ``qrencode``
        CLI tool.
        """
        try:
            import qrcode  # type: ignore[import-untyped]
            from qrcode.image.pil import PilImage  # type: ignore[import-untyped]

            qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M)
            qr.add_data(config)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("ascii")
        except ImportError:
            pass

        # Fallback: try the qrencode CLI tool
        try:
            result = subprocess.run(
                ["qrencode", "-t", "PNG", "-o", "-"],
                input=config.encode("utf-8"),
                capture_output=True,
                check=True,
            )
            return base64.b64encode(result.stdout).decode("ascii")
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            logger.error("QR code generation failed: %s", exc)
            raise RuntimeError(
                "Neither the 'qrcode' Python package nor the 'qrencode' "
                "CLI tool is available."
            ) from exc

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reload_interface(self) -> None:
        """Reload the WireGuard interface to apply config changes."""
        subprocess.run(
            ["wg", "syncconf", "wg0", str(self._conf_path)],
            check=True,
            capture_output=True,
        )
        logger.debug("Reloaded WireGuard interface wg0")

    def _get_server_public_key(self) -> str:
        """Extract the server public key from the running interface."""
        try:
            result = subprocess.run(
                ["wg", "show", "wg0", "public-key"],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            logger.warning("Could not read server public key from wg0")
            return "<SERVER_PUBLIC_KEY>"
