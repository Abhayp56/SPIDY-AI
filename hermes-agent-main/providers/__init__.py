"""
providers/__init__.py — Provider Profiles & Metadata for Hermes Agent
"""

from typing import Any, Dict, List, Optional, Tuple


class ProviderProfile:
    def __init__(self, name: str = "openrouter"):
        self.name = name
        self.aliases = [name]
        self.default_aux_model = "nousresearch/hermes-3-llama-3.1-405b:free"
        self.default_fast_aux_model = "nousresearch/hermes-3-llama-3.1-8b:free"
        self.api_mode = "openai"
        self.auth_mode = "api_key"
        self.context_length = 128000
        self.max_tokens = 4096
        self.fixed_temperature = None
        self.model_capabilities: Dict[str, Any] = {}
        self.default_headers: Dict[str, str] = {}

    def get_model_context_length(self, model: str = "") -> int:
        return 128000

    def get_max_tokens(self, model: str = "") -> Optional[int]:
        return self.max_tokens

    def prepare_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return messages

    def build_api_kwargs_extras(self, *args, **kwargs) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        return {}, {}

    def build_extra_body(self, *args, **kwargs) -> Dict[str, Any]:
        return {}

    def default_reasoning_config(self, model: str = "") -> Any:
        return None

    def supported_reasoning_efforts(self, model: str = "") -> Any:
        return None

    def resolve_aux_model(self, *args, **kwargs) -> str:
        return ""

    def get_usage_cost(self, *args, **kwargs) -> Any:
        return None

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key, None)


def get_provider_profile(provider_name: str = "openrouter", *args, **kwargs) -> ProviderProfile:
    return ProviderProfile(provider_name)
