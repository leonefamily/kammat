from qgis._core import QgsRenderContext, QgsLineSymbol, QgsLineSymbolLayer, QgsUnitTypes
from qgis.core import QgsMapSettings
from qgis.core import QgsGraduatedSymbolRenderer
from qgis.utils import iface

OFFSET = 5
layer = iface.activeLayer()
layer.startEditing()
renderer = layer.renderer()
if isinstance(renderer, QgsGraduatedSymbolRenderer):
    map_settings = QgsMapSettings()
    map_settings.setLayers([layer])
    render_context = QgsRenderContext.fromMapSettings(map_settings)
    symbols = renderer.symbols(render_context)

    for symbol in symbols:
        if isinstance(symbol, QgsLineSymbol):
            for slayer in symbol.symbolLayers():
                if isinstance(slayer, QgsLineSymbolLayer):
                    slayer.setOffset(OFFSET)
                    slayer.setOffsetUnit(QgsUnitTypes.RenderMapUnits)
        else:
            symbol.setOffset(OFFSET)

    layer.triggerRepaint()
    layer.commitChanges()
