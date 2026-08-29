"""Provider/model registry and per-bot model assignment."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Provider:
    """An upstream OpenAI-compatible LLM provider. API keys live only here."""

    name: str
    base_url: str
    api_key: str
    models: tuple[str, ...] = ()

    def supports(self, model: str) -> bool:
        return not self.models or model in self.models


@dataclass(slots=True)
class BotModelAssignment:
    """Which model a bot uses, with optional per-bot overrides."""

    bot_id: str
    model: str
    fallback_models: tuple[str, ...] = ()
    allowed_models: frozenset[str] = field(default_factory=frozenset)

    def resolve(self, requested: str | None) -> str:
        """Resolve the model to use for a request from this bot."""
        if requested is None or requested == self.model:
            return self.model
        if self.allowed_models and requested not in self.allowed_models:
            raise PermissionError(
                f"bot {self.bot_id!r} is not allowed to use model {requested!r}"
            )
        return requested


class ModelRegistry:
    """Registry of providers, models, and per-bot assignments."""

    def __init__(self, default_model: str | None = None) -> None:
        self._providers: dict[str, Provider] = {}
        self._assignments: dict[str, BotModelAssignment] = {}
        self._default_model = default_model

    def add_provider(self, provider: Provider) -> None:
        if provider.name in self._providers:
            raise ValueError(f"provider {provider.name!r} already registered")
        self._providers[provider.name] = provider

    def remove_provider(self, name: str) -> None:
        self._providers.pop(name, None)

    def providers_for(self, model: str) -> list[Provider]:
        """All providers able to serve ``model``, in registration order."""
        return [p for p in self._providers.values() if p.supports(model)]

    def assign(self, assignment: BotModelAssignment) -> None:
        self._assignments[assignment.bot_id] = assignment

    def assignment_for(self, bot_id: str) -> BotModelAssignment:
        assignment = self._assignments.get(bot_id)
        if assignment is not None:
            return assignment
        if self._default_model is None:
            raise KeyError(f"no model assignment for bot {bot_id!r} and no default model")
        return BotModelAssignment(bot_id=bot_id, model=self._default_model)

    def candidate_models(self, bot_id: str, requested: str | None) -> list[str]:
        """Primary model plus fallbacks for a bot's request."""
        assignment = self.assignment_for(bot_id)
        primary = assignment.resolve(requested)
        candidates = [primary]
        for fallback in assignment.fallback_models:
            if fallback not in candidates:
                candidates.append(fallback)
        return candidates
