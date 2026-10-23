"""Interface for controlled vocabularies provided by external platforms."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any


class ExternalVocabularyError(Exception):
    """Raised by a source when its platform cannot be reached or rejects a request."""


@dataclass(frozen=True)
class ExternalTermData:
    """
    One vocabulary term as returned by an external platform.

    Attributes:
        external_id: Identifier of the term on the platform.
        name: Name shown to users.
        description: Short description shown with the name.
        synonyms: Other names the term is found by.
        data: Full record from the platform.
    """

    external_id: str
    name: str
    description: str = ""
    synonyms: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)


class ExternalVocabularySource(ABC):
    """
    A vocabulary of one kind from one external platform.

    Searchable sources are queried when users search and their results are kept in the local
    cache. Sources that can be listed in full are loaded with the ``load_external_vocabulary``
    management command.

    Attributes:
        key: Unique key, also used as the ontology type of the vocabulary.
        platform: Platform the vocabulary comes from, for example ``protocols_io``.
        kind: Kind of term, for example ``reagent`` or ``unit``.
        label: Name shown to users.
        searchable: Whether :meth:`search` is supported.
        min_term_length: Shortest search text sent to the platform.
        page_size: Results requested from the platform per search.
    """

    key: str
    platform: str
    kind: str
    label: str
    searchable: bool = True
    min_term_length: int = 3
    page_size: int = 25

    @abstractmethod
    def is_configured(self) -> bool:
        """Return whether the instance has the settings needed to reach the platform."""

    def search(self, term: str, limit: int) -> list[ExternalTermData]:
        """
        Search the platform.

        Args:
            term: Search text.
            limit: Most results to return.

        Raises:
            NotImplementedError: When the source is not searchable.
        """
        raise NotImplementedError(f"{self.key} cannot be searched")

    def load_all(self, **options: str) -> Iterable[ExternalTermData]:
        """
        List every term of the vocabulary.

        Args:
            options: Source specific options from the management command.

        Raises:
            NotImplementedError: When the vocabulary cannot be listed in full.
        """
        raise NotImplementedError(f"{self.key} cannot be loaded in full")


class SourceRegistry:
    """Registered external vocabulary sources, by key."""

    def __init__(self) -> None:
        """Start with no registered sources."""
        self._sources: dict[str, ExternalVocabularySource] = {}
        self._listeners: list[Callable[[ExternalVocabularySource], None]] = []

    def register(self, source: ExternalVocabularySource) -> ExternalVocabularySource:
        """
        Add a source.

        Raises:
            ValueError: When another source already uses the same key.
        """
        if source.key in self._sources:
            raise ValueError(f"an external vocabulary source with key {source.key!r} is already registered")
        self._sources[source.key] = source
        for listener in self._listeners:
            listener(source)
        return source

    def on_register(self, listener: Callable[[ExternalVocabularySource], None]) -> None:
        """
        Call ``listener`` with every registered source, now and whenever another source is registered.

        Args:
            listener: Called with one source at a time.
        """
        self._listeners.append(listener)
        for source in self.all():
            listener(source)

    def get(self, key: str) -> ExternalVocabularySource | None:
        """Return the source with ``key``, or ``None``."""
        return self._sources.get(key)

    def all(self) -> list[ExternalVocabularySource]:
        """Return every registered source."""
        return list(self._sources.values())


sources = SourceRegistry()
