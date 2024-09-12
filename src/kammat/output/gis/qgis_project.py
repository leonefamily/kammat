# -*- coding: utf-8 -*-
"""
Created on Thu Mar 16 12:59:41 2023

@author: dgrishchuk
"""

import os
import re
import sys
import math
import random
import logging
import argparse
import traceback
from pathlib import Path
from decimal import Decimal
from typing import Union, Dict, List, Optional, Callable, Any

from PyQt5.QtGui import QColor, QFont
from qgis.gui import QgsMapCanvas
from qgis.core import QgsApplication, QgsProject, QgsVectorLayer, QgsSymbol, QgsSimpleFillSymbolLayer, \
    QgsRendererCategory, QgsCategorizedSymbolRenderer, QgsVectorLayerSimpleLabeling, \
    QgsPalLayerSettings, QgsTextFormat, QgsTextBufferSettings, QgsLayerTreeGroup, QgsRendererRange, \
    QgsGraduatedSymbolRenderer, QgsClassificationPrettyBreaks

logging.basicConfig(
    format='%(asctime)s | %(levelname)s | %(name)s:%(module)s:%(lineno)d:%(funcName)s() - %(message)s',
    level=logging.INFO
)


def none_if_failed(
        fun: Callable
) -> Callable:
    def inner(
            *args,
            **kwargs
    ) -> Optional[Any]:
        try:
            return fun(*args, **kwargs)
        except:
            logging.error(traceback.format_exc())
            return

    return inner


def remove_exponent(
        d: Decimal
) -> Decimal:
    """Remove exponent. Alexander Zaitsev (azaitsev@gmail.com)."""
    return d.quantize(Decimal(1)) if d == d.to_integral() else d.normalize()


def millify(
        n: Union[int, float],
        precision: int = 0,
        drop_nulls: bool = True,
        prefixes: List[str] = None
) -> str:
    """Humanize number. Alexander Zaitsev (azaitsev@gmail.com)."""
    millnames = ['', 'k', 'M', 'B', 'T', 'P', 'E', 'Z', 'Y']
    prefixes = [] if prefixes is None else prefixes
    if prefixes:
        millnames = ['']
        millnames.extend(prefixes)
    n = float(n)
    millidx = max(
        0, min(len(millnames) - 1, int(math.floor(0 if n == 0 else math.log10(abs(n)) / 3)))
    )
    result = '{:.{precision}f}'.format(n / 10 ** (3 * millidx), precision=precision)
    if drop_nulls:
        result = remove_exponent(Decimal(result))
    return '{0}{dx}'.format(result, dx=millnames[millidx])


def prettify(
        amount: Union[int, float, str],
        separator: str = ','
) -> str:
    """
    Separate with predefined separator.

    Alexander Zaitsev (azaitsev@gmail.com).
    """
    orig = str(amount)
    new = re.sub(
        r"^(-?\d+)(\d{3})", r"\g<1>{0}\g<2>".format(separator), str(amount)
    )
    if orig == new:
        return new
    else:
        return prettify(new)


def apply_categorized_symbology(
        layer: QgsVectorLayer,
        field_name: str,
        categories_names: Dict[str, str] = None,
        categories_props: Dict[str, Dict[str, str]] = None,
        common_props: Dict[str, Union[str, int]] = None,
        default_props: Dict[str, str] = None
):
    fni = layer.fields().indexFromName(field_name)
    cats = layer.uniqueValues(fni)
    symbol = QgsSymbol.defaultSymbol(geomType=layer.geometryType())

    categories = []
    layer_style = {}

    for cat in cats:

        if categories_props is not None and cat in categories_props:
            if common_props is not None:
                layer_style.update(common_props)
            layer_style.update(categories_props[cat])
        elif default_props is not None:
            layer_style.update(default_props)

        symbol_layer = QgsSimpleFillSymbolLayer.create(properties=layer_style)

        nsymbol = symbol.clone()
        if symbol_layer is not None:
            for key, value in layer_style.items():
                if key == 'color':
                    nsymbol.setColor(QColor(value))
                elif key == 'width':
                    nsymbol.setWidth(value)
                else:
                    raise NotImplementedError('Key "{key}" is not yet supported')

        if categories_names and cat in categories_names:
            catname = categories_names[cat]
        else:
            catname = str(cat)

        category = QgsRendererCategory(cat, nsymbol, catname)
        categories.append(category)

    renderer = QgsCategorizedSymbolRenderer(field_name, categories)

    if renderer is not None:
        layer.setRenderer(renderer)
    layer.triggerRepaint()


