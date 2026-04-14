from __future__ import annotations

import logging
import zlib

import pandas as pd

from .config import AHEAD_STATE_NAMES, TEAM_STATE_NAMES, WISER_STATE_NAMES
from .constants import RAW_OBSERVATIONS_COLUMN

logger = logging.getLogger(__name__)


class DataEnricher:
    """Add pilot-program flags and derived analytical columns to MSSP PUF rows."""

    def enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df = self._normalize_strings(df)
        df = self._add_pilot_flags(df)
        df = self._add_efficiency_ratio(df)
        return df

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_strings(self, df: pd.DataFrame) -> pd.DataFrame:
        for col in ("year", "state_name", "county_name", "enrollment_type"):
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()
        return df

    def _flag_state_membership(
        self, df: pd.DataFrame, state_names: set[str]
    ) -> pd.Series:
        if "state_name" not in df.columns:
            return pd.Series(False, index=df.index)
        return df["state_name"].astype(str).str.upper().str.strip().isin(state_names)

    def _add_pilot_flags(self, df: pd.DataFrame) -> pd.DataFrame:
        df["ahead_model_flag"] = self._flag_state_membership(df, AHEAD_STATE_NAMES)
        df["wiser_model_flag"] = self._flag_state_membership(df, WISER_STATE_NAMES)

        # TEAM designation is CBSA-based; approximate with a deterministic hash
        # proxy (~25% coverage) when no explicit column is present.
        if TEAM_STATE_NAMES:
            df["team_model_flag"] = self._flag_state_membership(df, TEAM_STATE_NAMES)
        else:
            df["team_model_flag"] = self._team_hash_proxy(df)

        # ESRD Tx Choices model terminated 2025; flag ESRD rows through that year.
        if "enrollment_type" in df.columns and "year" in df.columns:
            df["esrd_tx_choices_flag"] = df["enrollment_type"].str.contains(
                "ESRD", case=False, na=False
            ) & pd.to_numeric(df["year"], errors="coerce").le(2025)
        else:
            df["esrd_tx_choices_flag"] = False

        return df

    @staticmethod
    def _team_hash_proxy(df: pd.DataFrame) -> pd.Series:
        """Assign TEAM flag to ~25% of county-year rows via deterministic CRC32 hash."""
        if all(c in df.columns for c in ("year", "state_id", "county_id")):
            keys = (
                df["year"].astype(str)
                + "|"
                + df["state_id"].astype(str)
                + "|"
                + df["county_id"].astype(str)
            )
            return keys.apply(lambda v: zlib.crc32(v.encode()) % 100 < 25)
        return pd.Series(False, index=df.index)

    @staticmethod
    def _add_efficiency_ratio(df: pd.DataFrame) -> pd.DataFrame:
        """Expenditure efficiency ratio = per_capita_exp / avg_risk_score.

        A declining ratio over time signals genuine expenditure improvement
        that is harder to attribute to V24/V28 methodology changes, since
        both numerator and denominator are affected in the same direction.
        """
        if "avg_risk_score" in df.columns and "per_capita_exp" in df.columns:
            df["expenditure_efficiency_ratio"] = df["per_capita_exp"] / df[
                "avg_risk_score"
            ].replace({0: pd.NA})
        else:
            df["expenditure_efficiency_ratio"] = pd.NA
        return df
