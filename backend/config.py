from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Azure OpenAI (Microsoft Foundry)
    azure_openai_endpoint: Optional[str] = ""
    azure_openai_api_key: Optional[str] = ""
    azure_openai_chat_deployment: Optional[str] = ""
    azure_openai_embedding_deployment: Optional[str] = ""
    azure_openai_api_version: Optional[str] = "2025-04-01-preview"

    # Azure AI Search
    azure_search_endpoint: Optional[str] = ""
    azure_search_key: Optional[str] = ""
    azure_search_index: Optional[str] = "loan-knowledge-source"

    # Azure Blob Storage
    azure_storage_account: Optional[str] = ""
    azure_storage_container: Optional[str] = ""

    # DART OpenAPI
    dart_api_key: Optional[str] = ""

    # Bing Grounding (Azure AI Foundry Connection)
    bing_connection_id: Optional[str] = ""

    class Config:
        env_file = "../.env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def azure_connected(self) -> bool:
        return bool(self.azure_openai_endpoint and self.azure_openai_chat_deployment)


@lru_cache
def get_settings() -> Settings:
    return Settings()