def apply_labels(
        layer: QgsVectorLayer,
        field_name: str,
        font_name: str = 'Arial',
        font_size: int = 12,
        font_color: str = 'black',
        buffer_size: int = 0.1,
        enable: bool = True,
        is_expression: bool = False
):
    layer_settings = QgsPalLayerSettings()
    text_format = QgsTextFormat()

    text_format.setFont(QFont(font_name, font_size))
    text_format.setSize(font_size)

    buffer_settings = QgsTextBufferSettings()
    buffer_settings.setEnabled(enable)
    buffer_settings.setSize(buffer_size)
    buffer_settings.setColor(QColor(font_color))
    text_format.setBuffer(buffer_settings)

    layer_settings.setFormat(text_format)

    layer_settings.fieldName = field_name
    layer_settings.placement = QgsPalLayerSettings.Line  # ???

    layer_settings.enabled = enable

    layer_settings = QgsVectorLayerSimpleLabeling(layer_settings)
    layer_settings.isExpression = is_expression

    layer.setLabelsEnabled(enable)
    layer.setLabeling(layer_settings)
    layer.commitChanges()
    layer.triggerRepaint()


def apply_graduated_symbology(
        layer: QgsVectorLayer,
        field_name: str,
        range_data: List[Dict[str, Union[str, float]]] = None,
        min_size: float = 1.0,
        max_size: float = 10.0,
        classes: int = 10,
        color: str = "#f5c9c9"
):
    gradlist = []
    if range_data is None:
        cm = QgsClassificationPrettyBreaks()
        cm.setLabelFormat("%1 — %2")
        cm.setLabelPrecision(0)
        cm.setLabelTrimTrailingZeroes(True)
        range_data = [
            {'min': cr.lowerBound(), 'max': cr.upperBound(), 'label': cr.label()}
            for cr in cm.classes(layer, field_name, classes)
        ]
    for n, range_el in enumerate(range_data):
        symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        symbol.setColor(QColor(color))
        try:
            size = max(min_size, range_el['min'] / range_data[-1]['min'] * max_size)
        except ZeroDivisionError:
            size = min_size
        try:
            symbol.setSize(size)
        except AttributeError:
            symbol.setWidth(size)
        gradrange = QgsRendererRange(range_el['min'], range_el['max'], symbol, range_el['label'])
        gradlist.append(gradrange)

    renderer = QgsGraduatedSymbolRenderer(field_name, gradlist)
    layer.setRenderer(renderer)
    layer.triggerRepaint()


# def apply_graduated_symbology_auto_size(
#         layer: QgsVectorLayer,
#         field_name: str,
#         classes_num: int = 10,
#         color: str = "#f5c9c9"
# ):
#
#     symbol = QgsSymbol.defaultSymbol(layer.geometryType())
#     symbol.setColor(QColor(color))
#
#     cm = QgsClassificationPrettyBreaks()
#     cm.setLabelFormat("%1 — %2")
#     cm.setLabelPrecision(0)
#     cm.setLabelTrimTrailingZeroes(True)
#     rr = [QgsRendererRange(cr.lowerBound(), cr.upperBound(), symbol, cr.label())
#           for cr in cm.classes(layer, field_name, classes_num)]
#     renderer = QgsGraduatedSymbolRenderer(field_name, rr)
#     renderer.setGraduatedMethod(QgsGraduatedSymbolRenderer.GraduatedMethod.Size)
#     renderer.setClassificationMethod(cm)
#     layer.setRenderer(renderer)
#     layer.triggerRepaint()


