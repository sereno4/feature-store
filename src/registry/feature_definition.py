"""
feature_definition.py — Contrato Pydantic de cada feature.
Traduz o features.yaml para objetos Python com validacao.
Toda feature tem tipo, range e regras antes de ser armazenada.
"""
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, Field, model_validator


class FeatureDefinition(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    dtype: Literal["int", "float", "string", "bool"]
    description: str = Field(..., min_length=1)
    allow_null: bool = False

    # para int e float
    min_value: Optional[float] = None
    max_value: Optional[float] = None

    # para string
    allowed_values: Optional[List[str]] = None

    @model_validator(mode="after")
    def validate_range_consistency(self) -> "FeatureDefinition":
        if self.min_value is not None and self.max_value is not None:
            if self.min_value > self.max_value:
                raise ValueError(
                    f"min_value ({self.min_value}) nao pode ser "
                    f"maior que max_value ({self.max_value})"
                )
        return self

    def validate_value(self, value: Any) -> tuple[bool, Optional[str]]:
        """
        Valida um valor contra o contrato desta feature.
        Retorna (True, None) se valido.
        Retorna (False, motivo) se invalido.
        """
        # nulo
        if value is None:
            if self.allow_null:
                return True, None
            return False, f"feature '{self.name}' nao permite nulo"

        # tipo
        type_map = {"int": int, "float": (int, float), "string": str, "bool": bool}
        expected = type_map[self.dtype]
        if not isinstance(value, expected):
            return False, (
                f"feature '{self.name}' esperava {self.dtype}, "
                f"recebeu {type(value).__name__}"
            )

        # range numerico
        if self.min_value is not None and value < self.min_value:
            return False, (
                f"feature '{self.name}' valor {value} "
                f"abaixo do minimo {self.min_value}"
            )
        if self.max_value is not None and value > self.max_value:
            return False, (
                f"feature '{self.name}' valor {value} "
                f"acima do maximo {self.max_value}"
            )

        # valores permitidos
        if self.allowed_values is not None and value not in self.allowed_values:
            return False, (
                f"feature '{self.name}' valor '{value}' "
                f"nao esta em {self.allowed_values}"
            )

        return True, None


class FeatureGroup(BaseModel):
    name: str
    description: str
    entity: str                          # ex: "customer_id"
    features: List[FeatureDefinition]

    def get_feature(self, name: str) -> Optional[FeatureDefinition]:
        for f in self.features:
            if f.name == name:
                return f
        return None
