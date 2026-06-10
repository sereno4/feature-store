"""
online_store.py — Store de baixa latencia para inferencia.
Guarda apenas o valor mais recente de cada feature.
Dev: dicionario em memoria.
Prod: trocar _backend por Redis sem mudar a interface.
"""
from datetime import datetime, timezone
from typing import Any, Optional


class InMemoryBackend:
    """
    Backend em memoria para dev e testes.
    Mesma interface que o RedisBackend teria.
    """

    def __init__(self):
        self._data: dict[str, Any] = {}

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    def set(self, key: str, value: str):
        self._data[key] = value

    def delete(self, key: str):
        self._data.pop(key, None)

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return [k for k in self._data if k.startswith(prefix)]

    def flush(self):
        self._data.clear()

    def size(self) -> int:
        return len(self._data)


class OnlineStore:
    """
    Interface de serving para inferencia online.
    Latencia alvo: < 5ms por feature.

    Chave: {entity_id}:{feature_group}:{feature_name}
    Valor: JSON serializado com value + updated_at
    """

    def __init__(self, backend: Optional[InMemoryBackend] = None):
        self._backend = backend or InMemoryBackend()

    def _make_key(
        self,
        entity_id: str,
        feature_group: str,
        feature_name: str,
    ) -> str:
        return f"{entity_id}:{feature_group}:{feature_name}"

    def set(
        self,
        entity_id: str,
        feature_group: str,
        feature_name: str,
        feature_value: Any,
        feature_ts: str,
    ):
        """
        Escreve o valor mais recente de uma feature.
        Sobrescreve sempre — online store nao guarda historico.
        """
        import json
        key = self._make_key(entity_id, feature_group, feature_name)
        payload = json.dumps({
            "value":      feature_value,
            "feature_ts": feature_ts,
            "written_at": datetime.now(timezone.utc).isoformat(),
        })
        self._backend.set(key, payload)

    def get(
        self,
        entity_id: str,
        feature_group: str,
        feature_name: str,
    ) -> Optional[Any]:
        """
        Retorna o valor mais recente da feature.
        Retorna None se nao existir.
        """
        import json
        key = self._make_key(entity_id, feature_group, feature_name)
        raw = self._backend.get(key)
        if raw is None:
            return None
        return json.loads(raw)["value"]

    def get_many(
        self,
        entity_id: str,
        features: list[tuple[str, str]],
    ) -> dict[str, Any]:
        """
        Busca multiplas features de uma vez para um entity_id.
        features: lista de (feature_group, feature_name)
        Retorna dict com chave 'group__name' e valor da feature.
        Usado pelo serving API para montar o vetor de features.
        """
        result = {}
        for group, name in features:
            col = f"{group}__{name}"
            result[col] = self.get(entity_id, group, name)
        return result

    def delete(
        self,
        entity_id: str,
        feature_group: str,
        feature_name: str,
    ):
        key = self._make_key(entity_id, feature_group, feature_name)
        self._backend.delete(key)

    def count(self) -> int:
        return self._backend.size()

    def flush(self):
        """Remove tudo. Usado em testes."""
        self._backend.flush()
