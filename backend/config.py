from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    azure_openai_endpoint: str
    azure_openai_api_key: str
    azure_openai_chat_deployment: str
    azure_openai_embedding_deployment: str
    azure_openai_api_version: str

    azure_search_endpoint: str
    azure_search_key: str
    azure_search_index: str

    azure_storage_account: str
    azure_storage_container: str

    class Config:
        env_file = "../.env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
