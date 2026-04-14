from __future__ import annotations

import pandas as pd


def build_team_episode_proxy(
    df: pd.DataFrame,
    team_flag_col: str = "team_model_flag",
    per_capita_col: str = "per_capita_exp",
) -> pd.DataFrame:
    """Build a TEAM episode cost proxy for TEAM-designated county cohorts."""
    if per_capita_col not in df.columns:
        raise ValueError("Required per-capita expenditure column is missing for TEAM cost proxy")

    df = df.copy()
    if team_flag_col not in df.columns:
        df[team_flag_col] = False

    df["team_episode_proxy_cost"] = df[per_capita_col].fillna(0) * df[team_flag_col].map({False: 0.11, True: 0.18}).fillna(0.11)
    df["team_episode_proxy_ratio"] = df["team_episode_proxy_cost"] / df["team_episode_proxy_cost"].replace({0: 1}).mean()
    return df
