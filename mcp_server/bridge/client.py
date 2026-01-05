"""
RenderDoc Bridge Client
Communicates with the RenderDoc extension's socket server.
"""

import json
import socket
import struct
import uuid
from typing import Any


class RenderDocBridgeError(Exception):
    """Error communicating with RenderDoc bridge"""

    pass


class RenderDocBridge:
    """Client for communicating with RenderDoc extension"""

    def __init__(self, host: str = "127.0.0.1", port: int = 19876):
        self.host = host
        self.port = port
        self._socket: socket.socket | None = None

    def _ensure_connected(self) -> None:
        """Ensure connection to RenderDoc extension"""
        if self._socket is None:
            try:
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._socket.connect((self.host, self.port))
                self._socket.settimeout(30.0)
            except ConnectionRefusedError:
                raise RenderDocBridgeError(
                    f"Cannot connect to RenderDoc MCP Bridge at {self.host}:{self.port}. "
                    "Make sure RenderDoc is running with the MCP Bridge extension loaded."
                )
            except Exception as e:
                raise RenderDocBridgeError(f"Connection failed: {e}")

    def _disconnect(self) -> None:
        """Disconnect from RenderDoc extension"""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Call a method on the RenderDoc extension"""
        self._ensure_connected()

        request = {
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params or {},
        }

        try:
            # Send request
            request_bytes = json.dumps(request).encode("utf-8")
            assert self._socket is not None
            self._socket.sendall(struct.pack(">I", len(request_bytes)))
            self._socket.sendall(request_bytes)

            # Receive response
            length_bytes = self._recv_exact(4)
            msg_length = struct.unpack(">I", length_bytes)[0]
            response_bytes = self._recv_exact(msg_length)

            response = json.loads(response_bytes.decode("utf-8"))

            if "error" in response:
                error = response["error"]
                raise RenderDocBridgeError(f"[{error['code']}] {error['message']}")

            return response.get("result")

        except RenderDocBridgeError:
            raise
        except socket.timeout:
            self._disconnect()
            raise RenderDocBridgeError("Request timed out")
        except Exception as e:
            self._disconnect()
            raise RenderDocBridgeError(f"Communication error: {e}")

    def _recv_exact(self, n: int) -> bytes:
        """Receive exactly n bytes"""
        assert self._socket is not None
        data = b""
        while len(data) < n:
            chunk = self._socket.recv(n - len(data))
            if not chunk:
                raise RenderDocBridgeError("Connection closed by server")
            data += chunk
        return data
