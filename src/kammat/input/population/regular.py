# -*- coding: utf-8 -*-
"""
Created on Mon Dec 19 17:47:05 2022

@author: dgrishchuk
"""

import random
import logging
import numpy as np
import pandas as pd
import geopandas as gpd
from datetime import timedelta as td
from typing import Union, List, Dict, Literal


from kammat.defaults.constants import (
    SPATIAL_LEVELS, AGENTS_COLUMNS
    )
from kammat.input.population.agent import Agent
from kammat.defaults.variables import Variables
from kammat.input.population.utils import scale_to_percent
from kammat.input.data.types import (
    Categories, Staying, Diaries, ModalSplit, Helpers
)

v = Variables()


def set_categories(
        agents_df: Union[pd.DataFrame, gpd.GeoDataFrame],
        categs_df: Categories,
        all_zero_behavior: Literal['skip', 'equal', 'mean', 'random', 'error'] = 'mean'
        ):
    """
    Creates `category` column in ``agents_df`` and assigns categories
    based on probabilities per spatial units in ``categories_df``.

    Parameters
    ----------
    agents_df : Union[pd.DataFrame, gpd.GeoDataFrame]
        Agents DataFrame, derived from homes facilities
    categs_df : Categories
        Categories DataFrame from helpers
    all_zero_behavior : str, optional
        Whan happens, if all zero probabilities are encountered in categories:
            `skip` : spatial unit is skipped, no agents are generated in it;
            `equal` : all probabilities in spatial unit are equal, and are
                      assigned the value of 1 divided by number of categories;
            `mean` : probabilities are taken from whole categories dataset's
                     mean values for every present category;
            `random` : probabilities are drawn randomly in range from 0 to 1;
            `error` : raises RuntimeError.
        Default is `mean`.

    Raises
    ------
    RuntimeError
        If some category is missing in categories

    """
    # assign category to every agent, based on home zone code
    prec = categs_df.precision
    categories = [c for c in categs_df.columns if c not in SPATIAL_LEVELS]
    if all_zero_behavior == 'mean':
        mean_vals = categs_df[categories].mean()
        mean_probs = mean_vals / mean_vals.sum()
    for zone in agents_df[prec].unique():
        try:
            probs = categs_df[categs_df[prec] == zone][categories].iloc[0]
            if (probs == 0).all():
                logging.warn(
                    f'{prec.capitalize()} {zone} has 0 in all categories probs'
                    )
                if all_zero_behavior == 'skip':
                    logging.warn(f'Skipping {prec} {zone}')
                    continue
                elif all_zero_behavior == 'equal':
                    logging.warn(f'Set equal probabilities in {prec} {zone}')
                    probs = [1 / len(probs) for prob in probs]
                elif all_zero_behavior == 'mean':
                    logging.warn(f'Set mean probabilities in {prec} {zone}')
                    probs = mean_probs
                elif all_zero_behavior == 'random':
                    logging.warn(f'Set random probabilities in {prec} {zone}')
                    rand_vals = np.random.uniform(size=len(categories))
                    probs = rand_vals / rand_vals.sum()
                elif all_zero_behavior == 'error':
                    raise RuntimeError(
                        f'Failing on {prec.capitalize()} {zone} because of 0s'
                        )
                else:
                    raise RuntimeError(
                        'Wrong all_zero_behavior defined on function call'
                        )
            agents_df.loc[agents_df[prec] == zone, 'category'] = (
                np.random.choice(
                    # categories to choose from
                    categories,
                    # length of values to generate
                    len(agents_df.loc[agents_df[prec] == zone]),
                    # category probability
                    p=probs
                )
            )
        except IndexError as e:
            raise RuntimeError(
                f'{prec.capitalize()} {zone} is not in categories'
                ) from e
    logging.info('Setting categories done')


def set_modes(
        agents_df: Union[pd.DataFrame, gpd.GeoDataFrame],
        modal_split: ModalSplit
        ):
    """
    Creates `modes` column in ``agents_df`` and assigns initial modes
    based on modes per zones and categories in ``modes_df``.

    Parameters
    ----------
    agents_df : Union[pd.DataFrame, gpd.GeoDataFrame]
        Agents DataFrame, derived from homes facilities
    modal_split : ModalSplit
        Modes DataFrame from helpers

    """
    if modal_split.target_precision is not None:
        logging.info('Skipping initial means of transport, _target found')
        agents_df['modes'] = None
        return
    prec = modal_split.precision
    modes = [c for c in modal_split.columns if c not in
             SPATIAL_LEVELS + ('category',) and '_target' not in c]
    for zone in agents_df[prec].unique():
        for cat in agents_df['category'].unique():
            cond = (agents_df[prec] == zone) & (agents_df['category'] == cat)
            agents_df.loc[cond, 'modes'] = (
                                 np.random.choice(
                                     # modes to choose of
                                     modes,
                                     # length of values to generate
                                     len(agents_df[cond]),
                                     # modes probability
                                     p=modal_split[cond][modes].iloc[0]
                                 ))
    logging.info('Setting initial means of transport done')


