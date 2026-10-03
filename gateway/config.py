import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    data_dir: Path
    binary: str = "opencode"
    secure_cookies: bool = False
    public_origin: str = ""
    bootstrap_token: str = ""
    max_body_bytes: int = 2 * 1024 * 1024
    max_output_bytes: int = 2 * 1024 * 1024
    web_dir: Path = Path(__file__).resolve().parent.parent / "web/dist"

    @classmethod
    def from_env(cls):
        return cls(
            data_dir=Path(os.environ.get("GATEWAY_DATA_DIR", "data")).resolve(),
            binary=os.environ.get("GATEWAY_OPENCODE_BINARY", "opencode"),
            secure_cookies=os.environ.get("GATEWAY_SECURE_COOKIES", "false").lower() == "true",
            public_origin=os.environ.get("GATEWAY_PUBLIC_ORIGIN", "").rstrip("/"),
            bootstrap_token=os.environ.get("GATEWAY_BOOTSTRAP_TOKEN", ""),
            web_dir=Path(os.environ.get("GATEWAY_WEB_DIR", str(cls.web_dir))).resolve(),
        )
