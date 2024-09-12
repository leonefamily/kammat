# -*- coding: utf-8 -*-
"""
Created on Tue Dec 13 17:02:13 2022

Including multiprocessing

@author: dgrishchuk
"""

import copy
import random
import inspect
import logging
import itertools
import pandas as pd
import multiprocessing
import geopandas as gpd
from typing import Union, List, Tuple, Dict, Callable, Any

from kammat.input.data.facilities import split_facilities
from kammat.input.data.types import Helpers
from kammat.input.population.utils import (
    list_to_chunks
)
from kammat.input.population.additional import (
    handle_additional_agents
    )
from kammat.input.population.agent import (
    Agent, handle_and_write_regular_agents
    )
from kammat.input.population.regular import (
    get_basic_agents_df, get_agents_list_strict, get_agents_list
    )


def order_args_for_starmap(
        fun: Callable,  # positional only
        /,
        **kwargs
        ) -> Tuple[Any]:
    """
    Order function arguments to pass into function trhough ``starmap``.
    For missing arguments their defaults are automatically used.

    Parameters
    ----------
    fun : Callable
        Function that is being called with kwargs
    **kwargs
        Keyword arguments of function to call

    Returns
    -------
    Tuple[Any]
        Ordered tuple of arguments

    """
    params = inspect.signature(fun).parameters
    argdict = {}

    for key, value in params.items():
        defval = value.default
        if defval is inspect.Parameter.empty and key not in kwargs:
            raise KeyError(
                f'"{key}" key is required by function, but is not in kwargs'
                )
        elif defval is not inspect.Parameter.empty and key not in kwargs:
            argdict[key] = defval
        else:
            argdict[key] = kwargs[key]

    return tuple(argdict.values())


def split_agents_setup_data(
        agents_df: pd.DataFrame,
        h: Helpers,
        n: int = 1
        ) -> List[Union[pd.DataFrame, Helpers]]:
    """
    Split agents dataframe and put helpers alongside to pass to multiprocessing

    Parameters
    ----------
    agents_df : pd.DataFrame
        DataFrame of raw agents (without assigned category, etc.)
    h : Helpers
        Dictionary of helper tables
    n : int, optional
        Positive integer number of parts

    Returns
    -------
    List[Union[pd.DataFrame, Helpers]]
        Ordered arguments for ``get_agents_list_strict``

    """
    idx = list_to_chunks(agents_df.index, n)
    outl = []
    for i in range(n):
        argtuple = order_args_for_starmap(
            get_agents_list_strict,  # function
            agents_df=agents_df.loc[idx[i]],
            h=h
            )
        outl.append(argtuple)
    return outl


def get_agents_list_multiproc(
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        h: Helpers,
        ncores: int = 1
        ) -> List[Agent]:
    """
    Get list of preprocessed agents. Multiprocessing works
    only on non-strict diaries. Due to multiprocessing issues on Windows, this
    function is performed in other module, than the rest of regular population

    Parameters
    ----------
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about facilities for
        every available activity.
    h : Helpers
        Dictionary of helper tables.
    ncores : int, optional
        Positive integer number of cores to use during multiprocessing.
        The default is 1 - multiprocessing is off.

    Returns
    -------
    List[Agent]
        Raw agents list (before ``self.process()``)

    """
    logging.info('Assigning categories, modes and diaries to agents')

    if h['diaries'].type == 'strict':
        agents_df = get_basic_agents_df(facilities)

        if ncores > 1:
            data = split_agents_setup_data(agents_df, h, ncores)
            pool = multiprocessing.Pool(ncores)
            pre_agents_list = pool.starmap(get_agents_list_strict, data)
            agents_list = list(itertools.chain.from_iterable(pre_agents_list))
            random.shuffle(agents_list)
            pool.close()
            pool.join()
        else:
            agents_list = get_agents_list_strict(agents_df, h)
    else:
        agents_list = get_agents_list(facilities, h)

    return agents_list