def drop_staying(
        agents_df: Union[pd.DataFrame, gpd.GeoDataFrame],
        staying: Staying
        ):
    """
    Drop agents that are staying from ``agents_df`` based on probabilities
    from ``staying`` table

    Parameters
    ----------
    agents_df : Union[pd.DataFrame, gpd.GeoDataFrame]
        Agents DataFrame, derived from homes facilities
    staying : Staying
        Staying DataFrame from helpers

    """
    prec = staying.precision
    categs = [c for c in staying.columns if c not in SPATIAL_LEVELS]
    for i, row in staying.iterrows():
        for categ in categs:
            idx = agents_df[(agents_df[prec] == row[prec]) &
                            (agents_df['category'] == categ)].index.tolist()
            random.shuffle(idx)
            how_many = int(len(idx) * row[categ])
            agents_df.drop(random.sample(idx, how_many), inplace=True)


def assign_diaries(
        agents_df: Union[pd.DataFrame, gpd.GeoDataFrame],
        diaries: Diaries
        ):
    """
    Randomly assigns strict diaries index into `diary`
    column of ``agents_df`` based on `category` column
    and diaries' spatial precision. Only changes ``agents_df``

    Parameters
    ----------
    agents_df : Union[pd.DataFrame, gpd.GeoDataFrame]
        Table of agents with assigned categories
    diaries : pd.DataFrame
        Table of strict diaries

    """

    prec = diaries.precision
    categs = diaries['category'].dropna().unique()
    zones = diaries[prec].dropna().unique()
    weight_exists = any(c == 'weight' for c in diaries.columns)

    from collections import defaultdict, Counter
    comparison = {
        'weighted': defaultdict(lambda: defaultdict(int)),
        'unweighted': defaultdict(lambda: defaultdict(int))
        }
    combs = []

    if weight_exists:
        logging.info('Diaries weighting enabled as there is "weight" column')
    for categ in categs:
        for zone in zones:
            cond = (agents_df[prec] == zone) & (agents_df['category'] == categ)
            temp_catzone = agents_df[cond]
            temp_diaries = diaries[
                (diaries[prec] == zone) &
                (diaries['category'] == categ)
                ]
            if weight_exists:
                weight = (temp_diaries['weight'] / temp_diaries['weight'].sum()).tolist()
                try:
                    idx = np.random.choice(
                        temp_diaries.index,
                        len(temp_catzone),
                        p=weight
                        )
                    # remove
                    combs.append((categ, zone))
                    idx2 = np.random.choice(
                        temp_diaries.index,
                        len(temp_catzone)
                        )
                    for k, v in Counter(idx2).items():
                        comparison['unweighted'][categ, zone]['_'.join(diaries.loc[k]['activities'])] = v
                    for k, v in Counter(idx).items():
                        comparison['weighted'][categ, zone]['_'.join(diaries.loc[k]['activities'])] = v
                except ValueError:
                    logging.info(f'Weight cannot be applied for {prec} {zone} to category {categ}')
                    idx = np.random.choice(
                        temp_diaries.index,
                        len(temp_catzone)
                        )
            else:
                idx = np.random.choice(
                    temp_diaries.index,
                    len(temp_catzone)
                    )
            agents_df.loc[cond, 'diary'] = idx

    # # remove
    # comps = []
    # for comb in combs:
    #     for tp in ['weighted', 'unweighted']:
    #         comp_df = pd.DataFrame(dict(comparison[tp][comb]), [0]).transpose().rename({0: 'count'}, axis=1)
    #         comp_df.index.name = 'activities'
    #         comp_df['area'] = comb[1]
    #         comp_df['category'] = comb[0]
    #         comp_df['type'] = tp
    #         comps.append(comp_df)
    # big_comp_df = pd.concat(comps).reset_index()
    # big_comp_df = big_comp_df.sort_values(['activities', 'area', 'category', 'type'])


def get_agents_list_strict(
        agents_df: Union[pd.DataFrame, gpd.GeoDataFrame],
        h: Helpers
) -> List[Agent]:
    """
    Get agents list using strict diaries.

    Parameters
    ----------
    agents_df : Union[pd.DataFrame, gpd.GeoDataFrame]
        Table of agents with assigned categories
    h : Helpers
        Dictionary with helper tables, loaded from input_data module.
        Tables 'categories', 'staying', 'modal_split', 'diaries'
        are extracted from the dictionary.

    Returns
    -------
    List[Agent]
        A list of ``Agent`` objects with soc.-eco group, acitivities and
        pre-filled first lasting and starttime

    """
    logging.basicConfig(
        format='%(asctime)s %(levelname)s %(message)s',
        level=logging.INFO)
    # it is to force printing from within threads

    logging.info('Agents processing started')
    set_categories(agents_df, h['categories'])
    drop_staying(agents_df, h['staying'])
    set_modes(agents_df, h['modal_split'])
    assign_diaries(agents_df, h['diaries'])
    agents_list = prepare_strict_agents_list(agents_df, h['diaries'])
    random.shuffle(agents_list)
    return agents_list


