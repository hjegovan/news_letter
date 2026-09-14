from __future__ import annotations

import os


def get_webshare_proxy() -> dict[str, str] | None:
    username = os.getenv("WEBSHARE_PROXY_USERNAME")
    password = os.getenv("WEBSHARE_PROXY_PASSWORD")

    if not username or not password:
        return None

    proxy_url = (
        f"http://{username}:{password}"
        "@p.webshare.io:80"
    )

    return {
        "http": proxy_url,
        "https": proxy_url,
    }
