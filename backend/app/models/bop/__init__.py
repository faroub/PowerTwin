"""Balance of Plant (Transformer and Switchgear) models package."""

from backend.app.models.bop.switchgear import GenericSwitchgearModel, SwitchgearConfigModel
from backend.app.models.bop.transformer import GenericTransformerModel, TransformerConfigModel

__all__ = [
    "GenericTransformerModel",
    "TransformerConfigModel",
    "GenericSwitchgearModel",
    "SwitchgearConfigModel",
]
