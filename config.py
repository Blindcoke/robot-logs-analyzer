from typing import List
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application configuration settings."""

    # Application
    APP_NAME: str = Field(default="Robot Log Analysis Agent",
                          description="Application name")
    DEBUG: bool = Field(default=False, description="Debug mode")

    # Log source configuration
    LOG_FILE_PATH: str = Field(
        default="./logs/robot.log",
        description="Path to log file to monitor"
    )
    SIMULATION_MODE: bool = Field(
        default=True,
        description="Enable simulation mode with generated logs"
    )
    SIMULATION_INTERVAL_MIN: float = Field(
        default=2.0,
        description="Minimum seconds between simulated log entries"
    )
    SIMULATION_INTERVAL_MAX: float = Field(
        default=5.0,
        description="Maximum seconds between simulated log entries"
    )

    # Context engine configuration
    CONTEXT_WINDOW_SIZE: int = Field(
        default=50,
        description="Number of log lines to keep in sliding window"
    )
    CONTEXT_TIMEOUT_SEC: int = Field(
        default=30,
        description="Seconds before flushing context window"
    )

    # Error detection
    ERROR_KEYWORDS: List[str] = Field(
        default=[
            "ERROR", "FATAL", "CRITICAL",
            "Exception", "exception", "failed", "Failed",
            "timeout", "Timeout", "unable", "Unable",
            "cannot", "Cannot", "refused", "Refused"
        ],
        description="Keywords that trigger error analysis"
    )
    WARNING_KEYWORDS: List[str] = Field(
        default=["WARN", "Warning", "warning", "deprecated"],
        description="Keywords that indicate warnings"
    )

    # AI Configuration
    OPENAI_API_KEY: str = Field(
        default="",
        description="OpenAI API key"
    )
    OPENAI_MODEL: str = Field(
        default="gpt-3.5-turbo",
        description="OpenAI model to use (gpt-3.5-turbo is cheaper)"
    )
    MAX_TOKENS: int = Field(
        default=2048,
        description="Maximum tokens for AI response"
    )
    AI_TEMPERATURE: float = Field(
        default=0.1,
        description="AI temperature (0.0-1.0)"
    )
    AI_TIMEOUT_SEC: int = Field(
        default=30,
        description="Timeout for AI API calls"
    )

    # API Configuration
    API_HOST: str = Field(default="0.0.0.0", description="API host")
    API_PORT: int = Field(default=8000, description="API port")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Global settings instance
settings = Settings()
