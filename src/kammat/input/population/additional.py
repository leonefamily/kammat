# -*- coding: utf-8 -*-
"""
Created on Mon Dec 19 17:47:21 2022

@author: dgrishchuk
"""

import re
import random
import logging
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path
from datetime import timedelta as td
from typing import Union, Tuple, List, Dict

from kammat.input.data.load import Helpers
from kammat.defaults.variables import Variables
from kammat.input.population.utils import (
    proj_distance, str_to_td
    )
from kammat.input.population.agent import (
    Agent, get_min_diff, write_agents
    )


v = Variables()


def return_to_base(
        agent: Agent,
        base_coords: Tuple[float],
        speed: float,
        now: td,
        to_wait: float
        ) -> td:
    """
    Force city logistics agent to return to base, if working day is ended or
    agent must have cooldown (refill) at base.

    Parameters
    ----------
    agent : Agent
        Agent of city logistics
    base_coords : Tuple[float]
        x and y coordinates of a particular city logistics service
    speed : float
        Dictionary of modes speeds; car speed is extracted
    now : timedelta
        Current time in timedelta object
    to_wait : float
        Base cooldown duration of a particular city logistics service

    Returns
    -------
    td
        Time of agent being ready to leave after cooling down at a base

    """

    agent.coords.append(base_coords)
    dist = proj_distance(agent.coords[-1], base_coords)
    travtime = td(minutes=dist / speed)
    waittime = td(minutes=np.random.normal(1, 0.3) * to_wait)
    now = now + travtime
    agent.starttimes.append(now)
    now += waittime
    agent.endtimes.append(now)
    agent.trips.append(dist)
    agent.lastings.append(waittime)
    agent.triptimes.append(travtime)
    return now


def drop_facilities_by_region(
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        act: str,
        region: str
        ) -> Union[gpd.GeoDataFrame, pd.DataFrame]:
    """
    Drop particular region from facilities if activity exists

    Parameters
    ----------
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity.
    act : str
        String code of act in lower case
    region : str
        Region as stated in facilities files

    Returns
    -------
    filtered : Union[gpd.GeoDataFrame, pd.DataFrame]
        Facilities SINGLE table without specified region

    """
    try:
        filtered = facilities[act][~(facilities[act]['region'] == region)]
    except AttributeError:
        filtered = facilities[act]
    return filtered


def process_ctlog_acts(
        acts: List[str],
        row: pd.Series,
        base_coords: Tuple[float],
        modes_speed: Dict[str, float],
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        ) -> Agent:
    """
    Assign places and start/endtimes to a city logistics agent

    Parameters
    ----------
    acts : List[str]
        List of codes of upcoming activities
    row : pd.Series
        Row with data about city logistics type
    base_coords : Tuple[float]
        x and y coordinates of a particular city logistics service
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity.

    Returns
    -------
    Agent
        Agent object populated with all facilities and times

    """

    # here posiible problem with pandas automatically setting
    # str to Timestamp, we need Timedelta though
    if isinstance(row.service_start, pd.Timestamp):
        row.service_start = str(row.service_start.time())
    if isinstance(row.service_end, pd.Timestamp):
        row.service_end = str(row.service_end.time())

    # !!! more elegant or logical way needed:
    st = str_to_td(row.service_start) + td(minutes=np.random.normal(random.randint(20, 600), 5))
    en = str_to_td(row.service_end)
    if en == td(0):
        en += td(1)
    now = st
    one_ride = (
        row['daily_vehkilometers'] * 1000 /
        row['daily_trips'] /
        row['one_ride_stops']
        )
    visited = [v.acts['citylog'] if row['has_base'] else v.acts['buying']]

    agent = Agent(
        activities=acts,
        init_mode='car',
        facility=row['service_type'],
        home_geom=base_coords,
        population='transit',
        category='citylog'
    )
    agent.coords.append(base_coords)
    agent.endtimes.append(now)

    for j, act in enumerate(acts[:-1]):
        next_act = acts[j + 1]
        if next_act == v.acts['citylog']:
            now = return_to_base(
                agent, base_coords, modes_speed['car'], now,
                row['mean_base_cooldown_duration_min']
                )
            visited.append(next_act)
        else:
            # !!! more elegant or logical way needed, maybe set func parameters
            gen_dist = np.random.normal(1, 0.1) * one_ride
            filtered = drop_facilities_by_region(facilities,
                                                 next_act,
                                                 'suburb')
            facility_id, coords = get_min_diff(facilities, next_act,
                                               gen_dist,
                                               agent.coords[-1],
                                               False, filtered)
            dist = proj_distance(agent.coords[-1], coords)
            travtime = td(minutes=dist / modes_speed['car'])
            waittime = td(
                minutes=np.random.normal(1, 0.3) * row.mean_stop_duration_min)
            if now + travtime > en:
                if row['has_base']:
                    return_to_base(agent, base_coords, modes_speed['car'], now,
                                   row.mean_base_cooldown_duration_min)
                    visited += v.acts['citylog']
                agent.activities = visited
                break
            now += travtime
            agent.starttimes.append(now)
            now += waittime
            agent.endtimes.append(now)

            agent.coords.append(coords)
            agent.trips.append(dist)
            agent.lastings.append(waittime)
            agent.triptimes.append(travtime)
            visited.append(next_act)
    agent.modes = ['car' for _ in visited]
    agent.activities = [v.acts['citylog'] for _ in visited]
    return agent


