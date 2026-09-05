from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, ConfigDict


class DataPathsConfig(BaseModel):
    raw: str
    processed: str
    features: str
    models: str
    derived: str


class Config(BaseModel):
    model_config = ConfigDict(frozen=True)

    data_paths: DataPathsConfig


def load_config(config_path: Optional[str | Path] = None) -> Config:
    if config_path is None:
        # PROJECT_ROOT/configs/config.yaml
        config_path = Path(__file__).resolve().parents[3] / "configs" / "config.yaml"
    else:
        config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found at: {config_path.absolute()}")

    with open(config_path, "r") as f:
        config_dict = yaml.safe_load(f) or {}

    return Config.model_validate(config_dict)
