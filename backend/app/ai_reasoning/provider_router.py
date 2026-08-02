from app.ai_reasoning.interfaces import IProviderRouter, ILLMProvider

class ProviderRouter(IProviderRouter):
    def __init__(self, openai_provider: ILLMProvider, gemini_provider: ILLMProvider, claude_provider: ILLMProvider, local_provider: ILLMProvider):
        self.providers = {
            "openai": openai_provider,
            "gemini": gemini_provider,
            "claude": claude_provider,
            "local": local_provider
        }
        self.default_provider = "openai"

    def get_provider(self, name: str = None) -> ILLMProvider:
        prov_name = name or self.default_provider
        return self.providers.get(prov_name.lower(), self.providers[self.default_provider])
