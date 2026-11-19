"""Switchable model layers (berths, tank farm, crude units, custom).

Importing this package registers the built-in layer types. To add a type,
subclass :class:`Layer`, decorate it with :func:`register` and import its
module here.
"""
from .base import (CRUDE_RECEIPT, CRUDE_SUPPLY, GRADES, LAYER_TYPES, PERIOD_H, PERIODS, PORTS, Column, Context,
                   Field, Fragment, Grid, Layer, LayerInfo, Link, Port, Table, active_layers, compose,
                   default_layers, describe, has_layers, instantiate, layer_class, new_layer, normalize_layers,
                   register, register_port)
from . import berth, cdu, custom, tanks  # noqa: F401  (register the built-in types)

__all__ = [
    "CRUDE_RECEIPT", "CRUDE_SUPPLY", "GRADES", "LAYER_TYPES", "PERIOD_H", "PERIODS", "PORTS", "Column",
    "Context", "Field", "Fragment", "Grid", "Layer", "LayerInfo", "Link", "Port", "Table", "active_layers",
    "compose", "default_layers", "describe", "has_layers", "instantiate", "layer_class", "new_layer",
    "normalize_layers", "register", "register_port",
]
