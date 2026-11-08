"""Live search of plugin vocabularies: the backend asks the plugin at its registered address."""

from __future__ import annotations

from ccc.plugin.connection import PluginConnectionError, call_plugin
from ccc.plugin.model import Plugin
from ccv.external_vocabularies.base import ExternalTermData, ExternalVocabularyError, ExternalVocabularySource
from ccv.models import Vocabulary
from ccv.serializers import PluginTermSerializer


def search_path(local_key: str) -> str:
    """The path of a vocabulary's search endpoint on its plugin."""
    return f"cupcake/vocabularies/{local_key}/search"


class PluginVocabularySource(ExternalVocabularySource):
    """
    A plugin vocabulary declared with ``liveSearch``, searched at ``<base_url>/cupcake/vocabularies/<key>/search``.

    The plugin answers ``{"results": [...]}`` with terms in the form it sends them to
    ``/plugin-vocabularies/<key>/terms/``. Obsolete and invalid terms are left out. A failed search marks the
    vocabulary unavailable with the error; the next successful one marks it active again.
    """

    platform = "plugin"

    def __init__(self, vocabulary: Vocabulary):
        """Search the given plugin vocabulary."""
        self.vocabulary = vocabulary
        self.key = vocabulary.key
        self.kind = vocabulary.kind
        self.label = vocabulary.label
        self.min_term_length = vocabulary.min_term_length
        self.local_key = vocabulary.key.removeprefix(f"plugin.{vocabulary.plugin.name}.") if vocabulary.plugin else ""

    @classmethod
    def for_vocabulary(cls, vocabulary: Vocabulary) -> PluginVocabularySource:
        return cls(vocabulary)

    def is_configured(self) -> bool:
        """Whether the vocabulary is approved and its plugin is active, running and was reached at startup."""
        plugin = self.vocabulary.plugin
        return bool(
            plugin
            and self.vocabulary.approved
            and self.vocabulary.status != Vocabulary.STATUS_DISABLED
            and plugin.is_active
            and plugin.lifecycle_status == Plugin.LIFECYCLE_RUNNING
            and plugin.connection_verified_at
        )

    def search(self, term: str, limit: int) -> list[ExternalTermData]:
        try:
            body = call_plugin(self.vocabulary.plugin, search_path(self.local_key), {"q": term, "limit": limit})
        except PluginConnectionError as error:
            self._mark(Vocabulary.STATUS_UNAVAILABLE, f"Search failed: {error}")
            raise ExternalVocabularyError(str(error))
        results = body.get("results")
        if not isinstance(results, list):
            self._mark(Vocabulary.STATUS_UNAVAILABLE, "Search answered without a results list")
            raise ExternalVocabularyError("answered without a results list")
        self._mark(Vocabulary.STATUS_ACTIVE, "")
        terms = []
        for result in results[:limit]:
            serializer = PluginTermSerializer(data=result)
            if not serializer.is_valid() or serializer.validated_data["obsolete"]:
                continue
            data = serializer.validated_data
            terms.append(
                ExternalTermData(
                    external_id=data["id"],
                    name=data["name"],
                    description=data["description"],
                    synonyms=tuple(synonym.strip() for synonym in data["synonyms"] if synonym.strip()),
                    data=data["data"],
                )
            )
        return terms

    def _mark(self, status: str, error: str) -> None:
        if (self.vocabulary.status, self.vocabulary.last_error) == (status, error):
            return
        self.vocabulary.status = status
        self.vocabulary.last_error = error
        self.vocabulary.save(update_fields=["status", "last_error", "updated_at"])
