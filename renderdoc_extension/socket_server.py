"""
TCP Socket Server for RenderDoc MCP Bridge
Runs in a separate thread within RenderDoc to handle MCP requests.
"""

import json
import socket
import struct
import threading
import traceback


class MCPBridgeServer:
    """Socket server for MCP bridge communication"""

    def __init__(self, host, port, handler):
        self.host = host
        self.port = port
        self.handler = handler
        self._socket = None
        self._thread = None
        self._running = False

    def start(self):
        """Start the server in a separate thread"""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the server"""
        self._running = False
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass

    def is_running(self):
        """Check if server is running"""
        return self._running

    def _run(self):
        """Main server loop"""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            self._socket.bind((self.host, self.port))
            self._socket.listen(1)
            self._socket.settimeout(1.0)

            print("[MCP Bridge] Server listening on %s:%d" % (self.host, self.port))

            while self._running:
                try:
                    client, addr = self._socket.accept()
                    print("[MCP Bridge] Client connected from %s" % str(addr))
                    client_thread = threading.Thread(
                        target=self._handle_client, args=(client,), daemon=True
                    )
                    client_thread.start()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self._running:
                        print("[MCP Bridge] Accept error: %s" % str(e))
        except Exception as e:
            print("[MCP Bridge] Server error: %s" % str(e))
        finally:
            if self._socket:
                self._socket.close()

    def _handle_client(self, client):
        """Handle client connection"""
        try:
            while self._running:
                # Read message length (4 bytes, big-endian)
                length_bytes = self._recv_exact(client, 4)
                if not length_bytes:
                    break

                msg_length = struct.unpack(">I", length_bytes)[0]

                # Read message body
                msg_bytes = self._recv_exact(client, msg_length)
                if not msg_bytes:
                    break

                # Parse and handle request
                try:
                    request = json.loads(msg_bytes.decode("utf-8"))
                    response = self.handler.handle(request)
                except Exception as e:
                    traceback.print_exc()
                    response = {
                        "id": request.get("id") if "request" in dir() else None,
                        "error": {"code": -32700, "message": "Parse error: %s" % str(e)},
                    }

                # Send response
                response_bytes = json.dumps(response).encode("utf-8")
                client.sendall(struct.pack(">I", len(response_bytes)))
                client.sendall(response_bytes)

        except Exception as e:
            print("[MCP Bridge] Client error: %s" % str(e))
        finally:
            try:
                client.close()
            except Exception:
                pass
            print("[MCP Bridge] Client disconnected")

    def _recv_exact(self, sock, n):
        """Receive exactly n bytes"""
        data = b""
        while len(data) < n:
            try:
                chunk = sock.recv(n - len(data))
                if not chunk:
                    return None
                data += chunk
            except socket.timeout:
                if not self._running:
                    return None
                continue
        return data