def split_agents_data(
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        agents_list: List[Agent],
        ncores: int = 1,
        **kwargs
        ) -> tuple:
    """
    Split agents list in order to pass every part into multiprocessing with
    function ``handle_and_write_regular_agents``

    Parameters
    ----------
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about facilities for
        every available activity.
    agents_list : List[Agent]
        List of preprocessed agents (before ``self.process()``)
    ncores : int, optional
        Positive integer number of cores to use during multiprocessing.
        The default is 1.
    **kwargs
        Any other keyword arguments for ``handle_and_write_regular_agents``

    Returns
    -------
    tuple
        Ordered arguments for ``handle_and_write_regular_agents``

    """

    facilities_splitted = split_facilities(facilities, ncores)
    agents_splitted = list_to_chunks(agents_list, ncores)

    outl = []

    for i in range(ncores):
        argtuple = order_args_for_starmap(
            handle_and_write_regular_agents,  # function
            facilities=facilities_splitted[i],
            agents_list=agents_splitted[i],
            process=i,
            **kwargs
            )
        outl.append(argtuple)

    return outl


def handle_regular_agents_multiproc(
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        h: Helpers,
        ncores: int = 1,
        sample: float = 1,
        **kwargs
        ) -> List[Agent]:
    """
    Handle agents using several cores and multiprocessing. In case of several
    cores, split agents and facilities (more or less) equally.

    Parameters
    ----------
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about facilities for
        every available activity.
    h : Helpers
        Dictionary of helper tables.
    xml_path : Union[str, Path], optional
        Path to save xml (MATSim-like) data of agents
    csv_path : Union[str, Path], optional
        Path to save csv data of agents
    ncores : int, optional
        Number of cores to use. The default is 1.
    sample : float, optional
        Fraction of population to draw from agents list. The default is 1.
    **kwargs
        Other keyword arguments for ``handle_and_write_regular_agents``

    Returns
    -------
    List[Agent]
        Processed regular agents

    """
    agents_list = get_agents_list_multiproc(facilities, h, ncores)
    agents_list = random.sample(agents_list, int(len(agents_list) * sample))

    if ncores > 1:
        agents_data = split_agents_data(
            facilities, agents_list, ncores=ncores, h=h, **kwargs
        )
        pool = multiprocessing.Pool(ncores)
        pre_regular_agents_list = pool.starmap(
            handle_and_write_regular_agents, agents_data
            )
        regular_agents_list = list(
            itertools.chain.from_iterable(pre_regular_agents_list)
            )
        pool.close()
        pool.join()
    else:
        facilities_copy = copy.deepcopy(facilities)
        regular_agents_list = handle_and_write_regular_agents(
            facilities_copy, agents_list, h, **kwargs
            )

    return regular_agents_list


def prepare_and_handle_agents(
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        h: Helpers,
        ncores: int = 1,
        sample: float = 1,
        **kwargs
        ) -> Dict[str, List[Agent]]:
    """
    Handle and write all agents.

    Both regular and additional population, using several cores and
    multiprocessing where possible.

    Parameters
    ----------
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about facilities for
        every available activity.
    h : Helpers
        Dictionary of helper tables.
    ncores : int, optional
        Number of cores to use. The default is 1.
    sample : float, optional
        Fraction of population to draw from agents list. The default is 1.
    **kwargs
        Other keyword arguments for ``handle_and_write_regular_agents``

    Returns
    -------
    Dict[str, List[Agent]]
        Dictionary with keys 'regular' and 'additional'

    """
    logging.info('Additional population is being processed...')
    additional_agents_list = handle_additional_agents(
        facilities, h, sample
        )
    logging.info('Regular population is being processed...')
    regular_agents_list = handle_regular_agents_multiproc(
        facilities, h, ncores, sample, **kwargs
        )
    agents_lists = {
        'regular': regular_agents_list,
        'additional': additional_agents_list,
        }

    return agents_lists