def setup_city_logistics(
        h: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        sample: Union[float, int] = 1
) -> List[Agent]:
    """
    Calculate city logistics day cycles within their operation time

    Parameters
    ----------
    h : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with helper tables, loaded from input_data.py.
        Table 'city_logistics' is extracted from the dictionary.
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity. Must have `cit` activity
    sample : Union[float, int], optional
        Fraction of the original city logistics counts. The default is 1.

    Returns
    -------
    List[Agent]
        A list of agent objects for city logistics

    """
    logging.info('City logistics processing started')
    availacts = [f for f in facilities if 'region' in facilities[f] and
                 (facilities[f]['region'] == 'city').any()
                 and f not in v.exclude_foster]
    agents = []

    for i, row in h['city_logistics'].iterrows():
        count = round(row['vehs_number'] * sample)
        if not count:
            continue
        row[['service_start', 'service_end']] = pd.to_timedelta(
            row[['service_start', 'service_end']], unit='d')
        if row['service_start'] <= row['service_end']:
            row['service_end'] += td(1)
        companies = facilities[v.acts['citylog']].loc[
            facilities[v.acts['citylog']].base_type == row['service_type']
            ].copy()
        companies['fleet_size'] = (
            companies['fleet_size'] * sample
        ).round().astype('Int64')

        if len(companies) == 0:
            companies.loc[0] = pd.Series({
                'region': 'city',
                'area': None,
                'district': None,
                'zone': None,
                'rel_size': 1,
                'base_name': row['service_type'],
                'base_type': row['service_type'],
                'fleet_size': count
                })

        if row['one_ride_stops'] != 1 and not row['has_base']:
            logging.warning(
                f"Changing {row['service_type']}'s one_ride_stops to 1, "
                "because it has no base"
                )
            row['one_ride_stops'] = 1

        for _, company in companies.iterrows():

            for veh in range(int(company['fleet_size'])):
                if row['has_base']:
                    base_coords = company['x'], company['y']
                    acts = [v.acts['citylog']]
                    for _ in range(row['daily_trips']):
                        trip = np.random.choice(
                            availacts,
                            size=row['one_ride_stops']
                            ).tolist()
                        acts.extend(trip + [v.acts['citylog']])
                else:
                    acts = np.random.choice(
                        availacts,
                        size=row['daily_trips']
                        ).tolist()
                    filtered = drop_facilities_by_region(
                        facilities, acts[0], 'suburb'
                        )
                    base_coords = filtered.sample(1).iloc[0][['x', 'y']].tolist()

                agent = process_ctlog_acts(
                    acts, row, base_coords, v.speeds, facilities
                    )
                agent.info = f"{company['base_type']}_{company['base_name']}_{veh}"
                agent.prepare_xml_block(agent.info)
                agents.append(agent)
        logging.info(f'Service type {row["service_type"]} processed')
    logging.info('City logistics processed')
    return agents


