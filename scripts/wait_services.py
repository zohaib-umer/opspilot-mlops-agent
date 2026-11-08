import time

import httpx

for url in ["http://localhost:5000/health", "http://localhost:8080/auth/token"]:
    for attempt in range(120):
        try:
            result = httpx.get(url, timeout=3)
            if result.status_code < 500:
                break
        except httpx.HTTPError:
            pass
        time.sleep(5)
    else:
        raise RuntimeError(f"Service did not start: {url}")
print("MLflow and Airflow are reachable")
