"""
ingestor.py — Porta de entrada da Feature Store.
Todo dado que entra passa por aqui.
Valida contra o Registry, escreve no offline e online store.
Nunca aceita dado invalido — rejeita com motivo claro.
"""
from dataclasses import dataclass, field
from typing import Any, Optional

from ..registry.registry import FeatureRegistry
from ..store.offline_store import OfflineStore
from ..store.online_store import OnlineStore


@dataclass
class IngestEvent:
    """Um evento de feature para ser ingerido."""
    entity_id: str
    feature_group: str
    feature_name: str
    feature_value: Any
    feature_ts: str          # ISO 8601 — quando a feature foi computada


@dataclass
class IngestResult:
    """Resultado de uma ingestao."""
    success: bool
    entity_id: str
    feature_group: str
    feature_name: str
    feature_value: Any
    feature_ts: str
    errors: list[str] = field(default_factory=list)


class Ingestor:

    def __init__(
        self,
        registry: FeatureRegistry,
        offline_store: OfflineStore,
        online_store: OnlineStore,
    ):
        self.registry      = registry
        self.offline_store = offline_store
        self.online_store  = online_store

    def ingest(self, event: IngestEvent) -> IngestResult:
        """
        Ingere um evento de feature.
        1. Valida contra o contrato do Registry
        2. Escreve no offline store
        3. Escreve no online store
        Retorna IngestResult com success=False e errors se falhar.
        """
        result = IngestResult(
            success=False,
            entity_id=event.entity_id,
            feature_group=event.feature_group,
            feature_name=event.feature_name,
            feature_value=event.feature_value,
            feature_ts=event.feature_ts,
        )

        # 1. valida grupo
        group = self.registry.get_group(event.feature_group)
        if group is None:
            result.errors.append(
                f"grupo '{event.feature_group}' nao existe no registry"
            )
            return result

        # 2. valida feature
        feat_def = group.get_feature(event.feature_name)
        if feat_def is None:
            result.errors.append(
                f"feature '{event.feature_name}' nao existe "
                f"no grupo '{event.feature_group}'"
            )
            return result

        # 3. valida valor
        ok, error = feat_def.validate_value(event.feature_value)
        if not ok:
            result.errors.append(error)
            return result

        # 4. escreve nos dois stores
        try:
            self.offline_store.write(
                entity_id=event.entity_id,
                feature_group=event.feature_group,
                feature_name=event.feature_name,
                feature_value=event.feature_value,
                feature_ts=event.feature_ts,
            )
            self.online_store.set(
                entity_id=event.entity_id,
                feature_group=event.feature_group,
                feature_name=event.feature_name,
                feature_value=event.feature_value,
                feature_ts=event.feature_ts,
            )
            result.success = True

        except Exception as e:
            result.errors.append(f"erro ao escrever: {e}")

        return result

    def ingest_batch(
        self, events: list[IngestEvent]
    ) -> list[IngestResult]:
        """
        Ingere uma lista de eventos.
        Processa todos — falha em um nao para os outros.
        Retorna lista de resultados na mesma ordem dos eventos.
        """
        return [self.ingest(event) for event in events]

    def ingest_from_scenarios(
        self, scenarios_path: str
    ) -> list[IngestResult]:
        """
        Ingere todos os eventos do scenarios.yaml.
        Util para popular o store em dev e testes.
        """
        import yaml
        with open(scenarios_path) as f:
            data = yaml.safe_load(f)

        events = [
            IngestEvent(
                entity_id=e["customer_id"],
                feature_group=e["feature_group"],
                feature_name=e["feature_name"],
                feature_value=e["feature_value"],
                feature_ts=e["feature_ts"],
            )
            for e in data.get("events", [])
        ]
        return self.ingest_batch(events)
