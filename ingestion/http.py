import time

import requests

USER_AGENT = "job-comp-checker/0.1 (personal research tool; contact: akuma496@asu.edu)"

_last_request_at: dict[str, float] = {}
_MIN_DELAY_SECONDS = 1.0


def polite_get(url: str, **kwargs) -> requests.Response:
    """GET with a real User-Agent, a fixed delay per host, and one retry on 5xx."""
    host = requests.utils.urlparse(url).netloc
    elapsed = time.monotonic() - _last_request_at.get(host, 0.0)
    if elapsed < _MIN_DELAY_SECONDS:
        time.sleep(_MIN_DELAY_SECONDS - elapsed)

    headers = kwargs.pop("headers", {})
    headers.setdefault("User-Agent", USER_AGENT)

    response = requests.get(url, headers=headers, timeout=15, **kwargs)
    if response.status_code >= 500:
        time.sleep(_MIN_DELAY_SECONDS)
        response = requests.get(url, headers=headers, timeout=15, **kwargs)

    _last_request_at[host] = time.monotonic()
    return response
