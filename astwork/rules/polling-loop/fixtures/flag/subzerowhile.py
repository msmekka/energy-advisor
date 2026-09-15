
import time
import requests

def wait_for_job_completion(job_id, api_url, timeout=300):
    elapsed = 0
    status = "pending"
    while status == "pending":
        response = requests.get(f"{api_url}/jobs/{job_id}/status")
        status = response.json().get("status", "pending")
        time.sleep(0.1)
        elapsed += 0.1
        if elapsed > timeout:
            raise TimeoutError(f"Job {job_id} did not complete within {timeout}s")
    return status