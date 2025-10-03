from __future__ import annotations
import time
import random
import requests
from typing import Optional
from . import config

_session = requests.Session()
_session.headers.update({"User-Agent": config.USER_AGENT})

def get(url: str, timeout: int = None) -> requests.Response:
    timeout = timeout or config.REQUEST_TIMEOUT_SEC
    last_exc: Optional[Exception] = None
    for attempt in range(1, config.REQUEST_RETRY + 1):
        try:
            resp = _session.get(url, timeout=timeout)
            return resp
        except Exception as exc:
            last_exc = exc
            # backoff a touch
            time.sleep(config.REQUEST_SLEEP_BETWEEN_SEC + random.random())
    if last_exc:
        raise last_exc

def polite_sleep():
    time.sleep(config.REQUEST_SLEEP_BETWEEN_SEC + random.random() * 0.7)

def heat_details_url(heat_no: int) -> str:
    # e.g., https://.../sp_center/HeatDetails.aspx?HeatNo=82271
    return f"{config.SITE_BASE_URL}{config.HEAT_DETAILS_PATH}?HeatNo={heat_no}"
