from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    GITHUB_TOKEN: str
    GITHUB_WEBHOOK_SECRET: str
    GITHUB_BOT_USERNAME: str = "pr-review-bot"
    
    # OpenRouter configuration
    OPENROUTER_API_KEY: str
    OPENROUTER_MODEL: str = "openai/gpt-4o-mini"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

    class Config:
        env_file = ".env"

settings = Settings()