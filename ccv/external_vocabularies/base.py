"""Interface for controlled vocabularies provided by external platforms."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from django.apps import apps
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


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

    A vocabulary row names its source class in ``live_search_adapter``. Searchable sources are
    queried when users search and their results are kept in the vocabulary terms table. Sources
    that can be listed in full are loaded with the ``load_external_vocabulary`` management command.

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


def live_search_source(key: str) -> ExternalVocabularySource | None:
    """
    The live-search source of a vocabulary, from the class its row in the vocabulary table names.

    Args:
        key: Key of the vocabulary.

    Returns:
        A source instance, or ``None`` when the vocabulary has no live-search class or it cannot be loaded.
    """
    path = (
        apps.get_model("ccv", "Vocabulary")
        .objects.filter(key=key)
        .exclude(live_search_adapter="")
        .values_list("live_search_adapter", flat=True)
        .first()
    )
    if not path:
        return None
    try:
        return import_string(path)()
    except ImportError:
        logger.warning("Live-search class %s of vocabulary %s cannot be loaded", path, key)
        return None
