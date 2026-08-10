# -*- coding: utf-8 -*-
"""
Created on Tue Jan 31 09:44:45 2023

@author: dgrishchuk
"""

import os
import lxml
import math
import platform
import subprocess
import lxml.etree
from pathlib import Path
from typing import Dict, Sequence, Tuple, Union

from kammat.model.matsim import get_matsim_runnable_class, get_matsim_version

SIZE_NAME: Tuple[str] = ('b', 'k', 'm', 'g', 't')


def convert_size(
        size_bytes: Union[int, float]
        ) -> str:
    """
    Get human (and java) readable string of file size.

    Parameters
    ----------
    size_bytes : int
        File size in bytes

    Returns
    -------
    str
        Digit with appended size unit

    """
    if size_bytes == 0:
        return "0b"
    magnitude = int(math.floor(math.log(size_bytes, 1024)))
    if magnitude > 4:
        raise NotImplementedError('Too big size magnitude')

    close_big = math.pow(1024, magnitude)

    out = round(size_bytes / close_big, 2)

    if magnitude > 0:
        out = round(out * 1024)
        magnitude -= 1
    return f'{out}{SIZE_NAME[magnitude]}'


def get_ram_size() -> float:
    """
    Get RAM on Windows and Linux.

    Returns
    -------
    float
        Installed RAM in gigabytes

    """
    memory = 0
    system = platform.system().lower()
    if system == 'windows':
        sticks = os.popen('wmic memorychip get capacity').read().split()
        for module in sticks:
            if module.isdigit():
                memory += int(module)
    elif system == 'linux':
        memory = os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')
    else:
        raise NotImplementedError(f'{system} is not supported')
    return memory


def suggest_matsim_ram_limit(
        max_fraction: float = 0.7,
        min_free_ram: float = 2
        ) -> str:
    """
    Give MATSim process as much memory, as it's available.

    Without restricting other processes too much.

    Parameters
    ----------
    max_fraction : float, optional
        Maximum fraction to dedicate for MATSim process. The default is 0.7.
    min_free_ram : float, optional
        Minimum value to keep free from MATSim process in GB. The default is 2.

    Returns
    -------
    str

    """
    got_ram = get_ram_size()
    suggested = max_fraction * got_ram
    free = got_ram - suggested
    if free < min_free_ram * 1024 ** 3:
        return convert_size(free)
    return convert_size(suggested)


def run_subprocess(
        command: Sequence[str]
        ) -> int:
    """
    Run subprocess, fail if any error encountered.

    Parameters
    ----------
    command : Sequence[str]
        Literal argument vector. String commands are prohibited.

    """
    if isinstance(command, (str, bytes)):
        raise TypeError('run_subprocess requires an argument vector')
    argv = tuple(command)
    if not argv or any(not isinstance(item, str) or not item or '\x00' in item
                       for item in argv):
        raise ValueError('run_subprocess arguments must be non-empty strings')
    completed = subprocess.run(argv, shell=False, check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            'child process returned error code {0}'.format(completed.returncode)
        )
    return completed.returncode


def modify_config(
        replacements: Dict[str, str],
        tree: lxml.etree.ElementTree
        ):
    """
    Iterate over config tree parameters and replace suitable.

    Parameters
    ----------
    replacements : Dict[str, str]
        Dictionary pairs with parameter name and new value.
    tree : lxml.etree.ElementTree
        Config tree to replace in.

    """
    replacements = {k: str(v) for k, v in replacements.items()}

    for element in tree.iter():
        parameter = element.get('name')
        if parameter in replacements:
            element.set('value', replacements[parameter])
