"""Render service package: scene stills and the builtin style and template modules.

Builtin modules live here because services may only reach contracts and their
own package; a manifest's ``renderer.module`` names one of these entries.
"""

from app.services.render.layers import BUILTIN_TEMPLATE_MODULES, BuiltinLayerDrawer
from app.services.render.pixel import BUILTIN_STYLE_MODULE, PART_LAYERS, PixelPartsBuilder
from app.services.render.service import RenderService, create

BUILTIN_PARTS_BUILDERS = {BUILTIN_STYLE_MODULE: PixelPartsBuilder}
BUILTIN_LAYER_DRAWERS = {module: BuiltinLayerDrawer for module in BUILTIN_TEMPLATE_MODULES}

__all__ = [
    "BUILTIN_LAYER_DRAWERS",
    "BUILTIN_PARTS_BUILDERS",
    "PART_LAYERS",
    "BuiltinLayerDrawer",
    "PixelPartsBuilder",
    "RenderService",
    "create",
]
