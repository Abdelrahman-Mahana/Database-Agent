from typing import Any
from app.ai_reasoning.interfaces import ILLMProvider
from app.ai_reasoning.models import LLMResponse

class OpenAIProvider(ILLMProvider):
    def __init__(self, client: Any, model_name: str = "gpt-4o"):
        self.client = client
        self.model_name = model_name

    def generate(self, prompt: str) -> LLMResponse:
        # Production implementation using injected OpenAI client
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        text = response.choices[0].message.content
        tokens = response.usage.total_tokens
        return LLMResponse(text=text, tokens_used=tokens, model=self.model_name)

class GeminiProvider(ILLMProvider):
    def __init__(self, client: Any, model_name: str = "gemini-pro"):
        self.client = client
        self.model_name = model_name
        
    def generate(self, prompt: str) -> LLMResponse:
        # Production implementation using injected Google Generative AI client
        model = self.client.GenerativeModel(self.model_name)
        response = model.generate_content(prompt)
        # Approximate tokens if not provided directly
        tokens = len(prompt) // 4 + len(response.text) // 4
        return LLMResponse(text=response.text, tokens_used=tokens, model=self.model_name)

class ClaudeProvider(ILLMProvider):
    def __init__(self, client: Any, model_name: str = "claude-3-opus-20240229"):
        self.client = client
        self.model_name = model_name

    def generate(self, prompt: str) -> LLMResponse:
        # Production implementation using injected Anthropic client
        response = self.client.messages.create(
            model=self.model_name,
            max_tokens=4096,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text
        tokens = response.usage.input_tokens + response.usage.output_tokens
        return LLMResponse(text=text, tokens_used=tokens, model=self.model_name)

class LocalLLMProvider(ILLMProvider):
    def __init__(self, client: Any, model_name: str = "llama3"):
        self.client = client
        self.model_name = model_name
        
    def generate(self, prompt: str) -> LLMResponse:
        # Production implementation using injected local client (e.g. Ollama)
        response = self.client.generate(model=self.model_name, prompt=prompt)
        text = response.get("response", "")
        tokens = response.get("eval_count", len(prompt)//4)
        return LLMResponse(text=text, tokens_used=tokens, model=self.model_name)