@none_if_failed
def set_road_network_rw_differences_layers(
        project: QgsProject,
        path: Union[str, Path],
        group: QgsLayerTreeGroup = None
) -> QgsVectorLayer:
    layer = QgsVectorLayer(path, "Differences", "ogr")
    layers = []
    if not layer.isValid():
        raise RuntimeError(f'Layer {path} is invalid')

    for mode in ['car', 'truck']:
        nlayer = layer.clone()
        nlayer.setName(mode)
        if group is not None:
            project.addMapLayer(nlayer, False)
            group.addLayer(nlayer)
        else:
            project.addMapLayer(nlayer)

        dcat_cat_props = {
            'ok': {'color': 'green'},
            'model-': {'color': 'blue'},
            'model+': {'color': 'red'}
        }
        dcat_cat_names = {
            'ok': 'OK: ±25%',
            'model-': 'Less: -25% and lower',
            'model+': 'More: +25% and higher'
        }
        dcat_comm_props = {'width': 2}
        dcat_def_props = {'color': 'lightgray'}

        apply_categorized_symbology(
            layer=nlayer,
            field_name=f'dcat_{mode}',
            categories_names=dcat_cat_names,
            categories_props=dcat_cat_props,
            common_props=dcat_comm_props,
            default_props=dcat_def_props
        )
        apply_labels(
            layer=nlayer,
            field_name=f'to_string(round("{mode}" / 1000, 1)) || \' / \' || to_string(round("{mode}_c" / 1000, 1))',
            is_expression=True
        )
        nlayer.updateExtents()
        project.layerTreeRoot().findLayer(nlayer).setItemVisibilityChecked(False)
        layers.append(nlayer)
    return layers


def get_random_color(
) -> str:
    """
    Generate random color in hexadecimal format (#XXXXXX).

    Returns
    -------
    str

    """
    a = str(hex(random.randrange(0, 255)))[-2:]
    b = str(hex(random.randrange(0, 255)))[-2:]
    c = str(hex(random.randrange(0, 255)))[-2:]
    color = f'#{a}{b}{c}'
    return color


@none_if_failed
def set_input_facilities_layers(
        project: QgsProject,
        path: Union[str, Path],
        fields_groups: Dict[str, QgsLayerTreeGroup]
) -> List[QgsVectorLayer]:
    layer = QgsVectorLayer(path, "Facilities' visitors", "ogr")
    layers = []
    fni = layer.fields().indexFromName('activity')
    acts = layer.uniqueValues(fni)
    for act in acts:
        logging.info(f'Act "{act}"')
        for field_name, group in fields_groups.items():
            logging.info(f'Group "{group.name()}"')
            nlayer = layer.clone()
            nlayer.setSubsetString(f'"activity" = \'{act}\'')
            nlayer.setName(act)
            if group is not None:
                project.addMapLayer(nlayer, False)
                group.addLayer(nlayer)
            else:
                project.addMapLayer(nlayer)
            apply_graduated_symbology(
                layer=nlayer,
                field_name=field_name,
                color=get_random_color(),
            )
            project.layerTreeRoot().findLayer(nlayer).setItemVisibilityChecked(False)
            layers.append(nlayer)

    return layers


@none_if_failed
def set_basic_layer(
        project: QgsProject,
        name: str,
        path: Union[str, Path],
        group: QgsLayerTreeGroup = None
):
    layer = QgsVectorLayer(path, name, "ogr")
    if group is not None:
        project.addMapLayer(layer, False)
        group.addLayer(layer)
    else:
        project.addMapLayer(layer)
    return layer


