from __future__ import annotations

import logging

import pandas as pd

from .config import ALLOWED_DATA_CUTS, NUMERIC_COLUMNS, REQUIRED_COLUMNS, STRING_COLUMNS

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    pass


class DataValidator:
    """Schema and range validation for MSSP PUF ingestion."""

    def validate(self, df: pd.DataFrame) -> None:
        """Run all validation checks; raise ValidationError on any failure."""
        self.validate_schema(df)
        errors: list[str] = []
        errors += self.validate_dtypes(df)
        errors += self.validate_ranges(df)
        errors += self.validate_key_columns(df)
        if errors:
            raise ValidationError("; ".join(errors))

    def validate_schema(self, df: pd.DataFrame) -> None:
        """Raise if any required column (other than dataset_id) is missing."""
        missing = [
            col
            for col in REQUIRED_COLUMNS
            if col != "dataset_id" and col not in df.columns
        ]
        if missing:
            raise ValidationError(f"Missing required columns: {', '.join(missing)}")
        if "dataset_id" not in df.columns:
            logger.warning(
                "dataset_id is absent; cross-dataset deduplication will be skipped."
            )

    def validate_dtypes(self, df: pd.DataFrame) -> list[str]:
        errors: list[str] = []
        for col in STRING_COLUMNS:
            if col in df.columns and not pd.api.types.is_string_dtype(df[col]):
                errors.append(f"{col} should be string dtype")
        for col in NUMERIC_COLUMNS:
            if col in df.columns and not pd.api.types.is_numeric_dtype(df[col]):
                errors.append(f"{col} should be numeric dtype")
        if errors:
            logger.warning("Dtype issues: %s", errors)
        return errors

    def validate_ranges(self, df: pd.DataFrame) -> list[str]:
        errors: list[str] = []
        if "avg_risk_score" in df.columns:
            if df["avg_risk_score"].dropna().lt(0).any() or df["avg_risk_score"].dropna().gt(5).any():
                errors.append("avg_risk_score values outside [0, 5]")
        if "per_capita_exp" in df.columns and df["per_capita_exp"].dropna().lt(0).any():
            errors.append("per_capita_exp contains negative values")
        if "person_years" in df.columns and df["person_years"].dropna().lt(0).any():
            errors.append("person_years contains negative values")
        if "data_cut" in df.columns:
            invalid = df.loc[~df["data_cut"].isin(ALLOWED_DATA_CUTS), "data_cut"].unique()
            if len(invalid):
                errors.append(f"Unrecognised data_cut values: {sorted(invalid)}")
        return errors

    def validate_key_columns(self, df: pd.DataFrame) -> list[str]:
        errors: list[str] = []
        for col in ("year", "state_id", "county_id"):
            if col in df.columns and df[col].isna().any():
                errors.append(f"{col} has missing values")
        return errors
