"""
registry.py — Fonte de verdade de todas as features.
Le o features.yaml e disponibiliza contratos para o sistema.
Qualquer modulo que precisa saber o que e uma feature
pergunta ao Registry — nunca le o YAML diretamente.
"""
import os
from typing import Optional

import yaml

from .feature_definition import FeatureDefinition, FeatureGroup


class FeatureRegistry:

    def __init__(self, config_path: str = "config/features.yaml"):
        self.config_path = config_path
        self._groups: dict[str, FeatureGroup] = {}
        self._mtime: float = 0
        self._load()

    def _load(self):
        """Carrega ou recarrega o YAML se o arquivo mudou."""
        mtime = os.path.getmtime(self.config_path)
        if mtime == self._mtime:
            return

        with open(self.config_path) as f:
            data = yaml.safe_load(f)

        self._groups = {}
        for group_name, group_data in data["feature_groups"].items():
            features = [
                FeatureDefinition(**feat)
                for feat in group_data["features"]
            ]
            self._groups[group_name] = FeatureGroup(
                name=group_name,
                description=group_data["description"],
                entity=group_data["entity"],
                features=features,
            )
        self._mtime = mtime

    def get_group(self, group_name: str) -> Optional[FeatureGroup]:
        """Retorna um FeatureGroup completo ou None se nao existir."""
        self._load()
        return self._groups.get(group_name)

    def get_feature(
        self, group_name: str, feature_name: str
    ) -> Optional[FeatureDefinition]:
        """Retorna uma FeatureDefinition especifica ou None."""
        group = self.get_group(group_name)
        if group is None:
            return None
        return group.get_feature(feature_name)

    def list_groups(self) -> list[str]:
        """Lista todos os grupos registrados."""
        self._load()
        return list(self._groups.keys())

    def list_features(self, group_name: str) -> list[str]:
        """Lista todas as features de um grupo."""
        group = self.get_group(group_name)
        if group is None:
            return []
        return [f.name for f in group.features]
