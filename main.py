"""Compatibility entry point. Application code lives in app/server.py."""
from app.server import MiyoraHandler, main

if __name__ == "__main__":
    raise SystemExit(main())
