"""Standalone HTTP Micro-Oracle Server implementing x402 on Base USDC."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from omni_earner.config import Settings, get_settings
from omni_earner.ledger import TreasuryLedger
from omni_earner.x402_oracle import X402OracleService


class X402RequestHandler(BaseHTTPRequestHandler):
    """Dispatches HTTP requests to the X402OracleService protocol engine."""

    oracle: X402OracleService

    def log_message(self, format: str, *args: object) -> None:
        """Silence standard request logging for clean terminal output."""
        return

    def do_GET(self) -> None:
        """Handle incoming GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        query_params = {
            k: v[0] for k, v in parse_qs(parsed.query).items() if v
        }

        # Health endpoint
        if path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            payload = {
                "status": "healthy",
                "network": "eip155:8453",
                "treasury_balance": self.oracle.ledger.get_balance(),
            }
            self.wfile.write(json.dumps(payload, indent=2).encode("utf-8"))
            return

        # Ledger summary endpoint
        if path == "/ledger":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            summary = self.oracle.ledger.summary_report()
            self.wfile.write(json.dumps(summary, indent=2).encode("utf-8"))
            return

        # Extract request headers
        headers = {k: v for k, v in self.headers.items()}

        # Route through x402 Oracle protocol engine
        status, resp_headers, body = self.oracle.handle_request(
            headers=headers, query_params=query_params
        )

        self.send_response(status)
        for k, v in resp_headers.items():
            self.send_header(k, v)
        self.end_headers()

        body_bytes = json.dumps(body, indent=2).encode("utf-8")
        self.wfile.write(body_bytes)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8402,
    ledger: Optional[TreasuryLedger] = None,
    settings: Optional[Settings] = None,
) -> ThreadingHTTPServer:
    """Create and return a configured ThreadingHTTPServer instance."""
    app_settings = settings or get_settings()
    app_ledger = ledger or TreasuryLedger(
        db_path=app_settings.DB_PATH,
        starting_balance=app_settings.STARTING_BALANCE_USD,
        max_cost_per_task=app_settings.MAX_COST_PER_TASK_USD,
        min_ev_multiplier=app_settings.MIN_EV_MULTIPLIER,
        target_margin=app_settings.TARGET_MARGIN,
        owner_sweep_ratio=app_settings.OWNER_SWEEP_RATIO,
    )

    oracle = X402OracleService(ledger=app_ledger, settings=app_settings)

    handler = type("ConfiguredX402Handler", (X402RequestHandler,), {"oracle": oracle})
    server = ThreadingHTTPServer((host, port), handler)
    return server


def run_server(
    host: str = "127.0.0.1",
    port: int = 8402,
    ledger: Optional[TreasuryLedger] = None,
    settings: Optional[Settings] = None,
) -> None:
    """Run the blocking HTTP x402 Micro-Oracle server."""
    server = create_server(host=host, port=port, ledger=ledger, settings=settings)
    print(f"[*] x402 Micro-Oracle server running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Server shutdown.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
