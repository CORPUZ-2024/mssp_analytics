from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pdfplumber
import pandas as pd

from src.modules.pa_metrics_simulation.pa_metrics_schema import PriorAuthMetricRecord

logger = logging.getLogger(__name__)

class DisclosureIngestor:
    """Ingest and pre-process payer PA disclosure PDFs."""

    def __init__(self):
        self.records = []

    def ingest_directory(self, dir_path: str | Path) -> pd.DataFrame:
        """Ingest all PDF disclosures in a directory."""
        dir_path = Path(dir_path)
        for pdf_file in dir_path.glob("*.pdf"):
            try:
                self.ingest_file(pdf_file)
            except Exception as e:
                logger.error(f"Failed to ingest {pdf_file}: {e}")
        
        return self.to_dataframe()

    def ingest_file(self, file_path: Path):
        """Ingest a single PDF disclosure."""
        logger.info(f"Ingesting {file_path.name}...")
        text = ""
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                text += page.extract_text() + "\n"
        
        payer_name = self._detect_payer(file_path.name, text)
        year = self._detect_year(text)
        
        # Extract metrics
        metrics = self._extract_metrics(text)
        
        if metrics:
            # We don't have county/state at the plan level, so we use placeholders or 'ALL'
            record = PriorAuthMetricRecord(
                county_id="PLAN_LEVEL",
                state_id="CA",  # Most of these seem to be CA based on the text
                enrollment_type=payer_name,
                year=year,
                total_requests=metrics['total_standard'],
                approved_requests=metrics['approved_standard'],
                denied_requests=metrics['denied_standard'],
                appeals_overturned=metrics['appeals_overturned_total'],
                expedited_requests=metrics['total_expedited'],
                expedited_approved=metrics['approved_expedited'],
                expedited_denied=metrics['denied_expedited']
            )
            self.records.append(record)

    def _detect_payer(self, filename: str, text: str) -> str:
        if "blue_shield" in filename.lower() or "Blue Shield" in text:
            return "Blue Shield"
        if "healthnet" in filename.lower() or "Health Net" in text:
            if "Wellcare" in text or "wellcare" in filename.lower():
                return "Wellcare (Health Net)"
            return "Health Net"
        if "sfph" in filename.lower() or "San Francisco Health Plan" in text or "SFHP" in text:
            return "SFHP"
        return "Unknown Payer"

    def _detect_year(self, text: str) -> str:
        match = re.search(r"(?:Calendar Year|for|Summary for|metrics \(|Period:) (\d{4})", text)
        if match:
            return match.group(1)
        return "2025"  # Default based on what I saw

    def _extract_metrics(self, text: str) -> dict[str, int]:
        metrics = {
            'total_standard': 0,
            'approved_standard': 0,
            'denied_standard': 0,
            'total_expedited': 0,
            'approved_expedited': 0,
            'denied_expedited': 0,
            'appeals_overturned_total': 0
        }
        
        # Find all headers and their positions
        urgent_headers = list(re.finditer(r"(?:Urgent|Expedited)(?:\s+prior)?\s+authorization\s+requests", text, re.I)) or \
                         list(re.finditer(r"Urgent Requests", text, re.I))
        standard_headers = list(re.finditer(r"(?:Non[ -]urgent|Standard)(?:\s+prior)?\s+authorization\s+requests", text, re.I)) or \
                           list(re.finditer(r"Standard Requests", text, re.I))
        
        # Add Health Net style
        if not urgent_headers:
            urgent_headers = list(re.finditer(r"Expedited Prior Authorizations:", text, re.I))
        if not standard_headers:
            standard_headers = list(re.finditer(r"Standard Prior Authorizations:", text, re.I))
        
        all_headers = sorted(
            [(h.start(), 'urgent') for h in urgent_headers] + 
            [(h.start(), 'standard') for h in standard_headers]
        )
        
        urgent_section = ""
        standard_section = ""
        
        for i, (pos, h_type) in enumerate(all_headers):
            end_pos = all_headers[i+1][0] if i+1 < len(all_headers) else len(text)
            section_text = text[pos:end_pos]
            if h_type == 'urgent':
                urgent_section += section_text + "\n"
            else:
                standard_section += section_text + "\n"

        # If sections couldn't be isolated well, use the whole text
        if not urgent_section: urgent_section = text
        if not standard_section: standard_section = text

        # Improved Patterns for standard/non-urgent
        std_total_match = re.search(r"Total requests\s+([\d,]+)", standard_section, re.I) or \
                          re.search(r"Standard Requests\s+([\d,]+)", standard_section, re.I)
        
        if std_total_match:
            metrics['total_standard'] = int(std_total_match.group(1).replace(",", ""))

        std_app_match = re.search(r"Total approved\s+([\d,]+)", standard_section, re.I) or \
                        re.search(r"Requests Approved\s+([\d,]+)", standard_section, re.I) or \
                        re.search(r"•\s+([\d,]+)\s+requests.*?\)\s+were approved", standard_section, re.I)
        
        if std_app_match:
            metrics['approved_standard'] = int(std_app_match.group(1).replace(",", ""))

        std_den_match = re.search(r"Total denied\s+([\d,]+)", standard_section, re.I) or \
                        re.search(r"Requests Denied\s+([\d,]+)", standard_section, re.I) or \
                        re.search(r"•\s+([\d,]+)\s+requests.*?\)\s+were denied", standard_section, re.I)
        
        if std_den_match:
            metrics['denied_standard'] = int(std_den_match.group(1).replace(",", ""))

        # Improved Patterns for expedited/urgent
        exp_total_match = re.search(r"Total requests\s+([\d,]+)", urgent_section, re.I) or \
                          re.search(r"Urgent Requests\s+([\d,]+)", urgent_section, re.I)
        
        if exp_total_match:
            metrics['total_expedited'] = int(exp_total_match.group(1).replace(",", ""))

        exp_app_match = re.search(r"Total approved\s+([\d,]+)", urgent_section, re.I) or \
                        re.search(r"Requests Approved\s+([\d,]+)", urgent_section, re.I) or \
                        re.search(r"•\s+([\d,]+)\s+requests.*?\)\s+were approved", urgent_section, re.I)
        
        if exp_app_match:
            metrics['approved_expedited'] = int(exp_app_match.group(1).replace(",", ""))

        exp_den_match = re.search(r"Total denied\s+([\d,]+)", urgent_section, re.I) or \
                        re.search(r"Requests Denied\s+([\d,]+)", urgent_section, re.I) or \
                        re.search(r"•\s+([\d,]+)\s+requests.*?\)\s+were denied", urgent_section, re.I)
        
        if exp_den_match:
            metrics['denied_expedited'] = int(exp_den_match.group(1).replace(",", ""))

        # Appeals overturned (usually at the end of each section or total)
        appeal_matches = re.findall(r"Requests approved only after appeal\s+([\d,]+)", text, re.I) or \
                         re.findall(r"([\d,]+) of the .*?appeals.*?overturned", text, re.I) or \
                         re.findall(r"Requests approved only after appeal\s+-\s+([\d,]+)", text, re.I)
        
        if appeal_matches:
            metrics['appeals_overturned_total'] = sum(int(m.replace(",", "")) for m in appeal_matches if m)

        # Basic validation fixups
        if metrics['total_standard'] == 0 and metrics['approved_standard'] > 0:
            metrics['total_standard'] = metrics['approved_standard'] + metrics['denied_standard']
        
        if metrics['total_expedited'] == 0 and metrics['approved_expedited'] > 0:
            metrics['total_expedited'] = metrics['approved_expedited'] + metrics['denied_expedited']

        return metrics

    def to_dataframe(self) -> pd.DataFrame:
        if not self.records:
            return pd.DataFrame()
        
        data = []
        for r in self.records:
            data.append({
                'county_id': r.county_id,
                'state_id': r.state_id,
                'enrollment_type': r.enrollment_type,
                'year': r.year,
                'total_requests': r.total_requests,
                'approved_requests': r.approved_requests,
                'denied_requests': r.denied_requests,
                'appeals_overturned': r.appeals_overturned,
                'expedited_requests': r.expedited_requests,
                'expedited_approved': r.expedited_approved,
                'expedited_denied': r.expedited_denied,
                'source_type': 'external'
            })
        return pd.DataFrame(data)