def create_group(
        name: str,
        parent: QgsLayerTreeGroup,
        expanded: bool = False,
        visible: bool = False
) -> QgsLayerTreeGroup:
    group = parent.addGroup(name)
    group.setItemVisibilityChecked(visible)
    group.setExpanded(expanded)
    return group


@none_if_failed
def set_output_road_network_counts_layers(
        project: QgsProject,
        path: Union[str, Path],
        group: QgsLayerTreeGroup
) -> List[QgsVectorLayer]:
    layer = QgsVectorLayer(path, "Counts", "ogr")
    layers = []
    for mode in ['car', 'truck']:
        nlayer = layer.clone()
        nlayer.setName(mode)
        if group is not None:
            project.addMapLayer(nlayer, False)
            group.addLayer(nlayer)
        else:
            project.addMapLayer(nlayer)
        apply_graduated_symbology(
            layer=nlayer,
            field_name=mode,
            color=get_random_color(),
            min_size=0.5,
            max_size=5
        )
        project.layerTreeRoot().findLayer(nlayer).setItemVisibilityChecked(False)
        apply_labels(
            layer=nlayer,
            field_name=f'to_string(round("{mode}" / 1000, 1))',
            is_expression=True
        )
        layers.append(nlayer)
    return layers


@none_if_failed
def set_output_pt_network_counts_layer(
        project: QgsProject,
        path: Union[str, Path],
        group: QgsLayerTreeGroup
) -> QgsVectorLayer:
    layer = QgsVectorLayer(path, "Links", "ogr")
    if group is not None:
        project.addMapLayer(layer, False)
        group.addLayer(layer)
    else:
        project.addMapLayer(layer)
    apply_graduated_symbology(
        layer=layer,
        field_name='count',
        color=get_random_color(),
        min_size=0.5,
        max_size=5
    )
    project.layerTreeRoot().findLayer(layer).setItemVisibilityChecked(False)
    apply_labels(
        layer=layer,
        field_name='to_string(round("count" / 1000, 1))',
        is_expression=True
    )
    return layer


@none_if_failed
def set_output_pt_stops_counts_layer(
        project: QgsProject,
        path: Union[str, Path],
        group: QgsLayerTreeGroup
) -> List[QgsVectorLayer]:
    layer = QgsVectorLayer(path, "Stops", "ogr")
    if group is not None:
        project.addMapLayer(layer, False)
        group.addLayer(layer)
    else:
        project.addMapLayer(layer)
    apply_graduated_symbology(
        layer=layer,
        field_name='"entered" + "left"',
        color=get_random_color(),
        min_size=1,
        max_size=10
    )
    project.layerTreeRoot().findLayer(layer).setItemVisibilityChecked(False)
    apply_labels(
        layer=layer,
        field_name='"name" || \' | \' || to_string(round(("entered" + "left") / 1000, 1))',
        is_expression=True
    )
    return layer


@none_if_failed
def set_cordons_poly_layer(
        project: QgsProject,
        path: Union[str, Path],
        group: QgsLayerTreeGroup
) -> List[QgsVectorLayer]:
    layer = QgsVectorLayer(path, "Cordons", "ogr")
    layers = []
    for mode in ['car', 'truck']:
        nlayer = layer.clone()
        nlayer.setName(mode)
        if group is not None:
            project.addMapLayer(nlayer, False)
            group.addLayer(nlayer)
        else:
            project.addMapLayer(nlayer)

        fni = nlayer.fields().indexFromName(mode)
        cats = nlayer.uniqueValues(fni)
        cat_props = {cat: {'color': get_random_color()} for cat in cats}
        cat_names = {cat: millify(cat, precision=3) for cat in cats}
        def_props = {'color': 'lightgray'}

        apply_categorized_symbology(
            layer=nlayer,
            field_name=mode,
            categories_names=cat_names,
            categories_props=cat_props,
            default_props=def_props
        )
        project.layerTreeRoot().findLayer(nlayer).setItemVisibilityChecked(False)
        apply_labels(
            layer=nlayer,
            field_name=mode,
            is_expression=True
        )
        layers.append(nlayer)
    return layers


