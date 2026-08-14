import os


ENV_NAME = "OAS_XIUXING_HEXUN_ENABLED"


def xiuxing_hexun_globally_enabled() -> bool:
    return os.getenv(ENV_NAME, "1").strip().lower() in {"1", "true", "yes", "on"}
