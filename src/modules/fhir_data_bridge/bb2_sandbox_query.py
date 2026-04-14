from __future__ import annotations

import requests
from dataclasses import dataclass


@dataclass
class BlueButton2SandboxClient:
    base_url: str = "https://sandbox.bluebutton.cms.gov/v1/fhir"
    access_token: str | None = None

    def _headers(self) -> dict[str, str]:
        if not self.access_token:
            raise ValueError("Access token is required for Blue Button 2.0 sandbox queries")
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/fhir+json",
        }

    def fetch_explanation_of_benefit(self, beneficiary_id: str, count: int = 10) -> dict[str, object]:
        url = f"{self.base_url}/ExplanationOfBenefit"
        params = {"patient": beneficiary_id, "_count": count}
        response = requests.get(url, headers=self._headers(), params=params, timeout=30)
        response.raise_for_status()
        return response.json()
