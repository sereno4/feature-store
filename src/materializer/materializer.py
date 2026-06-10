"""
materializer.py — Sincroniza offline store com online store.
Le os valores mais recentes do Parquet e popula o Redis/memoria.
Roda sob demanda ou periodicamente em producao.
Resolve o problema de o online store comecar vazio apos restart.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

import duckdb

from ..store.offline_store import OfflineStore
from ..store.online_store import OnlineStore


@dataclass
class MaterializationResult:
    success: bool
    features_materialized: int = 0
    entities_updated: set = field(default_factory=set)
    errors: list[str] = field(default_factory=list)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    finished_at: str = ""


class Materializer:

    def __init__(
        self,
        offline_store: OfflineStore,
        online_store: OnlineStore,
    ):
        self.offline_store = offline_store
        self.online_store  = online_store
        self._conn         = duckdb.connect()

    def materialize_all(self) -> MaterializationResult:
        """
        Materializa todos os valores mais recentes
        do offline store para o online store.

        Para cada (entity_id, feature_group, feature_name)
        pega o valor com o feature_ts mais recente
        e escreve no online store.
        """
        result = MaterializationResult(success=False)

        if not self.offline_store._parquet_path.exists():
            result.errors.append("offline store vazio — nada para materializar")
            result.success = True
            result.finished_at = datetime.now(timezone.utc).isoformat()
            return result

        try:
            # query que pega o valor mais recente
            # para cada combinacao unica de entity + feature
            rows = self._conn.execute("""
                SELECT
                    entity_id,
                    feature_group,
                    feature_name,
                    feature_value,
                    feature_ts
                FROM (
                    SELECT
                        entity_id,
                        feature_group,
                        feature_name,
                        feature_value,
                        feature_ts,
                        ROW_NUMBER() OVER (
                            PARTITION BY entity_id, feature_group, feature_name
                            ORDER BY feature_ts DESC
                        ) AS rn
                    FROM parquet_scan(?)
                ) ranked
                WHERE rn = 1
            """, [str(self.offline_store._parquet_path)]).fetchall()

            import json
            for row in rows:
                entity_id, group, name, raw_value, ts = row
                value = json.loads(raw_value)

                self.online_store.set(
                    entity_id=entity_id,
                    feature_group=group,
                    feature_name=name,
                    feature_value=value,
                    feature_ts=ts,
                )
                result.features_materialized += 1
                result.entities_updated.add(entity_id)

            result.success = True

        except Exception as e:
            result.errors.append(f"erro durante materializacao: {e}")

        result.finished_at = datetime.now(timezone.utc).isoformat()
        return result

    def materialize_entity(
        self, entity_id: str
    ) -> MaterializationResult:
        """
        Materializa apenas as features de uma entidade.
        Util para atualizar um cliente especifico
        sem reprocessar o store inteiro.
        """
        result = MaterializationResult(success=False)

        if not self.offline_store._parquet_path.exists():
            result.success = True
            result.finished_at = datetime.now(timezone.utc).isoformat()
            return result

        try:
            import json
            rows = self._conn.execute("""
                SELECT
                    entity_id,
                    feature_group,
                    feature_name,
                    feature_value,
                    feature_ts
                FROM (
                    SELECT
                        entity_id,
                        feature_group,
                        feature_name,
                        feature_value,
                        feature_ts,
                        ROW_NUMBER() OVER (
                            PARTITION BY entity_id, feature_group, feature_name
                            ORDER BY feature_ts DESC
                        ) AS rn
                    FROM parquet_scan(?)
                    WHERE entity_id = ?
                ) ranked
                WHERE rn = 1
            """, [str(self.offline_store._parquet_path), entity_id]).fetchall()

            for row in rows:
                eid, group, name, raw_value, ts = row
                value = json.loads(raw_value)

                self.online_store.set(
                    entity_id=eid,
                    feature_group=group,
                    feature_name=name,
                    feature_value=value,
                    feature_ts=ts,
                )
                result.features_materialized += 1
                result.entities_updated.add(eid)

            result.success = True

        except Exception as e:
            result.errors.append(f"erro: {e}")

        result.finished_at = datetime.now(timezone.utc).isoformat()
        return result
