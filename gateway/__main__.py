import os

import uvicorn

from .app import create_app

uvicorn.run(
    create_app(),
    host=os.environ.get("GATEWAY_HOST", "127.0.0.1"),
    port=int(os.environ.get("GATEWAY_PORT", "8080")),
    access_log=False,
    proxy_headers=True,
    forwarded_allow_ips=os.environ.get("GATEWAY_TRUSTED_PROXIES", "127.0.0.1"),
)