def setup_simple_diaries(
        h: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        kind: str = 'transit',
        mode: str = 'car',
        pref: str = '',
        sample: Union[int, float] = 1
) -> List[Agent]:
    """
    Prepare agents of transit population, that have exactly one origin
    and exactly one destination. Time is generated randomly within one hour
    given in ``h`` in `time_courses` table.

    Parameters
    ----------
    h : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with helper tables, loaded from input_data.py.
        Table 'time_courses' is extracted from the dictionary.
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity.
        Must have `tra` and `fre` activity
    kind : str, optional
        Whether 'oneway' (from some transit point to destination) or
        'transit' (between two transit points). The default is 'transit'.
    mode : str, optional
        String code of mode. The default is 'car'.
    pref : str, optional
        Prefix to distinguish. The default is ''.
    sample : Union[int, float], optional
        Fraction to be derived from original counts. The default is 1.

    Raises
    ------
    ValueError
        If wrong kind passed (not 'transit' or 'oneway')

    Returns
    -------
    List[Agent]
        List of Agent objects with simple plans, ready to write

    """
    if kind not in ['transit', 'oneway']:
        raise ValueError(f'Wrong kind: {kind}')
    repeat = 1 if kind == 'transit' else 2
    point_fac1 = v.acts['transit']
    point_fac2 = v.acts['freight']
    count_fac = v.acts['freight'] if kind != 'transit' else v.acts['transit']
    coord_fac1 = v.acts['freight'] if kind != 'transit' else v.acts['transit']
    coord_fac2 = v.acts['transit']
    logging.info(f'{mode.capitalize()} {kind} processing started')

    points_to = [col for col in facilities[point_fac1].columns
                 if bool(re.match(rf'^{v.acts["transit"]}\d+', col))]
    if kind != 'transit':
        points_from = {col for col in facilities[point_fac2].facility
                       if bool(re.match(rf'^{v.acts["freight"]}\d+', col))}
    else:
        points_from = points_to

    wholelist = []

    for point1 in points_from:
        for point2 in points_to:
            count = round(
                facilities[count_fac].loc[
                    (facilities[count_fac]['facility'] == point1) &
                    (facilities[coord_fac1]['mode'] == mode),
                    point2
                ].iloc[0] * sample
            )
            if count == 0:
                continue
            activities = [coord_fac1, coord_fac2]
            coord1 = facilities[coord_fac1][
                (facilities[coord_fac1].facility == point1) &
                (facilities[coord_fac1]['mode'] == mode)
            ].geometry.iloc[0]
            coord2 = facilities[coord_fac2][
                (facilities[coord_fac2].facility == point2) &
                (facilities[coord_fac2]['mode'] == mode)
            ].geometry.iloc[0]
            coord1 = coord1.coords[0]
            coord2 = coord2.coords[0]
            for _ in range(repeat):
                hours = np.random.choice(a=h['time_courses'].hour, size=count,
                                         p=h['time_courses'][mode])
                minutes = np.random.choice(range(60), count)
                seconds = np.random.choice(range(60), count)

                ag_list = [
                    Agent(
                        activities=activities,
                        init_mode=mode,
                        facility=point1,
                        home_geom=coord1,
                        population='transit'
                    ) for _ in range(count)
                ]

                for i, tr in enumerate(ag_list):
                    tr.endtimes.append(
                        td(hours=int(hours[i]),
                           minutes=int(minutes[i]),
                           seconds=int(seconds[i]))
                        )
                    tr.starttimes.append(td(0))
                    tr.modes.append(tr.init_mode)
                    tr.coords = [coord1, coord2]
                    tr.modes = [tr.init_mode]
                    tr.facilities = [point1, point2]
                    tr.calculate_trips()
                    tr.info = f"{pref}{point1}_{point2}_{i}"
                    tr.prepare_xml_block(tr.info)

                wholelist.extend(ag_list)
                logging.info(f'{point1}-{point2} {mode} {kind} processed')
                if repeat == 2:
                    point1, point2 = point2, point1
                    coord1, coord2 = coord2, coord1
                    activities = activities[::-1]
                    # continues to next round with reversed acts

    logging.info(f'{mode.capitalize()} {kind} processed')
    return wholelist


