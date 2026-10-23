"""protocols.io reagent and unit vocabularies."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from choux import ChouxError, ProtocolsIO, RateLimiter
from choux.units import unit_kind

from ccv.external_vocabularies.base import ExternalTermData, ExternalVocabularyError, ExternalVocabularySource, sources
from cupcake_protocols_io import conf

rate_limiter = RateLimiter()


def _client() -> ProtocolsIO:
    return ProtocolsIO(conf.access_token(), rate_limiter=rate_limiter, max_retries=1, timeout=10.0)


def reagent_term(item: Mapping[str, Any]) -> ExternalTermData:
    """
    Convert a protocols.io catalogue reagent into a vocabulary term.

    Args:
        item: Reagent from the protocols.io reagent search.
    """
    vendor = (item.get("vendor") or {}).get("name") or ""
    sku = item.get("sku") or ""
    description = " ".join(part for part in (vendor, f"Catalog #{sku}" if sku else "") if part)
    return ExternalTermData(
        external_id=str(item.get("id") or ""),
        name=item.get("name") or "",
        description=description,
        synonyms=(sku,) if sku else (),
        data=dict(item),
    )


def unit_term(unit: Mapping[str, Any]) -> ExternalTermData:
    """
    Convert a protocols.io unit into a vocabulary term.

    Args:
        unit: Unit from the ``units`` list of a protocol.
    """
    return ExternalTermData(
        external_id=str(unit.get("id") or ""),
        name=unit.get("name") or "",
        description=unit_kind(unit) or "",
        synonyms=tuple(alias for alias in unit.get("aliases") or [] if alias),
        data=dict(unit),
    )


class ProtocolsIOReagentSource(ExternalVocabularySource):
    """Reagents from the protocols.io catalogue, searched by name, catalogue number or vendor."""

    key = "protocols_io_reagent"
    platform = "protocols_io"
    kind = "reagent"
    label = "protocols.io Reagent"

    def is_configured(self) -> bool:
        return bool(conf.access_token())

    def search(self, term: str, limit: int) -> list[ExternalTermData]:
        try:
            with _client() as client:
                items = client.search_reagents(term, page_size=limit)["items"]
        except ChouxError as error:
            raise ExternalVocabularyError(str(error)) from error
        return [reagent_term(item) for item in items]


class ProtocolsIOUnitSource(ExternalVocabularySource):
    """Units for amounts, temperatures, concentrations and other quantities on protocols.io."""

    key = "protocols_io_unit"
    platform = "protocols_io"
    kind = "unit"
    label = "protocols.io Unit"
    searchable = False

    def is_configured(self) -> bool:
        return bool(conf.access_token())

    def load_all(self, **options: str) -> Iterable[ExternalTermData]:
        """
        List the units protocols.io offers, read from any protocol the token can open.

        Args:
            options: ``protocol``, the id or URI of that protocol; defaults to the
                ``PROTOCOLS_IO_UNITS_PROTOCOL`` setting.

        Raises:
            ValueError: When no protocol is given.
            ExternalVocabularyError: When protocols.io rejects the request.
        """
        protocol = options.get("protocol") or conf.units_protocol()
        if not protocol:
            raise ValueError("pass protocol=<id or uri> or set PROTOCOLS_IO_UNITS_PROTOCOL")
        try:
            with _client() as client:
                units = client.get_units(protocol)
        except ChouxError as error:
            raise ExternalVocabularyError(str(error)) from error
        return [unit_term(unit) for unit in units if not unit.get("deleted")]


reagents = sources.register(ProtocolsIOReagentSource())
units = sources.register(ProtocolsIOUnitSource())
