from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Anthropic
    anthropic_api_key: str
    model_name: str = "claude-sonnet-4-6"  # override in .env or agent_config.yaml

    # IBKR
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7497
    ibkr_client_id: int = 1
    ibkr_account_id: str = ""

    # Binance
    binance_api_key: str = ""
    binance_api_secret: str = ""
    binance_testnet: bool = False

    # Bitget
    bitget_api_key: str = ""
    bitget_api_secret: str = ""
    bitget_passphrase: str = ""

    # TradingView
    tradingview_webhook_secret: str = ""

    # Voice
    deepgram_api_key: str = ""
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"

    # Database
    database_url: str = "postgresql://jarvis:jarvis_password@localhost:5432/jarvis"

    # App
    jarvis_secret_key: str = "change_me"
    jarvis_host: str = "0.0.0.0"
    jarvis_port: int = 8000
    jarvis_env: str = "development"

    # Briefing
    briefing_time: str = "07:00"
    briefing_email: Optional[str] = None
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""


settings = Settings()
