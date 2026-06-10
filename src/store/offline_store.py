"""
offline_store.py — Armazenamento historico com DuckDB + Parquet.
Implementa point-in-time correctness para treino sem data leakage.

Estrutura do Parquet:
  entity_id    : str   — identificador da entidade (ex: customer_id)
  feature_group: str   — grupo da feature (ex: support)
  feature_name : str   — nome da feature (ex: open_tickets)
  feature_value: str   — valor serializado como string
  feature_ts   : str   — ISO 8601, quando a feature foi computada
  ingested_at  : str   — ISO 8601, quando foi salva no store
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


SCHEMA = pa.schema([
    pa.field("entity_id",     pa.string()),
    pa.field("feature_group", pa.string()),
    pa.field("feature_name",  pa.string()),
    pa.field("feature_value", pa.string()),
    pa.field("feature_ts",    pa.string()),
    pa.field("ingested_at",   pa.string()),
])


class OfflineStore:

    def __init__(self, store_path: str = "data/offline"):
        self.store_path = Path(store_path)
        self.store_path.mkdir(parents=True, exist_ok=True)
        self._parquet_path = self.store_path / "features.parquet"
        self._conn = duckdb.connect()

    # ── escrita ───────────────────────────────────────────────

    def write(
        self,
        entity_id: str,
        feature_group: str,
        feature_name: str,
        feature_value: Any,
        feature_ts: str,
    ):
        """
        Salva um evento de feature no Parquet.
        Nunca sobrescreve — sempre appenda.
        """
        now = datetime.now(timezone.utc).isoformat()
        row = pa.table({
            "entity_id":     [entity_id],
            "feature_group": [feature_group],
            "feature_name":  [feature_name],
            "feature_value": [json.dumps(feature_value)],
            "feature_ts":    [feature_ts],
            "ingested_at":   [now],
        }, schema=SCHEMA)

        if self._parquet_path.exists():
            existing = pq.read_table(self._parquet_path)
            combined = pa.concat_tables([existing, row])
            pq.write_table(combined, self._parquet_path)
        else:
            pq.write_table(row, self._parquet_path)

    # ── leitura point-in-time ─────────────────────────────────

    def get_point_in_time(
        self,
        entity_id: str,
        feature_group: str,
        feature_name: str,
        as_of: str,
    ) -> Optional[Any]:
        """
        Retorna o valor mais recente da feature
        para o entity_id no instante as_of.
        So retorna o que existia ANTES de as_of.
        Nunca vaza dados do futuro.
        """
        if not self._parquet_path.exists():
            return None

        result = self._conn.execute("""
            SELECT feature_value
            FROM parquet_scan(?)
            WHERE entity_id    = ?
              AND feature_group = ?
              AND feature_name  = ?
              AND feature_ts   <= ?
            ORDER BY feature_ts DESC
            LIMIT 1
        """, [
            str(self._parquet_path),
            entity_id,
            feature_group,
            feature_name,
            as_of,
        ]).fetchone()

        if result is None:
            return None

        return json.loads(result[0])

    # ── dataset de treino ─────────────────────────────────────

    def get_training_dataset(
        self,
        labels: list[dict],
        feature_groups: list[str],
        feature_names: list[str],
    ) -> pd.DataFrame:
        """
        Gera dataset de treino sem data leakage.
        Para cada label, busca o valor point-in-time
        de cada feature — so o que existia antes de label_ts.

        Sempre retorna uma linha por label,
        com None nas features sem dados — nunca DataFrame vazio.
        """
        rows = []
        for label in labels:
            entity_id = label["entity_id"]
            label_ts  = label["label_ts"]
            row = {"entity_id": entity_id, "label_ts": label_ts}

            for group, name in zip(feature_groups, feature_names):
                col = f"{group}__{name}"
                row[col] = self.get_point_in_time(
                    entity_id, group, name, label_ts
                )

            rows.append(row)

        return pd.DataFrame(rows)

    # ── utilitarios ───────────────────────────────────────────

    def count(self) -> int:
        """Total de eventos no store."""
        if not self._parquet_path.exists():
            return 0
        result = self._conn.execute(
            "SELECT COUNT(*) FROM parquet_scan(?)",
            [str(self._parquet_path)],
        ).fetchone()
        return result[0] if result else 0

    def get_entity_history(
        self, entity_id: str
    ) -> pd.DataFrame:
        """
        Retorna todo o historico de um entity_id.
        Util para debug e auditoria.
        """
        if not self._parquet_path.exists():
            return pd.DataFrame()

        return self._conn.execute("""
            SELECT *
            FROM parquet_scan(?)
            WHERE entity_id = ?
            ORDER BY feature_ts ASC
        """, [str(self._parquet_path), entity_id]).df()

    def clear(self):
        """Remove todos os dados. Usado em testes."""
        if self._parquet_path.exists():
            self._parquet_path.unlink()
