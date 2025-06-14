# -*- coding: utf-8 -*-
"""
Created on Sun Dec 18 14:36:22 2022

@author: dgrishchuk
"""

import logging
import geopandas as gpd
from pathlib import Path
from typing import Union, Tuple, Dict


from kammat.input.data.facilities import (
    load_facilities, get_spatial_units
    )
from kammat.input.data.categories import load_categories
from kammat.input.data.diaries import load_diaries
from kammat.input.data.oneway_flows import load_oneway_flows
from kammat.input.data.staying import (
    load_staying, get_staying_category_spatial_unit_combinations
    )
from kammat.input.data.distances import load_distances
from kammat.input.data.target_probabilities import (
    load_target_probabilities
    )

from kammat.input.data.time_courses import load_time_courses
from kammat.input.data.city_logistics import load_city_logistics
from kammat.input.data.modal_split import load_modal_split
from kammat.input.data.times import load_times
from kammat.input.data.indices import load_indices
from kammat.input.data.relations import load_relations
from kammat.input.data.stops import load_stops
from kammat.defaults.variables import Variables
from kammat.input.data.types import Helpers


def load_data(
        facilities_path: Union[str, Path],
        categories_path: Union[str, Path],
        diaries_path: Union[str, Path],
        distances_path: Union[str, Path],
        clusters_path: Union[str, Path] = None,
        citylog_points_path: Union[str, Path] = None,
        freight_points_path: Union[str, Path] = None,
        transit_points_path: Union[str, Path] = None,
        staying_path: Union[str, Path] = None,
        target_probabilities_path: Union[str, Path] = None,
        time_courses_path: Union[str, Path] = None,
        city_logistics_path: Union[str, Path] = None,
        times_path: Union[str, Path] = None,
        modal_split_path: Union[str, Path] = None,
        indices_path: Union[str, Path] = None,
        relations_path: Union[str, Path] = None,
        stops_path: Union[str, Path] = None,
        oneway_flows_path: Union[str, Path] = None,
        ) -> Tuple[Dict[str, gpd.GeoDataFrame], Helpers]:
    """
    Load all possible spatial and non-spatial input data about population

    Parameters
    ----------
    facilities_path : Union[str, Path]
        DESCRIPTION.
    categories_path : Union[str, Path]
        DESCRIPTION.
    diaries_path : Union[str, Path]
        DESCRIPTION.
    distances_path : Union[str, Path]
        DESCRIPTION.
    clusters_path : Union[str, Path], optional
        DESCRIPTION. The default is None.
    citylog_points_path : Union[str, Path], optional
        DESCRIPTION. The default is None.
    freight_points_path : Union[str, Path], optional
        DESCRIPTION. The default is None.
    transit_points_path : Union[str, Path], optional
        DESCRIPTION. The default is None.
    staying_path : Union[str, Path], optional
        DESCRIPTION. The default is None.
    target_probabilities_path : Union[str, Path], optional
        DESCRIPTION. The default is None.
    time_courses_path : Union[str, Path], optional
        DESCRIPTION. The default is None.
    city_logistics_path : Union[str, Path], optional
        DESCRIPTION. The default is None.
    times_path : Union[str, Path], optional
        DESCRIPTION. The default is None.
    modal_split_path : Union[str, Path], optional
        DESCRIPTION. The default is None.
    relations_path : Union[str, Path], optional
        DESCRIPTION. The default is None.

    Raises
    ------
    RuntimeError
        DESCRIPTION.

    Returns
    -------
    facilities : Dict[str, gpd.GeoDataFrame]
    helpers :  Dict[str, Union[Diaries, Distances, TargetProbabilities,
                               Times, Indices, CityLogistics, Staying,
                               ModalSplit, TimeCourses, Categories, Relations]]

    """

    v = Variables()

    if city_logistics_path is None and citylog_points_path is not None:
        raise RuntimeError('City logistics points are specified, but'
                           'city logistics info is not')

    # !!! get polygons for the whole scope! and check validity with them
    # creeate function in utils for this
    # check connections between diaries
    helpers = {}

    facilities = load_facilities(facilities_path,
                                 clusters_path,
                                 transit_points_path,
                                 freight_points_path,
                                 citylog_points_path)

    if freight_points_path or transit_points_path:
        if time_courses_path is None:
            raise RuntimeError(
                'If freight or transit points used, time courses are mandatory'
                )
        req_tc_modes = set()
        if transit_points_path:
            req_tc_modes.update(
                set(facilities[v.acts['transit']]['mode'].tolist()))
        if freight_points_path:
            req_tc_modes.add('truck')

        helpers['time_courses'] = load_time_courses(
            time_courses_path, req_modes=list(req_tc_modes)
            )

    activities_spatial_units = {
        a: get_spatial_units(facilities[a]) for a in facilities
    }

    spatial_units = get_spatial_units(facilities[v.acts['home']])
    activities_for_diaries = [a for a in facilities.keys()
                              if a not in v.cuckoo_acts + v.special_acts]

    helpers['categories'] = load_categories(categories_path, spatial_units)
    categories = helpers['categories'].categories

    if staying_path:
        helpers['staying'] = load_staying(staying_path,
                                          categories,
                                          spatial_units)
        ignore_category_spatial_units_combs = (
            get_staying_category_spatial_unit_combinations(helpers['staying'])
        )
    else:
        ignore_category_spatial_units_combs = None

    helpers['diaries'] = load_diaries(
        diaries_path, activities_for_diaries, categories, spatial_units,
        ignore_category_spatial_units_combs=ignore_category_spatial_units_combs
        )

    activities = helpers['diaries'].all_activities
    activities_lc = list(set(a.lower() for a in activities))
    logging.info(
        f'Following activities will be used in the simulation: {activities}')

    if staying_path is None and helpers['diaries'].type == 'strict':
        raise RuntimeError(
            'In case strict diaries are used, staying is mandatory'
        )

    if times_path is None and helpers['diaries'].type == 'non-strict':
        helpers['times'] = load_times

    activities_for_distances = activities_lc  # + list(v.cuckoo_acts)

    if target_probabilities_path:
        helpers['target_probabilities'] = load_target_probabilities(
            target_probabilities_path, activities_for_distances, spatial_units
        )

    helpers['distances'] = load_distances(
        distances_path, categories, activities_for_distances, spatial_units
    )

    if helpers['distances'].target_precision is not None and not target_probabilities_path:
        raise RuntimeError(
            'If distances have target column, target probabilities are mandatory'
        )
    elif helpers['distances'].target_precision is not None and (
            helpers['target_probabilities'].target_precision !=
            helpers['distances'].target_precision
        ):
        raise RuntimeError(
            'Distances target and target probabilities precision is different'
        )

    if city_logistics_path:
        helpers['city_logistics'] = load_city_logistics(city_logistics_path)
        if citylog_points_path:
            btypes = helpers['city_logistics'].base_types
            # if there are not enough base types described in citylog points
            if not set(btypes).issubset(
                    set(facilities[v.acts['citylog']]['base_type'].tolist())
                ):
                raise RuntimeError(
                    'There is not every base type in citylog points '
                    f'described in citylog info: {btypes}'
                )

    helpers['modal_split'] = load_modal_split(modal_split_path, categories,
                                              activities, spatial_units)

    if indices_path:
        helpers['indices'] = load_indices(indices_path, activities)

    if relations_path:
        helpers['relations'] = load_relations(relations_path, activities)

    if stops_path:
        helpers['stops'] = load_stops(stops_path)

    if oneway_flows_path:
        helpers['oneway_flows'] = load_oneway_flows(oneway_flows_path, facilities)

    return facilities, helpers