def handle_additional_agents(
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        h: Helpers,
        sample: float = 1
        ) -> List[Agent]:
    """
    Get all possible additional agents: city logistics, car and freight transit

    Parameters
    ----------
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity. To handle city logistics,
        transit and freight, must have `tra` and `fre` activities
    h : Helpers
        Dictionary with helper tables, loaded from .input.data package
        Tables 'time_courses' and 'city_logistics' are optionally extracted
        from the dictionary.
    sample : float, optional
        Fraction of population to draw from agents list. The default is 1.

    Returns
    -------
    List[Agent]

    """

    additional_agents_list = []

    if 'city_logistics' in h and v.acts['citylog'] in facilities:
        citylog_agents = setup_city_logistics(
            h=h,
            facilities=facilities,
            sample=sample
        )
        additional_agents_list.extend(citylog_agents)

    if 'oneway_flows' in h:
        ow_flows = setup_oneway_flows_diaries(
            facilities=facilities,
            h=h,
            sample=sample
        )
        additional_agents_list.extend(ow_flows)
    else:
        if 'time_courses' in h and v.acts['transit'] in facilities:
            transitcars = setup_simple_diaries(
                h=h,
                facilities=facilities,
                kind='transit',
                mode='car',
                sample=sample
                )
            additional_agents_list.extend(transitcars)
        if 'time_courses' in h and v.acts['freight'] in facilities and v.acts['transit'] in facilities:
            transittruck = setup_simple_diaries(
                h, facilities,
                kind='transit',
                mode='truck',
                pref='f_',
                sample=sample
            )
            additional_agents_list.extend(transittruck)
            onewaytruck = setup_simple_diaries(
                h=h,
                facilities=facilities,
                kind='oneway',
                mode='truck',
                pref='f_',
                sample=sample
            )
            additional_agents_list.extend(onewaytruck)

    return additional_agents_list


