# -*- coding: utf-8 -*-
"""
Created on Thu Jan 26 15:59:07 2023

@author: dgrishchuk
"""

import lxml
import shutil
import inspect
from pathlib import Path
from typing import Union

from kammat.defaults.constants import (
    EXAMPLE_MATSIM_VEHICLES_PATH, PathPointer
    )

ABSOLUTE_EXAMPLE_MATSIM_VEHICLES_PATH = str(
    (Path(inspect.getfile(PathPointer)).parent / EXAMPLE_MATSIM_VEHICLES_PATH).resolve()
    )


def load_modify_and_save_vehicles(
        existing_vehicles_path: Union[str, Path],
        output_vehicles_path: Union[str, Path],
        default_vehicles_path: Union[str, Path] = ABSOLUTE_EXAMPLE_MATSIM_VEHICLES_PATH,
        ):
    """
    Append default vehicles definitions to the existing vehicles file and save

    Parameters
    ----------
    existing_vehicles_path : Union[str, Path]
        Vehicles to modify.
    output_vehicles_path : Union[str, Path]
        Where to save modified vehicles.
    default_vehicles_path : Union[str, Path], optional
        Vehicles to append. The default is
        ABSOLUTE_EXAMPLE_MATSIM_VEHICLES_PATH.

    """
    defvehs = lxml.etree.parse(str(default_vehicles_path)).getroot()
    newvehs = lxml.etree.parse(str(existing_vehicles_path)).getroot()

    lasttypes = newvehs.findall('{http://www.matsim.org/files/dtd}vehicleType')
    lasindex = newvehs.index(lasttypes[-1])

    for i, child in enumerate(defvehs.getchildren(), start=1):
        newvehs.insert(lasindex + i, child)

    with open(output_vehicles_path, mode='wb') as ov:
        ov.write(
            lxml.etree.tostring(
                newvehs, pretty_print=True,
                xml_declaration=True, encoding='utf-8'
                )
            )


def copy_vehicles(
        output_vehicles_path: Union[str, Path],
        default_vehicles_path: Union[str, Path] = ABSOLUTE_EXAMPLE_MATSIM_VEHICLES_PATH
        ):
    """
    Copy default vehicles into simulation directory, if no changes are needed

    Parameters
    ----------
    output_vehicles_path : Union[str, Path]
        Where to save copied vehicles.
    default_vehicles_path : str, optional
        The default is ABSOLUTE_EXAMPLE_MATSIM_VEHICLES_PATH.

    """
    shutil.copy(default_vehicles_path, output_vehicles_path)