def get_basic_agents_df(
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        sample: float = 1.0
        ) -> pd.DataFrame:
    """
    Duplicate home coordinates as many times, as they have capacity.

    Parameters
    ----------
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity.
    sample : float, optional
        Multiply with this fraction to get reduced/increased agents number.
        The default is 1.0.

    Returns
    -------
    pd.DataFrame

    """
    homes = facilities[v.acts['home']]
    agents_df = homes.loc[
        homes.index.repeat(
            scale_to_percent(homes['capacity'].tolist(), perc=sample)
        )
    ].reset_index(drop=True)[list(AGENTS_COLUMNS)]
    return agents_df


def get_agents_list(
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        h: Helpers,
        sample: float = 1.0
) -> List[Agent]:
    """
    Get list of agents using ordinary diaries.

    Ordinary diaries are ones with probabilities of every activity chain.

    Parameters
    ----------
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity.
    h : Helers
        Dictionary with helper tables, loaded from .input.data.load
        Tables 'distances' and 'target_probabilities'
        are extracted from the dictionary.
    sample : float, optional
        Multiply with this fraction to get reduced/increased agents number.
        The default is 1.0.

    Returns
    -------
    agents_list : List[Agent]
        A list of ``Agent`` objects with soc.-eco group and acitivities

    """
    logging.info('Agents processing started')
    agents_df = get_basic_agents_df(facilities, sample=sample)
    set_categories(agents_df, h['categories'])
    set_modes(agents_df, h['modal_split'])
    set_diaries(agents_df, h['diaries'])

    agents_list = []
    aglen = len(agents_df)
    report_n = int(aglen / 10)
    for i, ag in agents_df.iterrows():
        if ag.activities != v.acts['home']:  # skip everyone who stays home
            coords = ag['x'], ag['y']
            agents_list.append(Agent(ag['zone'], ag['district'],
                                     ag['area'], ag['region'],
                                     None, ag.category, ag.activities,
                                     ag.modes, ag.facility, coords,
                                     info=ag['info']
                                     ))
        if i % report_n == 0:
            logging.info(
                f'{i} agents generated ({round(i * 100 / aglen, 2)}%)'
            )
    logging.info('Agents processed')
    random.shuffle(agents_list)
    return agents_list


def set_diaries(
        agents_df: Union[pd.DataFrame, gpd.GeoDataFrame],
        diaries: Diaries
        ):
    """
    Create `activities` column in ``agents_df`` and assigns activities.

    Activities are assigned based on spatial units and categories
    in ``diaries_df``. Changes are made in place.

    Parameters
    ----------
    agents_df : Union[pd.DataFrame, gpd.GeoDataFrame]
        Agents DataFrame, derived from homes facilities
    diaries : pd.DataFrame
        Table of probabilities of a activities chain per spatial reference unit

    """
    prec = diaries.precision
    for zone in agents_df[prec].unique():
        for cat in agents_df.category.unique():
            cond = (agents_df[prec] == zone) & (agents_df.category == cat)
            agents_df.loc[cond, 'activities'] = (
                np.random.choice(diaries[diaries[prec] == zone]['activities'],
                                 len(agents_df[cond]),
                                 p=diaries[diaries[prec] == zone][cat]
                                 ))
    logging.info('Setting diaries done')


def prepare_strict_agents_list(
        agents_df: Union[pd.DataFrame, gpd.GeoDataFrame],
        diaries: Diaries
        ) -> List[Agent]:
    """
    Prepare the list of agents based on strict diaries and spatial precision.
    Skip `t` category (toddlers), as they don't impact traffic or pt occupancy.
    Pre-fill lastings and starttimes from diaries.

    Parameters
    ----------
    agents_df : Union[pd.DataFrame, gpd.GeoDataFrame]
        Agents DataFrame, derived from homes facilities
    diaries : Diaries
        Table of probabilities of a activities chain per spatial reference unit

    Returns
    -------
    List[Agent]
        List of agents

    """
    agents_list = []
    for i, ag in agents_df.reset_index(drop=True).iterrows():
        if ag.category == 't':  # skip everyone who stays home
            continue
        diary = diaries.loc[ag.diary]
        starttimes = []
        lastings = []
        until = len(diary.activities) - 1

        for j, act in enumerate(diary.activities):
            if j == 0:
                starttimes = [
                    td(0),
                    diary['starttime1'] +
                    td(minutes=np.random.normal(0, 5))
                    ]
                lastings.append(td(0))
            elif j != until:
                dur = (
                    td(0) if pd.isnull(diary[f'lasting{j}'])
                    else diary[f'lasting{j}']
                )
                lastings.append(
                    abs(dur + td(minutes=np.random.normal(0, 5)))
                )
        coords = ag['x'], ag['y']
        agobj = Agent(
            zone=ag['zone'],
            district=ag['district'],
            area=ag['area'],
            region=ag['region'],
            calib_code=None,
            category=ag['category'],
            activities=diary['activities'],
            init_mode=ag['modes'],
            facility=ag['facility'],
            home_geom=coords,
            info=ag['info']
        )
        agobj.lastings = lastings
        agobj.starttimes = starttimes
        agents_list.append(agobj)
    return agents_list