def setup_oneway_flows_diaries(
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        h: Helpers,
        sample: float = 1
) -> List[Agent]:
    ow_agents = []
    total_count = 0
    for i, row in h['oneway_flows'].iterrows():
        pre_count = row['count'] * sample
        if pre_count < 1:
            keep = np.random.choice([True, False], p=[sample, 1 - sample])
            if not keep:
                continue
        count = max(round(pre_count), 1)
        total_count += count
        mode = row['mode']

        from_act = row['from_activity']
        from_fac = row['from_facility']
        to_act = row['to_activity']
        to_fac = row['to_facility']
        from_slevel = row['from_spatial_level']
        from_spunit = row['from_spatial_unit']
        to_slevel = row['to_spatial_level']
        to_spunit = row['to_spatial_unit']
        if pd.isnull(from_act):
            if pd.isnull(from_spunit):
                available_from_facilities = {
                    act: facs[facs[from_slevel] == from_spunit]
                    for act, facs in facilities.items()
                }
                available_from_facilities = {
                    act: facs for act, facs
                    in available_from_facilities.items()
                    if len(facs)
                }
                acts_counts = {
                    act: len(facs) for act, facs
                    in available_from_facilities.items()
                }
                acts_weights = {
                    act: val / sum(acts_counts.values())
                    for act, val in acts_counts.items()
                }
            else:
                available_from_facilities = facilities
                acts_weights = {
                    act: len(facs) / sum(facilities.values())
                    for act, facs in facilities.items()
                }
            from_activities = np.random.choice(
                list(acts_weights.keys()),
                p=list(acts_weights.values()),
                size=count,
                replace=True
            )
        else:
            available_from_facilities = {from_act: facilities[from_act]}
            from_activities = [from_act] * count

        if pd.isnull(to_act):
            if pd.isnull(to_spunit):
                available_to_facilities = {
                    act: facs[facs[to_slevel] == to_spunit]
                    for act, facs in facilities.items()
                }
                available_to_facilities = {
                    act: facs for act, facs
                    in available_from_facilities.items()
                    if len(facs)
                }
                acts_counts = {
                    act: len(facs) for act, facs
                    in available_to_facilities.items()
                }
                acts_weights = {
                    act: val / sum(acts_counts.values())
                    for act, val in acts_counts.items()
                }
            else:
                available_to_facilities = facilities
                acts_weights = {
                    act: len(facs) / sum(facilities.values())
                    for act, facs in facilities.items()
                }
            to_activities = np.random.choice(
                list(acts_weights.keys()),
                p=list(acts_weights.values()),
                size=count,
                replace=True
            )
        else:
            available_to_facilities = {to_act: facilities[to_act]}
            to_activities = [to_act] * count

        if pd.isnull(from_fac):
            from_facilities = [
                available_from_facilities[fa].sample(1)[
                    ['facility', 'geometry']
                ].iloc[0].to_dict()
                for fa in from_activities
            ]
        else:
            from_facilities = [{
                'facility': from_fac,
                'geometry': facilities[from_act].loc[
                    facilities[from_act]['facility'] == from_fac, 'geometry'
                ].iloc[0]
            }] * count

        if pd.isnull(to_fac):
            to_facilities = [
                available_to_facilities[ta].sample(1)[
                    ['facility', 'geometry']
                ].iloc[0].to_dict()
                for ta in to_activities
            ]
        else:
            to_facilities = [{
                'facility': to_fac,
                'geometry': facilities[to_act].loc[
                    facilities[to_act]['facility'] == to_fac, 'geometry'
                ].iloc[0]
            }] * count

        departure_times = []
        deptime_constr = zip(
            np.random.choice(
                h['time_courses']['hour'],
                p=h['time_courses'][mode],
                size=count
            ).tolist(),
            np.random.uniform(0, 3600, size=count).tolist()
        )
        for deph, deps in deptime_constr:
            departure_times.append(td(hours=deph, seconds=deps))

        for num in range(count):
            ow_ag = Agent(
                activities=[from_activities[num], to_activities[num]],
                init_mode=mode,
                facility=from_facilities[num]['facility'],
                home_geom=(
                    from_facilities[num]['geometry'].x,
                    from_facilities[num]['geometry'].y
                ),
                population='transit'
            )
            ow_ag.endtimes.append(departure_times[num])
            ow_ag.starttimes.append(td(0))
            ow_ag.modes.append(ow_ag.init_mode)
            ow_ag.coords = [(
                from_facilities[num]['geometry'].x,
                from_facilities[num]['geometry'].y
            ), (
                to_facilities[num]['geometry'].x,
                to_facilities[num]['geometry'].y
            )]
            ow_ag.modes = [ow_ag.init_mode]
            ow_ag.facilities = [
                from_facilities[num]['facility'],
                to_facilities[num]['facility']
            ]
            ow_ag.calculate_trips()
            ow_ag.info = f"{'_'.join(ow_ag.facilities)}_{mode}_{num}"
            ow_ag.prepare_xml_block(ow_ag.info)
            ow_agents.append(ow_ag)
    return ow_agents


def handle_and_write_additional_agents(
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        h: Helpers,
        xml_path: Union[str, Path] = None,
        sample: float = 1
        ) -> List[Agent]:
    """
    Get and write all possible additional agents (city logistics, car and
    freight transit)

    Parameters
    ----------
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity. To handle city logistics,
        transit and freight, must have `tra` and `fre` activities
    h : Helpers
        Dictionary with helper tables, loaded from .input.data package
        Tables 'time_courses' and 'city_logistics' are optionally extracted
        from the dictionary.
    xml_path : Union[str, Path], optional
        Path where agents will be written
    sample : float, optional
        Fraction of population to draw from agents list. The default is 1.

    Returns
    -------
    List[Agent]

    """
    additional_agents_list = handle_additional_agents(facilities, h, sample)
    if xml_path is not None:
        write_agents(additional_agents_list, xml_path)
    return additional_agents_list
