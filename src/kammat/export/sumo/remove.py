# -*- coding: utf-8 -*-
"""
Created on Mon Jan 13 16:35:56 2025

@author: dgrishchuk
"""
import sys

import argparse
import warnings
from lxml import etree
from pathlib import Path
from typing import Union, List, Literal, Optional

from kammat.export.sumo.utils import write_element_tree


ALLOWED_ELEMENT_TYPES = ['junction', 'edge']
ALLOWED_PARENT_TYPES = ['trip', 'vehicle', 'personTrip']
VIA_ARGUMENT_NAME = {
    'junction': 'viaJunctions',
    'edge': 'via'
}


def split_elements(
        els_str: str,
        sep: str = ';'
) -> List[str]:
    if els_str:
        return els_str.split(sep)


def parse_args(
        args_list: Optional[List[str]] = None
):
    if args_list is None:
        args_list = sys.argv[1:]

    parser = argparse.ArgumentParser(
        description='Remove a sequence from viaJunction attributes in an XML file.'
    )
    group = parser.add_mutually_exclusive_group(required=True)
    parser.add_argument(
        '-i', '--input-file',
        help='Path to the input XML file'
    )
    parser.add_argument(
        '-o', '--output-file',
        help='Path to the output XML file'
    )
    group.add_argument(
        '-l', '--elements-list', type=split_elements,
        help='The elements to remove from viaJunction attributes separated by ;'
    )
    group.add_argument(
        '-a', '--all', action='store_true',
        help='Removes all viaJunction or via attributes'
    )
    group.add_argument(
        '-s', '--selection-file',
        help='File with lines like junction:XXX from netedit selection save'
    )
    parser.add_argument(
        '-e', '--element-type',
        help='Type of entities that vehicle/trip depends on',
        default='junction',
        choices=ALLOWED_ELEMENT_TYPES
    )
    parser.add_argument(
        '-p', '--parent-type',
        help='Parent tag to interact with',
        default='trip',
        choices=ALLOWED_PARENT_TYPES
    )
    args = parser.parse_args(args_list)
    return args


def remove_via(
        element_tree: etree.ElementTree,
        via_elements_list: List[str],
        via_elements_type: Literal['junction', 'edge'] = 'junction',
        parent_elements_type: Literal['vehicle', 'trip', 'personTrip'] = 'trip'
):
    via_elements_name = VIA_ARGUMENT_NAME[via_elements_type]
    changes_num = 0
    for trip in element_tree.findall(f'//{parent_elements_type}'):
        try:
            old_string = trip.attrib[via_elements_name]
            old_elements_list = old_string.split(' ')
            new_elements_list = [
                el for el in old_elements_list if
                el not in via_elements_list
            ]
            if len(old_elements_list) != len(new_elements_list):
                if len(new_elements_list) != 0:
                    new_string = ' '.join(new_elements_list)
                    trip.attrib[via_elements_name] = new_string
                else:
                    del trip.attrib[via_elements_name]
                changes_num += 1
        except KeyError:
            continue
    if changes_num == 0:
        warnings.warn(
            'Not a single element was removed in any attribute named '
            f'"{via_elements_name}" within parents {parent_elements_type}'
        )


def remove_all_via(
        element_tree: etree.ElementTree,
        via_elements_type: Literal['junction', 'edge'] = 'junction',
        parent_elements_type: Literal['vehicle', 'trip', 'personTrip'] = 'trip'
):
    via_elements_name = VIA_ARGUMENT_NAME[via_elements_type]
    changes_num = 0
    for trip in element_tree.findall(f'//{parent_elements_type}'):
        try:
            del trip.attrib[via_elements_name]
            changes_num += 1
        except KeyError:
            continue
    if changes_num == 0:
        warnings.warn(
            f'Not a single attribute "{via_elements_name}" '
            f'was removed within parents {parent_elements_type}'
        )


def handle_remove_via(
        input_path: Union[str, Path],
        output_path: Union[str, Path],
        selection_path: Optional[Union[str, Path]] = None,
        remove_all: bool = False,
        elements_list: Optional[List[str]] = None,
        element_type: Literal['junction', 'edge'] = 'junction',
        parent_type: Literal['vehicle', 'trip', 'personTrip'] = 'trip'
):
    tree = etree.parse(input_path)
    if remove_all:
        remove_all_via(
            element_tree=tree,
            via_elements_type=element_type,
            parent_elements_type=parent_type
        )
    elif elements_list is None:
        elements_list = parse_elements(
            selection_path=selection_path,
            kind=element_type
        )
        remove_via(
            element_tree=tree,
            via_elements_list=elements_list,
            via_elements_type=element_type
        )
    write_element_tree(tree=tree, path=output_path)


def parse_elements(
        selection_path: Union[str, Path],
        kind: Literal['edge', 'junction'] = 'junction'
) -> List[str]:
    elements_list = []
    with open(selection_path, mode='r', encoding='utf-8') as sp:
        for line in sp:
            spline = line.split(':')
            if spline[0].startswith(kind):
                elements_list.append(spline[-1].strip())
    return elements_list


if __name__ == '__main__':
    args = parse_args()
    handle_remove_via(
        input_path=args.input_file,
        output_path=args.output_file,
        elements_list=args.elements_list,
        element_type=args.element_type,
        selection_path=args.selection_file
    )