def parse_args(
        args_list: List[str] = None
) -> argparse.Namespace:
    if args_list is None:
        args_list = sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument('-pp', '--project-path', required=True)
    # input
    parser.add_argument('-if', '--input-facilities')
    parser.add_argument('-ie', '--input-edges')
    parser.add_argument('-in', '--input-nodes')
    # output
    parser.add_argument('-orc', '--output-road-counts')
    parser.add_argument('-opc', '--output-pt-counts')
    parser.add_argument('-ops', '--output-pt-stops')
    parser.add_argument('-ocs', '--output-cordons-stats')
    parser.add_argument('-ovs', '--output-volumes-stats')
    # comparison
    parser.add_argument('-crwrd', '--comparison-rw-road-diffs')
    parser.add_argument('-crwid', '--comparison-rw-road-intersection-diffs')
    parser.add_argument('-crwpd', '--comparison-rw-pt-diffs')
    parser.add_argument('-cmrd', '--comparison-model-road-diffs')
    parser.add_argument('-cmpd', '--comparison-model-pt-diffs')
    parser.add_argument('-cmpsd', '--comparison-model-pt-stops-diffs')

    args = parser.parse_args(args_list)
    return args


def create_project(
        project_path: Union[str, Path] = None,
        input_facilities_path: Union[str, Path] = None,
        input_edges_path: Union[str, Path] = None,
        input_nodes_path: Union[str, Path] = None,
        output_road_counts_path: Union[str, Path] = None,
        output_pt_counts_path: Union[str, Path] = None,
        output_pt_stops_path: Union[str, Path] = None,
        output_cordons_stats_path: Union[str, Path] = None,
        output_volumes_stats_path: Union[str, Path] = None,
        comparison_rw_road_diffs_path: Union[str, Path] = None,
        comparison_rw_road_intersection_diffs_path: Union[str, Path] = None,
        comparison_rw_pt_diffs_path: Union[str, Path] = None,
        comparison_model_road_diffs_path: Union[str, Path] = None,
        comparison_model_pt_diffs_path: Union[str, Path] = None,
        comparison_model_pt_stops_diffs_path: Union[str, Path] = None
) -> Optional[QgsProject]:
    # app instance created
    qgs = QgsApplication([], False)
    qgs.initQgis()
    project = QgsProject.instance()
    root = QgsProject.instance().layerTreeRoot()
    input_group = create_group('Input', root)
    input_roads_group = create_group('Road network', input_group)
    input_fac_group = create_group('Facilities\' visitors', input_group)
    input_own_fac_group = create_group('Own', input_fac_group)
    input_foster_fac_group = create_group('Foster', input_fac_group)
    input_all_fac_group = create_group('All', input_fac_group)

    output_group = create_group('Output', root)
    output_roads_group = create_group('Road network counts', output_group)
    output_cordons_group = create_group('Road cordon counts', output_group)
    output_volumes_group = create_group('Road cordon volumes', output_group)
    output_pt_group = create_group('PT network counts', output_group)

    comparison_group = create_group('Comparison', root)
    rw_comp_group = create_group('Real world', comparison_group)
    m_comp_group = create_group('Previous model', comparison_group)

    layers_list = []
    # layers added
    if output_cordons_stats_path is not None:
        logging.info('Setting cordon counts')
        cordons_stats_layers = set_cordons_poly_layer(
            project=project,
            path=output_cordons_stats_path,
            group=output_cordons_group
        )
        if cordons_stats_layers is not None:
            layers_list.extend(cordons_stats_layers)
    if output_volumes_stats_path is not None:
        logging.info('Setting cordon volumes')
        volume_stats_layers = set_cordons_poly_layer(
            project=project,
            path=output_volumes_stats_path,
            group=output_volumes_group
        )
        if volume_stats_layers is not None:
            layers_list.extend(volume_stats_layers)
    if input_edges_path is not None:
        logging.info('Setting input edges')
        edges_layer = set_basic_layer(
            project=project,
            name='Road network edges',
            path=input_edges_path,
            group=input_roads_group
        )
        if edges_layer is not None:
            layers_list.append(edges_layer)
    if input_nodes_path is not None:
        logging.info('Setting input nodes')
        nodes_layer = set_basic_layer(
            project=project,
            name='Road network nodes',
            path=input_nodes_path,
            group=input_roads_group
        )
        if nodes_layer is not None:
            layers_list.append(nodes_layer)
    if input_facilities_path is not None:
        logging.info('Setting input facilities')
        facilities_layers = set_input_facilities_layers(
            project=project,
            fields_groups={
                'count_own': input_own_fac_group,
                'count_nown': input_foster_fac_group,
                'count_all': input_all_fac_group
            },
            path=input_facilities_path
        )
        if facilities_layers is not None:
            layers_list.extend(facilities_layers)
    if output_road_counts_path is not None:
        output_road_counts_layers = set_output_road_network_counts_layers(
            project=project,
            group=output_roads_group,
            path=output_road_counts_path
        )
        if output_road_counts_layers is not None:
            layers_list.extend(output_road_counts_layers)
    if output_pt_stops_path is not None:
        output_pt_stops_layer = set_output_pt_stops_counts_layer(
            project=project,
            group=output_pt_group,
            path=output_pt_stops_path
        )
        if output_pt_stops_layer is not None:
            layers_list.append(output_pt_stops_layer)
    if output_pt_counts_path is not None:
        output_pt_counts_layer = set_output_pt_network_counts_layer(
            project=project,
            group=output_pt_group,
            path=output_pt_counts_path
        )
        if output_pt_counts_layer is not None:
            layers_list.append(output_pt_counts_layer)
    if comparison_rw_road_diffs_path is not None:
        rw_road_diff_layers = set_road_network_rw_differences_layers(
            project=project,
            group=rw_comp_group,
            path=comparison_rw_road_diffs_path
        )
        if rw_road_diff_layers is not None:
            layers_list.extend(rw_road_diff_layers)
    if comparison_rw_road_intersection_diffs_path is not None:
        rw_road_int_diff_layers = set_road_network_rw_differences_layers(
            project=project,
            group=rw_comp_group,
            path=comparison_rw_road_intersection_diffs_path
        )
        if rw_road_int_diff_layers is not None:
            layers_list.extend(rw_road_int_diff_layers)

    canvas = QgsMapCanvas()
    canvas.setExtent(layers_list[0].extent())
    canvas.setLayers(layers_list)
    canvas.refreshAllLayers()

    if project_path is None:
        qgs.exitQgis()
        return project
    project.write(project_path)
    qgs.exitQgis()


if __name__ == '__main__':
    args = parse_args()
    create_project(
        project_path=args.project_path,
        input_facilities_path=args.input_facilities,
        input_edges_path=args.input_edges,
        input_nodes_path=args.input_nodes,
        output_road_counts_path=args.output_road_counts,
        output_pt_counts_path=args.output_pt_counts,
        output_pt_stops_path=args.output_pt_stops,
        output_cordons_stats_path=args.output_cordons_stats,
        output_volumes_stats_path=args.output_volumes_stats,
        comparison_rw_road_diffs_path=args.comparison_rw_road_diffs,
        comparison_rw_road_intersection_diffs_path=args.comparison_rw_road_intersection_diffs,
        comparison_rw_pt_diffs_path=args.comparison_rw_pt_diffs,
        comparison_model_road_diffs_path=args.comparison_model_road_diffs,
        comparison_model_pt_diffs_path=args.comparison_model_pt_diffs,
        comparison_model_pt_stops_diffs_path=args.comparison_model_pt_stops_diffs
    )
