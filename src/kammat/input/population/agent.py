# -*- coding: utf-8 -*-
"""
Created on Mon Jul 19 17:12:28 2021

@author: dgrishchuk
"""
import gzip
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
import matplotlib.pyplot as plt
import numpy as np
from datetime import timedelta
from io import StringIO
import logging
import random
from pathlib import Path
from copy import deepcopy
from typing import Union, Tuple, List, Dict, Literal, Optional, Any

from kammat.input.data.types import Helpers
from kammat.defaults.variables import Variables
from kammat.defaults.constants import (
    SPATIAL_LEVELS_LIST, PRIVATE_MODES, MODAL_SPLIT_MODES
    )
from kammat.input.population.utils import (
    proj_distance, proj_distance_df, td_to_str, intify
    )
from kammat.defaults.constants import CACHE_SETTINGS_PATH

CACHE_FOLDER: Path = Path(CACHE_SETTINGS_PATH) / 'population'
v = Variables()


class Agent:

    """
    An object for MATSim agent representation.

    Attributes
    ----------
    zone : str
        Home zone for agent.
    district : str
        Home district for agent.
    area : str
        Home area for agent.
    region : str
        Home region for agent.
    calib_code : str
        Home calibration code for agent. # !!! Unused.
    category : str
        Role of agent - e (employed), mss (middle school student), etc...
    activities : List[str]
        List of agent's activities as strings, eg. ['hom', 'wor', 'hom'].
    init_mode : str
        Initial mode of transport for agent, that is kept for most
        of the trips, if possible.
    facility : str
        Home zone for agent
    home_geom : Tuple[float]
        Geometry of home point. A tuple of x and y coord
    population : str
        Population name. The default is 'regular', may be any string
    info : str
        Home zone for agent. The default is empty string.
    endtimes : List[timedelta]
        List of timedeltas, describing the time, when the agent left facility
        with the same index, eg. if self.facilities[0] is 'hom', then
        the time when agent leaves his home facility for the first time
        is in self.endtimes[0]
    lastings : List[timedelta]
        List of timedeltas, describing the time that was spent at the facility
        with the same index, eg. if self.facilities[1] is 'wor', then
        the time that was spent at work is in self.lastings[1]. First lasting
        equals to zero timedelta.
    starttimes : List[timedelta]
        List of timedeltas, describing the time of arrival to the facility
        with the same index, eg. if self.facilities[1] is 'wor', then the
        time of arrival is self.starttimes[1]. First starttime equals to
        zero timedelta.
    facilities : List[str]
        List of strings representing facilities id,
        eg. ['hom7899', 'wor2554', 'hom7899']
    spatial_references : List[Dict[str, str]]
        List of dicts with facilities' spatial references
    coords : List[Tuple[float]]
        List of coordinates of every facility with the same index
    modes : List[str]
        List of strings representing modes used by agent for every trip, eg.
        self.modes[0] is mode for the trip between
        self.facilities[0] and self.facilities[1]
    gendists : List[Union[float, int]]
        List of numeric values of distances, that were generated for agent's
        trips between facilities, eg. self.gendists[0] is generated distance
        for trip betwen self.facilities[0] and self.facilities[1]
    trips : List[Union[float, int]]
        List of numeric values of beeline distance between facilities, eg.
        self.trips[0] is distance between
        self.facilities[0] and self.facilities[1]
    triptimes : List[timedelta]
        List of timedeltas, describing the time that is spent while travelling,
        eg. self.triptimes[0] is the time between
        self.facilities[0] and self.facilities[1]
    pt_stop_walks : List[Union[float, int]]
        List of numeric values, representing beeline distances to the nearest
        public transport stops
    links : List[str]
        List of strings, representing link_id's from MATSim network,
        that define, where agent should spawn and disappear, when interacts
        with facilities, eg. self.links[0] is the link to interact with
        self.facilities[0]
    car_avail : str
        Car availability status, is either 'always' or 'never' depending on
        agent's socioeconomic category (self.category)
    xml_buffer : StringIO
        Buffer containing full XML block for agent as MATSim population_v6.dtd
        schema requires
    csv_buffer : StringIO
        Buffer containing a row describing the agent for further analysis
        after stacking into csv file

    """

    def __init__(
            self,
            zone: str = None,
            district: str = None,
            area: str = None,
            region: str = None,
            calib_code: str = None,
            category: str = None,
            activities: List[str] = None,
            init_mode: str = 'car',
            facility: str = None,
            home_geom: Tuple[float, float] = None,
            population: str = 'regular',
            info: str = ''
            ):
        """
        Create Agent class.

        Parameters
        ----------
        zone : str, optional
            Home zone for agent. Can be None, if not regular population.
        district : str, optional
            Home district for agent. Can be None, if not regular population.
        area : str, optional
            Home area for agent. Can be None, if not regular population.
        region : str, optional
            Home region for agent. Can be None, if not regular population.
        calib_code : str, optional
            Home calibration code for agent. Unused.
        category : str, optional
            Role of agent - e (employed), mss (middle school student), etc...
        activities : List[str], optional
            List of agent's activities, eg. ['hom', 'wor', 'hom']
        init_mode : str, optional
            Initial mode of transport for agent. The default is 'car'.
        facility : str, optional
            Home facility for agent. The default is None.
        home_geom : Tuple[float], optional
            Geometry of home point. A tuple of x and y coord
        population : str, optional
            Population name. The default is 'regular', may be any string
        info : str, optional
            Any info defining the agent. The default is empty string.

        """
        self.zone = zone
        self.district = district
        self.area = area
        self.calib_code = calib_code
        self.region = region
        self.home_facility = facility
        self.home_geom = home_geom
        self.category = category
        self.endtimes = []
        self.lastings = []
        self.starttimes = []
        self.activities = activities
        self.spatial_references = []
        self.facilities = []
        self.coords = []
        self.init_mode = init_mode
        self.modes = []
        self.gendists = []
        self.trips = []
        self.triptimes = []
        self.pt_stop_walks = []
        self.population = population
        self.links = []
        self.car_avail = 'never' if category in ['ess', 'mss'] else 'always'
        self.xml_buffer = StringIO()
        self.csv_buffer = StringIO()
        self.info = info

    def __str__(self):
        start = self.starttimes[1] if len(self.starttimes) > 1 else None
        end = self.endtimes[-1] if self.endtimes else None
        return (
            f'Agent(category={self.category}, activities={self.activities}, '
            f'region={self.region}, area={self.area}, district={self.district}'
            f', zone={self.zone}, start={start}, end={end}'
            )

    def __repr__(self):
        start = self.starttimes[1] if len(self.starttimes) > 1 else None
        end = self.endtimes[-1] if self.endtimes else None
        return (
            f'Agent(category={self.category}, activities={self.activities}, '
            f'region={self.region}, area={self.area}, district={self.district}'
            f', zone={self.zone}, start={start}, end={end}'
            )

    def copy(self):
        """
        Recreate Agent with basic attributes passed along with created instance
        Does not save attributes, that did not come with the parameters

        Returns
        -------
        Agent

        """
        return Agent(self.zone, self.district, self.area, self.region,
                     self.calib_code, self.category, self.activities,
                     self.init_mode, self.home_facility, self.home_geom,
                     self.population, self.info)

    def generate_dists(
            self,
            h: Helpers
            ):
        """
        Generates random variable from Weibull distribution
        with parameters (0.96, 0.96), max possible value is 4.
        Then the value is multiplied by mean travel distance
        based on agent's socioeconomic group, home zone
        and the upcoming activity type.

        Note
        ----
        - Here, the distance is only searched by upcoming activities,
        previous activities are not involved.
        - The method is used only if no spatial restrictions applied.

        Parameters
        ----------
        h : Helpers
            Dictionary with helper tables, loaded from input_data module.
            Table 'distances' is extracted from the dictionary.

        """
        dists = []
        for i, act in enumerate(self.activities):
            if act in v.no_gen_dist:
                # activities that don't allow distance generating, namely home
                gen_dist = 0
            else:
                randweib = min(np.random.weibull(0.96) * 0.96, 4)
                prec = h['distances'].precision
                fixval = h['distances'][act.lower()][h['distances'][prec] == getattr(self, prec)].iloc[0]
                gen_dist = int(randweib * fixval)
            dists.append(gen_dist)
        self.gendists = dists

    def pick_dists_facilities_spatially(
            self,
            facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
            h: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
            reset_at_home: bool = False,
            closer_to_home: bool = True
            ):
        """
        Generates distances, picks facilities and their coords, and
        calculates trip lengths between those facilities.

        Note
        ----
        - This method is based on spatial from `target_probabilities`
        table from ``h`` and precisional restrictions of ``facilities``.
        `distances` table from ``h`` has to have '{`precision`}_target' column,
        where `precision` is the smallest available spatial unit in
        ``facilities`` out of available.
        - Generated distance is 0, when the destination is predefined, eg. home

        Parameters
        ----------
        facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
            Dictionary with (Geo)DataFrames, containing info about
            facilities for every available activity.
        h : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
            Dictionary with helper tables, loaded from input_data.py.
            Tables 'distances' and 'target_probabilities'
            are extracted from the dictionary.
        reset_at_home : bool, optional
            Define, whether the mode should reset and be found again,
            when the agent arrives home
        closer_to_home : bool, optional
            Set to True, if agent should try to look for activity before home,
            that is closer to it, than other available, instead of just picking
            by minimal distance difference according to ``h[distances]``

        """
        (coords, gendists, dists, fclts,
         modes, pt_stop_walks, spat_refs) = [[] for _ in range(7)]

        visited_dict = {v.acts['home']: {
            'facility': self.home_facility,
            'coord': self.home_geom,
            'spatial_ref': get_spat_ref_dict(facilities, v.acts['home'],
                                             self.home_facility)
            }
        }
        remove_first, currnext_acts = group_upcoming_acts(self.activities, n=3)
        # first act is removed, if agent doesn't start at home
        lastact = None  # is an activity of the last visited facility

        for i, (curr_act, next_act, next_next_act) in enumerate(currnext_acts):

            islast = i >= (len(currnext_acts) - (1 if remove_first else 0))
            curr_act = lastact if lastact is not None else curr_act

            # ---------- Handle first or repeating activities block -----------

            if ((next_act in visited_dict
                and next_act in v.capacity_affected
                    and next_act != curr_act)
                        or next_act == v.acts['home']) and i != 0:
                # if next act is affected by obligatory returning, or it's home
                # just append the same coordinates and facility as existing
                act_dict = visited_dict[next_act]

                dist = proj_distance(coords[-1], act_dict['coord'])
                stopwalk1 = get_pt_stop_walk(coords[-1], h)
                stopwalk2 = get_pt_stop_walk(act_dict['coord'], h)
                gendists.append(0)
                dists.append(dist)
                coords.append(act_dict['coord'])
                fclts.append(act_dict['facility'])

                if not islast:  # !!! more elegant way needed...
                    mode = self.pick_mode_spatially(
                        h, i, dist, stopwalk1, stopwalk2,
                        spat_refs[-1], act_dict['spatial_ref'],
                        reset_at_home=reset_at_home
                        )
                    modes.append(mode)

                pt_stop_walks.append(stopwalk1)
                spat_refs.append(act_dict['spatial_ref'])
                continue
            elif i == 0:
                # generally triggers, when the first activity is not home
                # simulates departure from home, but will be removed anyway
                # used only to send agent somewhere based on statistics from h
                # doesn't jump to the next iteration like usual home
                gendists.append(0)
                fclts.append(visited_dict[curr_act]['facility'])
                coords.append(visited_dict[curr_act]['coord'])
                spat_refs.append(visited_dict[curr_act]['spatial_ref'])
            # -----------------------------------------------------------------

            reduce = must_reduce(next_act)
            # whether to reduce capacity of facility
            isup = next_act.isupper()
            # uppercase means escort: same facilities, but different stats in h

            # --------------- Handle "not-own" activities block ---------------

            if next_act.lower() in v.cuckoo_acts:  # acts without own facilities
                if next_act.lower() == v.acts['visit']:
                    # visits can only be in homes layer
                    next_act = v.acts['home']
                else:
                    # any other picks randomly except for excluded
                    next_act = np.random.choice([f for f in facilities.keys()
                                                 if f.lower() not in
                                                 v.exclude_foster])
                if isup:
                    next_act = next_act.upper()
                reduce = False  # never reduce capacity, if "not-own"
            # -----------------------------------------------------------------

            # ----------------- Handle other activities block -----------------

            if next_act in v.no_move_acts:
                # activities that are not simulated - walking, cycling etc...
                fclt, coord, next_spat_ref_prob, next_spat_ref, next_act = (
                    fclts[-1],
                    coords[-1],
                    spat_refs[-1][h['target_probabilities'].precision],
                    spat_refs[-1],
                    curr_act
                    )
                new_gen_dist = 0

            else:  # all other simulated activities
                gen_dist, next_spat_ref_prob = generate_dist_spatially(
                    h, curr_act, next_act, spat_refs[-1]
                    )
                # get not only distance, but spatial reference based on stats
                # it's proven, that distance distribution might have two peaks
                # depending on where does a person departs from or where to

                next_act_l = next_act.lower()

                filtered = include_indices(
                    facilities, h, next_act_l, next_spat_ref_prob
                )
                # filter by indices probabilities where applicable

                filtered = include_relations(
                    filtered, h, next_act_l,
                    spat_refs[-1]  # or visited_dict[v.acts['home']]['spatial_ref']
                    )
                # if relations are available, reduce possibilities

                if next_act_l in v.cluster_affected:
                    # prefer places that lie in predefined clusters
                    filtered = get_places_cluster(
                        filtered, facilities, next_act_l, gen_dist, coords[-1]
                    )

                if spat_refs[-1][h['target_probabilities'].precision] != next_spat_ref_prob:
                    # or spat_refs[PRECISIONS['target_probabilities']][-1] == 'suburb' and next_spat_ref == 'city':
                    # alter_suburb_dist

                    # creates new distance based on reachability
                    new_gen_dist = alter_any_dist(
                        coords[-1], gen_dist, filtered,
                        outer_offset=v.cluster_dist_thresh,
                        alter_thresh=v.reach_percentage
                    )
                else:
                    new_gen_dist = gen_dist

                fclt, coord, next_spat_ref = get_min_diff(
                    facilities, next_act_l, new_gen_dist,
                    coords[-1], reduce, filtered,
                    extended=True,
                    closer_to_home=closer_to_home,
                    home_coord=self.home_geom,
                    prev_act=curr_act,
                    next_act=next_next_act,
                )

            # -----------------------------------------------------------------

            dist = proj_distance(coords[-1], coord)
            stopwalk1 = get_pt_stop_walk(coords[-1], h)
            stopwalk2 = get_pt_stop_walk(coord, h)

            gendists.append(new_gen_dist)
            dists.append(dist)
            fclts.append(fclt)
            coords.append(coord)
            pt_stop_walks.append(stopwalk1)
            spat_refs.append(next_spat_ref)

            if not islast:
                mode = self.pick_mode_spatially(
                    h, i, dist, stopwalk1, stopwalk2,
                    spat_refs[-1], next_spat_ref
                    )
                modes.append(mode)

            if next_act not in visited_dict:
                # to know if we've done this activity somewhere already
                visited_dict[next_act] = {
                    'facility': fclt,
                    'coord': coord,
                    'spatial_ref': next_spat_ref
                    }
            lastact = next_act

        pt_stop_walks.append(stopwalk2)  # last stop walk
        self.facilities = fclts[1:] if remove_first else fclts
        self.coords = coords[1:] if remove_first else coords
        self.gendists = intify(gendists[1:] if remove_first else gendists)
        self.trips = intify(dists[1:] if remove_first else dists)
        self.modes = self._fix_private_modes(modes)
        self.pt_stop_walks = intify(pt_stop_walks[1:] if remove_first else pt_stop_walks)
        self.spatial_references = spat_refs[1:] if remove_first else spat_refs

    def pick_facilities(
            self,
            facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
            h: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
            ):
        """
        Pick facilities for agent's diary, not taking spatial aspect into
        account.
        # !!! DEPRECATED, use ``self.pick_dists_facilities_spatially()``

        Parameters
        ----------
        facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
            Dictionary with (Geo)DataFrames, containing info about
            facilities for every available activity.
        h : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
            Dictionary with helper tables, loaded from input_data.py.

        """
        fclts = []
        coords = []
        visited_dict = {}
        lastact = None

        for i, act in enumerate(self.activities):
            gen_dist = self.gendists[i]

            if act in visited_dict and act in v.capacity_affected and act != lastact:
                fclt, coord = visited_dict[act]
                fclts.append(fclt)
                coords.append(coord)
                continue

            if act == v.acts['home']:
                fclts.append(self.home_facility)
                coords.append(self.home_geom)
                continue

            reduce = must_reduce(act)
            isup = act.isupper()

            if act.lower() in [v.acts['worktrip'], v.acts['citylog'],
                               v.acts['other'],  v.acts['visit']]:
                if act.lower() == v.acts['visit']:
                    act = v.acts['home']
                else:
                    act = np.random.choice(
                        [f for f in facilities.keys()
                         if f.lower() not in v.exclude_foster]
                        )
                if isup:
                    act = act.upper()
                reduce = False

            pre_coord = None if i == 0 else coords[-1]
            if act in (v.acts['walk'], v.acts['walk'].upper(),
                       v.acts['cycling'], v.acts['cycling'].upper()):
                fclt, coord = self.activities[i - 1], pre_coord
            else:
                fclt, coord = pick_any_place(facilities, act, gen_dist, h,
                                             pre_coord, reduce)
            fclts.append(fclt)
            coords.append(coord)

            if act not in visited_dict:
                visited_dict[act] = (fclt, coord)

            lastact = act

        self.facilities = fclts
        self.coords = coords

    def prefer_private_mode(
            self,
            once_car_always_car: bool = False,
            abandon_pt: bool = False,
            abandon_pt_thresh: Union[float, int] = 30000,
            abandon_pt_prob: Union[float, int] = 0.4
            ):
        """
        Increase car preference, and slightly override what is given by the
        modal split table. There are two strategies - abandoning pt, if sum
        of trip lengths is too big, or setting all trips with car mode, if
        it was used at least once. The strategies can be combined.

        Parameters
        ----------
        once_car_always_car : bool, optional
            If met `car` mode in modes, replace every mode with car.
            The default is False.
        abandon_pt : bool, optional
            Allow pt abandoning. Pt will be abandoned with probability,
            specified in ``abandon_pt_prob``, if total bee-line length of all
            trips exceeds ``abandon_pt_thresh``. The default is False.
        abandon_pt_thresh : Union[float, int], optional
            If total bee-line length of all trips exceeds
            ``abandon_pt_thresh``, pt will be abandoned with probability,
            specified in ``abandon_pt_prob``. The default is 30000.
        abandon_pt_prob : Union[float, int], optional
            Pt will be abandoned with probability, specified in
            ``abandon_pt_prob``, if total bee-line length of all
            trips exceeds ``abandon_pt_thresh``. The default is 0.4.

        """
        modes = self.modes[:]
        if (abandon_pt and
            sum(self.trips) > abandon_pt_thresh and
                any(mode == 'pt' for mode in modes)):
            change = np.random.choice([True, False],
                                      p=[abandon_pt_prob, 1 - abandon_pt_prob])
            if change:
                if self.category not in ['ess', 'mss']:
                    modes = ['car' for _ in modes]
                else:
                    modes = ['carpool' for _ in modes]

        if once_car_always_car:
            for mode in modes:
                if mode == 'car':
                    modes = [mode] * len(modes)
                    break
        self.modes = modes

    def calculate_trips(self):
        """
        Calculate trip lengths based on picked coordinates
        of activities, that the agent have already chosen

        Note
        ----
        - Resulting list for self.trips is populated with integer values

        """
        dists = []
        for i, coord in enumerate(self.coords[:-1]):
            dist = int(proj_distance(coord, self.coords[i + 1]))
            dists.append(dist)
        self.trips = dists

    def stop_dists(
            self,
            h: Helpers
            ):
        """
        Beeline distances to the nearest stops for every activity coordinates.
        If `stops` table is not provided, sets zero for every facility

        Parameters
        ----------
        h : Helpers
            Dictionary with helper tables, loaded from input_data module.
            Table 'stops' is extracted from the dictionary.

        Note
        ----
        `stops` is GTFS-like table with stops coordinates in **cartesian** CRS

        """

        if 'stops' not in h:
            walk_dists = [0 for _ in range(len(self.coords))]
        else:
            walk_dists = []
            for i, coord in enumerate(self.coords):
                walk_dist = int(proj_distance_df(h['stops'], coord).min())
                walk_dists.append(walk_dist)
        self.pt_stop_walks = walk_dists

    def pick_mode_spatially(
            self,
            h: Helpers,
            tripnum: int,
            triplen: Union[int, float],
            stopwalk1: Union[int, float],
            stopwalk2: Union[int, float],
            spat_ref1: Dict[str, str],
            spat_ref2: Dict[str, str] = None,
            walk_thresh: Union[int, float] = 1000,
            pt_stop_thresh: Union[int, float] = 750,
            reset_at_home: bool = True
            ) -> str:
        """
        Assign transport mode for trip number ``tripnum``. Decides, whether
        to abandon init_mode and start to look for new one.

        Parameters
        ----------
        h : Helpers
            Dictionary with helper tables, loaded from input_data module.
            Table 'modal_split' is extracted from the dictionary.
        tripnum : int
            Number of agent's trip (technically, rather number of activity)
        walk_thresh : Union[int, float], optional
            Threshold distance (m) between facilities beyond which walk mode
            is not chosen. The default is 1000.
        pt_stop_thresh : Union[int, float], optional
            Threshold distance (m) between facility and the closest pt stop
            beyond which pt mode is not chosen. The default is 750.
        reset_at_home : bool, optional
            Define, whether the mode should reset and be found again,
            when the agent arrives home. The default is True

        Raises
        ------
        ValueError
            If passed negative threshold distances

        Returns
        -------
        str
            Chosen mode

        """
        if any(val < 0 for val in [walk_thresh, pt_stop_thresh]):
            raise ValueError('Distances must be positive')

        if tripnum >= len(self.activities) - 1:
            raise ValueError(
                f'Trip number {tripnum} is more than there are trips'
                )

        if tripnum == 0:
            init_mode = None
        elif tripnum != 0 and not reset_at_home:
            init_mode = self.init_mode
        elif tripnum != 0 and self.activities[tripnum].lower() == v.acts['home']:
            init_mode = None
        else:
            init_mode = self.init_mode

        mode = choose_single_mode(self.category, self.activities[tripnum],
                                  self.activities[tripnum + 1], triplen,
                                  stopwalk1, stopwalk2, h, spat_ref1,
                                  spat_ref2, init_mode, walk_thresh,
                                  pt_stop_thresh)
        if init_mode is None:
            self.init_mode = mode
        return mode

    def pick_modes(
            self,
            h: Helpers,
            walk_thresh: Union[int, float] = 1000,
            pt_stop_thresh: Union[int, float] = 750
            ):
        """
        Assign transport modes for every agent's trip

        Parameters
        ----------
        h : Helpers
            Dictionary with helper tables, loaded from input_data module.
            Table 'modal_split' is extracted from the dictionary.
        walk_thresh : Union[int, float], optional
            Threshold distance (m) between facilities beyond which walk mode
            is not chosen. The default is 1000.
        pt_stop_thresh : Union[int, float], optional
            Threshold distance (m) between facility and the closest pt stop
            beyond which pt mode is not chosen. The default is 750.

        Raises
        ------
        ValueError
            If passed negative threshold distances

        """
        if any(val < 0 for val in [walk_thresh, pt_stop_thresh]):
            raise ValueError('Distances must be positive')

        modes = []

        spat_ref = {
            prec: getattr(self, prec) for prec in SPATIAL_LEVELS_LIST
            }

        for i, trip in enumerate(self.trips):
            mode = choose_single_mode(self.category, self.activities[i],
                                      self.activities[i + 1], trip,
                                      self.pt_stop_walks[i],
                                      self.pt_stop_walks[i + 1], h,
                                      spat_ref, None,
                                      self.init_mode, walk_thresh,
                                      pt_stop_thresh)
            modes.append(mode)

        self.modes = self._fix_private_modes(modes)

    def _fix_private_modes(
            self,
            modes: List[str]
            ) -> List[str]:
        """
        Replaces modes, that would conflict with the private mode usage,
        e.g. if car is abandoned somewhere except for home.
        If no conflict is present or there are no private modes, returns
        unchanged list.

        Parameters
        ----------
        modes : List[str]
            List with preliminary modes to be checked and fixed

        Returns
        -------
        List[str]
            Modes with fixed private modes order

        """

        private_modes = [i for i, m in enumerate(modes) if m in PRIVATE_MODES]
        if not private_modes:
            return modes

        home_indices = [num for num, act in enumerate(self.activities)
                        if act in (v.acts['home'], v.acts['home'].upper())]

        if not home_indices:
            if 'car' in modes:
                return ['car' for _ in modes]
            return modes

        newmodes: List[str] = modes[:]

        # !!! TODO
        # Except walking if agent walks and returns to the same place,
        # e.g. from work to a restaurant for lunch and back

        for i, mode in enumerate(modes):
            if i not in private_modes:
                continue
            filt = list(filter(lambda x: i < x, home_indices))
            if filt:
                end_at = filt[0]
                end_index = home_indices.index(end_at)
            else:
                end_at = len(self.activities) - 1
                end_index = len(home_indices)

            if len(home_indices) == 1 and filt:
                start_at = 0
            elif len(home_indices) == 1 and not filt:
                start_at = home_indices[0]
            else:
                start_at = home_indices[end_index - 1]

            for index in range(start_at, end_at):
                newmodes[index] = mode

        return newmodes

    def pick_startend_link(
            self,
            links: gpd.GeoDataFrame = None
            ):
        """
        Assign closest allowed links to interact with facilities.
        # !!! bugged, figure out how MATSim treats agents with start and end

        Parameters
        ----------
        links : gpd.GeoDataFrame
            Filtered links in GeoDataFrame, that was extracted from
            MATSim network and had `nofacility` column equal to 0.
            If left None, self.links doesn't change (keeps being empty)

        Note
        ----
        - Only `car` mode is supported.

        """
        if isinstance(links, type(None)):
            return

        links_list = [None for _ in self.coords]
        for i, mode in enumerate(self.modes):
            if mode == 'car':
                for j, coord in enumerate([self.coords[i], self.coords[i + 1]]):
                    if coord not in v.links_cache:
                        v.links_cache[coord] = get_closest_link(coord, links)
                    links_list[i + j] = v.links_cache[coord]
        self.links = links_list

    def _lasting_by_act(
            self,
            h: Helpers,
            act: str
            ) -> timedelta:
        """
        Extract `mu_lasting` and `sd_lasting` from ``h``'s `times` table
        that corresponds with the activity (``act``) code, and get value
        of activity lasting from normal distribution with those parameters.

        Parameters
        ----------
        h : Helpers
            Dictionary with helper tables, loaded from input_data module.
            Table 'times' is extracted from the dictionary.
        act : str
            String of activity code, eg. 'wor'

        Returns
        -------
        timedelta
            Lasting of the activity

        """
        mu = h['times'].loc[h['times'].activity == act, 'mu_lasting']
        sdnorm = h['times'].loc[h['times'].activity == act, 'sd_lasting']
        last = timedelta(days=abs(np.random.normal(mu, sdnorm)[0]))
        return last

    def pick_lastings(
            self,
            h: Helpers
            ):
        """
        Calculate lastings of every activity based on ``h``'s `times` table
        with means and standard deviations of normal distribution.
        In case there are several occurencies of the same activity,
        that is affected by time splitting (``AFF_SPLIT``), its time is split
        by the number of occurencies, eg. if generated time for 'uni'
        is 6:05:20 and there are 2 occurencies, each of them will get an
        equal lasting of 3:02:40.
        The first and the last activity get zero timedelta lasting

        Parameters
        ----------
        h : Helpers
            Dictionary with helper tables, loaded from input_data module.
            Table 'times' is extracted from the dictionary.

        """
        visited_dict = {}
        lasts = []
        for i, act in enumerate(self.activities):
            if i != 0 and i != len(self.activities) - 1:
                if act in v.capacity_affected:
                    # if agent has several of these activities in a plan,
                    # picked lasting is divided by number of occurencies
                    if act not in visited_dict:
                        last = self._lasting_by_act(h, act)
                        visited_dict[act] = last / self.activities.count(act)
                    lasts.append(visited_dict[act])
                else:
                    lasts.append(self._lasting_by_act(h, act))
            else:
                lasts.append(timedelta(0))
        self.lastings = lasts

    def reduce_lastings(
            self,
            h: Helpers,
            max_lasting: float = v.lasting_limit
            ):
        """
        Evenly reduces lasting of every activity if time spend performing
        activities (time upon last arrival minus first departure time) exceeds
        specified ``max_lasting``. Calls ``pick_startend_times`` method
        after rearranging lastings.

        Parameters
        ----------
        h : Helpers
            Dictionary with helper tables, loaded from input_data module.
            Table 'times' is extracted from the dictionary.
        max_lasting : timedelta, optional
            Maximum length of agent's day

        """
        max_lasting_td = timedelta(hours=max_lasting)
        # !!! TODO replace with some kind of logit function or lin. regr.?
        if self.starttimes and self.endtimes:
            lastingsum = self.starttimes[-1] - self.endtimes[0]
            if lastingsum > max_lasting_td:
                triptime = sum(self.triptimes, timedelta())
                tripratio_orig = triptime / lastingsum
                tripratio_max = triptime / max_lasting_td

                lastingsum_red = lastingsum - lastingsum * tripratio_orig
                maxlasting_red = max_lasting_td - tripratio_max * max_lasting_td
                multiplyby = maxlasting_red / lastingsum_red

                self.lastings = [lt * multiplyby for lt in self.lastings]
                self.pick_startend_times(h)
        else:
            logging.warning(f'{str(self)} has no times to reduce')

    def pick_startend_times_strict(
            self,
            ):
        """
        Assumes that ``h``'s diaries are strict and that first start time is
        already set during preprocessing (e.g. time of first arrival to 'wor').
        Computes first end time (e.g. first departure from 'hom') by
        subtracting the time that the agent would need to get to 'wor'.
        Other start and end times and inferred from trip time and lastings of
        activities.

        """
        starts = []
        ends = []
        triptimes = []
        for i, act in enumerate(self.activities):
            if i == 0:
                triptime = self._get_triptime(0)
                starts = self.starttimes
                nextstart = self.starttimes[1]
                end = nextstart - triptime
                triptimes.append(triptime)
                ends.append(end)
            else:
                if i == 1 and self.activities[i - 1] == v.acts['home']:
                    triptime = triptimes[0]
                    start = starts[1]
                else:
                    triptime = self._get_triptime(i - 1)
                    start = ends[i - 1] + triptime
                    triptimes.append(triptime)
                    starts.append(start)
                if i != len(self.activities) - 1:
                    end = start + self.lastings[i]
                    ends.append(end)
        self.starttimes = starts
        self.endtimes = ends
        self.triptimes = triptimes

    def _get_triptime(
            self,
            tripnum: int
            ) -> timedelta:
        """
        Calculate travel time by the specified type of
        transport (self.modes[tripnum]) based on ``h``'s `speeds` table (m/min)

        Parameters
        ----------
        tripnum : int
            Number of agent's trip (technically, rather number of activity)

        Returns
        -------
        timedelta
            Travel time by the chosen mean of transport

        """
        trip = self.trips[tripnum]
        minutes = trip / v.speeds[self.modes[tripnum]]
        return timedelta(minutes=minutes)

    def pick_startend_times(
            self,
            h: Helpers
            ):
        """
        Calculate time of the start and the end of every activity, including
        lasting. In case of first activity being home, start time of the second
        activity is calculated before the end time of home activity.

        Parameters
        ----------
        h : Helpers
            Dictionary with helper tables, loaded from input_data module.
            Table 'times' is extracted from the dictionary.

        """
        starts = []
        ends = []
        triptimes = []
        for i, act in enumerate(self.activities):
            if i == 0:
                if act == v.acts['home']:
                    mu = h['times'].loc[h['times'].activity ==
                                        self.activities[1], 'mu_start']
                    sdnorm = h['times'].loc[h['times'].activity ==
                                            self.activities[1], 'sd_start']
                    triptime = self._get_triptime(0)
                    nextstart = timedelta(days=abs(np.random.normal(mu, sdnorm))[0])
                    end = nextstart - triptime
                    starts = [timedelta(0), nextstart]
                    triptimes.append(triptime)
                    ends.append(end)
                else:
                    mu = h['times'].loc[h['times'].activity ==
                                        self.activities[i + 1], 'mu_end']
                    sdnorm = h['times'].loc[h['times'].activity ==
                                            self.activities[i + 1], 'sd_end']
                    end = timedelta(days=abs(np.random.normal(mu, sdnorm)[0]))
                    starts.append(timedelta(0))
                    ends.append(end)
            else:
                if i == 1 and self.activities[i - 1] == v.acts['home']:
                    triptime = triptimes[0]
                    start = starts[1]
                else:
                    triptime = self._get_triptime(i - 1)
                    start = ends[i - 1] + triptime
                    triptimes.append(triptime)
                    starts.append(start)
                if i != len(self.activities) - 1:
                    end = start + self.lastings[i]
                    ends.append(end)
        self.starttimes = starts
        self.endtimes = ends
        self.triptimes = triptimes

    def _reorder_for_xml(self) -> Tuple[List[str], List[Tuple[float]],
                                        List[timedelta], List[str], List[str]]:
        """
        Reorder activities in case there is one of the activities has endtime
        that is later than the midnight of the next day, eg. ``timedelta(1)``.
        Activities from after mignight are put before the agent's start the day
        before, if they don't interfere with those activities.
        If some error happens, or there are no activities after midnight, the
        original lists are returned.

        Returns
        -------
        Tuple[List[str], List[Tuple[float]],
              List[timedelta], List[str], List[str]]
            A tuple of reformatted lists to replace the original ones

        """

        if not any([et >= timedelta(1) for et in self.endtimes]):
            return (self.activities, self.coords,
                    self.endtimes, self.modes, self.links)

        try:
            acts = deepcopy(self.activities)
            links = deepcopy(self.links)
            coords = deepcopy(self.coords)
            modes = deepcopy(self.modes)
            endtimes, new_order = [], []
            first_pos, last_sameday = 0, len(self.endtimes) - 1

            for n, endtime in enumerate(self.endtimes):
                if endtime < timedelta(1):
                    endtimes.append(endtime)
                    new_order.append(n)
                    last_sameday = n
                else:
                    endtime = timedelta(seconds=endtime.total_seconds() -
                                        timedelta(days=1).total_seconds())
                    if endtimes and endtime < self.endtimes[first_pos]:
                        endtimes.insert(first_pos, endtime)
                        new_order.insert(first_pos, n)
                        first_pos += 1
                    elif not endtimes:
                        endtimes.append(endtime)
                        new_order.append(n)

            dropped = set(range(len(self.endtimes))).symmetric_difference(set(new_order))
            for d in dropped:
                del coords[d + 1], modes[d]
                acts = acts[:d + 1] + acts[d + 2:]
                if links:
                    del links[d]
            # add last act from same day to beginning and reorder the rest
            modes = [modes[n] for n in new_order]
            acts = ([self.activities[last_sameday + 1]] + [acts[n + 1] for n in new_order])
            coords = [coords[n + 1] for n in new_order]
            coords.insert(0, self.coords[last_sameday])
            if links:
                links = [links[n] for n in new_order]
            return acts, coords, endtimes, modes, links
        except Exception:
            return self.activities, self.coords, self.endtimes, self.modes, self.links

    def prepare_xml_block(
            self,
            pers_id: Union[str, int],
            teleported: bool = False
            ):
        """
        Create agent xml block in MATSim format to write to xml of population.
        Resulting block is indented with two spaces. This xml block is written
        into agent's attribute ``self.xml_buffer``. Resulting block may stay
        empty, if there is nothing to write (eg. because of teleported modes).

        Parameters
        ----------
        pers_id : Union[str, int]
            Unique string to precisely identificate every particular agent
            later on. MATSim crashes, if agents don't have distinct IDs.
        teleported : bool, optional
            Whether to include modes `carpool`, `bike', `walk` into xml block.
            They are known to be teleported (not network) modes and are not
            written by default. If True, agents with these modes will still be
            written, resulting into larger input and output files, and implying
            longer MATSim processing times.

        """
        if (all(mode in ['bike', 'carpool', 'walk'] for mode in self.modes)
                and not teleported):
            return
        self.xml_buffer = StringIO()
        self.xml_buffer.write(f'  <person id="{pers_id}">\n')
        self.xml_buffer.write(
            create_attributes_string({
                'carAvail': self.car_avail,
                'subpopulation': self.population,
                'category': self.category,
                'region': self.region,
                'area': self.region,
                'district': self.district,
                'zone': self.zone
            })
        )
        self.xml_buffer.write('    <plan selected="yes">\n')

        acts, coords, endtimes, modes, links = self._reorder_for_xml()

        for i, act in enumerate(acts):

            x, y = coords[i]

            if i + 1 != len(acts):

                if i + 1 != len(modes):
                    if acts[i + 1] in (v.acts['cycling'], v.acts['cycling'].upper()):
                        modes[i] = 'bike'
                    if acts[i + 1] in (v.acts['walk'], v.acts['walk'].upper()):
                        modes[i] = 'walk'

                mode = modes[i]
                if mode in ['bike', 'carpool', 'walk'] and not teleported:
                    continue

                if self.links and self.links[i] is not None:
                    actrow = (
                        f'      <activity type="{act}" x="{x}"  y="{y}" '
                        f'link="{self.links[i]}" end_time="{td_to_str(endtimes[i])}" />\n')
                else:
                    actrow = (f'      <activity type="{act}" x="{x}"  y="{y}" '
                              f'end_time="{td_to_str(endtimes[i])}" />\n')
                self.xml_buffer.write(actrow)
                self.xml_buffer.write(f'      <leg mode="{mode}" />\n')
            else:
                if self.links:
                    actrow = f'      <activity type="{act}" link="{self.links[i]}" x="{x}"  y="{y}" />\n'
                else:
                    actrow = f'      <activity type="{act}" x="{x}"  y="{y}" />\n'
                self.xml_buffer.write(actrow)
        self.xml_buffer.write('    </plan>\n')
        self.xml_buffer.write('  </person>\n')

    def prepare_csv_row(
            self,
            pers_id: Union[str, int]
            ):
        """
        Create row for csv file, that is used in further population analysis.
        This row is written into agent's attribute ``self.csv_buffer``

        Parameters
        ----------
        pers_id : Union[str, int]
            Unique string to precisely identificate every particular agent
            later on.

        """
        self.csv_buffer = StringIO()
        self.csv_buffer.write(
            f'{pers_id};'
            f'{self.category};{"_".join(self.activities)};{self.init_mode};'
            f'{self.region};{self.area};'
            f'{self.district};{self.zone};')
        for i, act in enumerate(self.activities):

            x, y = self.coords[i]

            if i + 1 != len(self.activities):
                self.csv_buffer.write(
                    f'{self.facilities[i]};{x};{y};'
                    f'{self.gendists[i+1]};{self.trips[i]};{self.pt_stop_walks[i]};'
                    f'{self.modes[i]};{self.starttimes[i]};{self.endtimes[i]};')
            else:
                self.csv_buffer.write(f'{self.facilities[i]};{x};{y};'
                                      f';;{self.pt_stop_walks[i]};'
                                      f';{self.starttimes[i]}\n')

    def process(
            self,
            facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
            h: Helpers,
            use_links: bool = False,
            prefer_private: bool = True,
            abandon_pt: bool = False,
            include_teleported: bool = False
            ):
        """
        Process agent depending on types of passed data. Changes agent's data

        Parameters
        ----------
        facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
            Dictionary with (Geo)DataFrames, containing info about
            facilities for every available activity.
        h : Helpers
            Dictionary with helper tables, loaded from `input.data` module.
        use_links : bool, optional
            Whether to consider some links inaccessible. Requires MATSim
            network in helpers with `nofacility` attr. The default is False.
        prefer_private : bool, optional
            Once car, always car, or consider dropping pt. The default is True.
        abandon_pt : bool, optional
            Leave from pt, if trip is too long. The default is False.
        include_teleported : bool, optional
            Whether to generate XML block for walk/bike/carpool activities

        """
        if 'target_probabilities' in h:
            self.pick_dists_facilities_spatially(
                facilities, h
                )
        else:
            self.generate_dists(h)
            pick_facilities(
                self, facilities, h
                )  # !!! include into self?
            self.calculate_trips()
            self.stop_dists(h)
            self.pick_modes(h)

        if h['diaries'].type == 'strict':
            self.pick_startend_times_strict()
        else:
            self.pick_startend_times(h)
            self.pick_lastings(h)
            self.reduce_lastings(h)
        if use_links:
            self.pick_startend_link(h['net'])
        if prefer_private:
            self.prefer_private_mode(once_car_always_car=True,
                                     abandon_pt=abandon_pt)
        self.prepare_xml_block(self.info, teleported=include_teleported)
        self.prepare_csv_row(self.info)

    def show_trips(
            self,
            spat_unit: Literal[SPATIAL_LEVELS_LIST] = 'area'
            ) -> plt.Figure:
        """
        Show agent's trips using ``matplotlib``.

        Also adds a table with detailed description of the trips below.

        Parameters
        ----------
        spat_unit : Literal[SPATIAL_LEVELS_LIST], optional
            What spatial precision unit should be shown in columns `Origin`
            and `Destination`. The default is `area`.

        Raises
        ------
        RuntimeError
            If agent has incomplete data (coords, facilities...)

        Returns
        -------
        fig : plt.Figure
            Matplotlib Figure. If in Spyder, also sends plot into Plots pane.

        """
        fig, ax = plt.subplots()

        ag_info = (
            r"Agent $\bf{" + str(self.info).replace('_', r'\_') + "}$, "
            if self.info not in [None, 'None'] else 'Agent, '
            )
        ag_cat = r"category $\bf{" + str(self.category) + "}$"
        ax.set_title(rf'{ag_info}{ag_cat}')

        ax.get_xaxis().set_ticks([])
        ax.get_yaxis().set_ticks([])
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['bottom'].set_visible(False)
        ax.spines['left'].set_visible(False)

        table = []
        cols = ['From', 'To', 'Origin', 'Destination', 'Departure',
                'Arrival', 'Trip time', 'Mode', 'Length']
        colors = plt.cm.Dark2(np.linspace(0, 1, len(self.activities) - 1))
        seen = set()
        for num, act in enumerate(self.activities):
            try:
                if num > 0:
                    xs, ys = zip(self.coords[num - 1], self.coords[num])
                    ax.plot(xs, ys, color=(0, 0, 0, 0))  # plot invisible line
                    ax.annotate(
                        text=self.activities[num - 1] if self.coords[num - 1] not in seen else '',
                        xy=self.coords[num],
                        xytext=self.coords[num - 1],
                        arrowprops={'shrink': .05,
                                    'connectionstyle': 'arc3,rad=.1',
                                    'facecolor': colors[num - 1]}
                    )
                    table.append(
                        [f'{self.activities[num - 1]} ({self.facilities[num - 1]})',
                         f'{self.activities[num]} ({self.facilities[num]})',
                         f'{spat_unit} {self.spatial_references[num - 1][spat_unit]}',
                         f'{spat_unit} {self.spatial_references[num][spat_unit]}',
                         td_to_str(self.endtimes[num - 1]),
                         td_to_str(self.starttimes[num]),
                         td_to_str(self.starttimes[num] - self.endtimes[num - 1]),
                         self.modes[num - 1],
                         self.trips[num - 1]
                         ]
                        )
                    seen.add(self.coords[num - 1])
                else:
                    ax.text(*self.coords[num], s=act)
                    seen.add(self.coords[num])
            except IndexError:
                raise RuntimeError(
                    'Agent with incomplete data (coords, facilities...)'
                    )

        tab = ax.table(
            cellText=table,
            rowLabels=[f'   {n}   ' for n in range(1, len(self.activities))],
            rowColours=colors,
            colLabels=cols
        )
        tab.auto_set_column_width(col=list(range(len(cols))))
        return fig


def create_attributes_string(
        attributes: Optional[Dict[str, Any]] = None
) -> str:
    if not attributes:
        return ''
    attrs_string = '    <attributes>\n'
    for attribute, value in attributes.items():
        attrs_string += f'      <attribute name="{attribute}" class="java.lang.String">{value}</attribute>\n'
    attrs_string += '    </attributes>\n'
    return attrs_string


def alter_suburb_dist(
        last_coord: Tuple[float],
        gen_dist: Union[int, float],
        filtered: Union[gpd.GeoDataFrame, pd.DataFrame],
        outer_offset: Union[int, float] = v.cluster_dist_thresh,
        alter_thresh: Union[int, float] = v.reach_percentage
        ) -> float:
    """
    Add random distance in range from the city center to the farthest reachable
    point by agent's generated distance and possible threshold

    Parameters
    ----------
    last_coord : Tuple[float]
        x, y coordinates of agent's previous location
    gen_dist : Union[int, float]
        Generated distance
    filtered : Union[gpd.GeoDataFrame, pd.DataFrame]
        Activity table possibly filtered by indices
    outer_offset : Union[int, float], optional
        Positive or zero distance, that is added to generated distance
    alter_thresh : Union[int, float], optional
        Threshold triggering distance change

    Returns
    -------
    float

    """
    curr_dists = proj_distance_df(filtered, last_coord)
    try:
        farthest = curr_dists[curr_dists <= gen_dist + outer_offset].idxmax()
        enough = True
    except ValueError:
        farthest = curr_dists.idxmin()
        enough = False

    unreachable = curr_dists[curr_dists >= curr_dists[farthest]]
    # everything what is farther than farthest reachable point by condition

    # in case everything is reachable
    if len(unreachable) == 0 and enough:
        return gen_dist
    elif len(unreachable) == 0 and not enough:
        return curr_dists[farthest]

    ratio = len(unreachable) / len(filtered)
    # if unreachability is high, add random distance
    # in range from the closest point to the center
    if ratio >= alter_thresh:
        rng = random.uniform(0, filtered.loc[farthest, 'center_dist'])
        if enough:
            return gen_dist + rng
        return curr_dists[farthest] + rng
    # if not fitting contition, return unchanged gen_dist or closest point dist
    if enough:
        return gen_dist
    return curr_dists[farthest]


def alter_any_dist(
        last_coord: Tuple[float],
        gen_dist: Union[int, float],
        filtered: Union[gpd.GeoDataFrame, pd.DataFrame],
        outer_offset: Union[int, float] = v.cluster_dist_thresh,
        alter_thresh: Union[int, float] = v.reach_percentage,
        alter_thresh_abs: Union[int, float] = 5,
        max_increase_ratio: Union[int, float] = 0,
        max_increased_dist: Union[int, float] = 0
        ) -> float:
    """
    Add random distance in range from the farthest point of target spatial unit
    to the farthest reachable point by agent's generated distance and possible
    threshold

    Parameters
    ----------
    last_coord : Tuple[float]
        x, y coordinates of agent's previous location
    gen_dist : Union[int, float]
        Generated distance
    filtered : Union[gpd.GeoDataFrame, pd.DataFrame]
        Activity table possibly filtered by indices
    outer_offset : Union[int, float], optional
        Positive or zero distance, that is added to generated distance
    alter_thresh : Union[int, float], optional
        Threshold triggering distance change
    alter_thresh_abs : Union[int, float], optional
        Absolute count of available facilities to trigger alterring. NOT USED
    max_increase_ratio : Union[int, float], optional
        A ratio, by which the generated distance can increase. Default 0 - off.
        Should be more than 1. NOT USED YET
    max_increased_dist : Union[int, float], optional
        A maximum distance, that can be returned afted all operations.
        If resulting distance is bigger than this number, an original gen_dist
        is returned. NOT USED YET

    Returns
    -------
    float

    """
    curr_dists = proj_distance_df(filtered, last_coord)
    try:
        farthest = curr_dists[curr_dists <= gen_dist + outer_offset].idxmax()
        enough = True
    except ValueError:
        if len(curr_dists) == 0:
            return gen_dist
        farthest = curr_dists.idxmin()
        enough = False

    unreachable = curr_dists[curr_dists >= curr_dists[farthest]]
    # everything what is farther than farthest reachable point by condition

    # in case everything is reachable
    if len(unreachable) == 0 and enough:
        return gen_dist
    elif len(unreachable) == 0 and not enough:
        return curr_dists[farthest]

    ratio = len(unreachable) / len(filtered)
    # if unreachability is high, add random distance
    # in range from the closest point to the center
    if ratio >= alter_thresh:

        # !!! add azimuth maybe?
        farthest_coord = tuple(filtered.loc[farthest, ['x', 'y']].tolist())
        max_dist = proj_distance_df(filtered, farthest_coord).idxmax()
        max_dist_coord = tuple(filtered.loc[max_dist, ['x', 'y']].tolist())

        rng = random.uniform(0, proj_distance(farthest_coord, max_dist_coord))

        if enough:
            return gen_dist + rng
        return curr_dists[farthest] + rng
    # if not fitting contition, return unchanged gen_dist or closest point dist
    if enough:
        return gen_dist
    return curr_dists[farthest]


def get_places_cluster(
        filtered: Union[gpd.GeoDataFrame, pd.DataFrame],
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        next_act_l: str, gen_dist: Union[int, float],
        prev: Union[Tuple[float], List[float]],
        inner_offset: Union[int, float] = 0,
        outer_offset: Union[int, float] = v.cluster_dist_thresh,
        sample_size: int = 5
        ) -> Union[gpd.GeoDataFrame, pd.DataFrame]:
    """
    In case there are facilities of particular type (`next_act_l`), that have
    not null cluster ID and fall into a ring around generated distance
    (+-top/bottom limit), prefer those facilities. Points of clusters with
    bigger capacity have higher probability of being chosen, if intersected.
    If nothing falls into the intersection, input ``filtered``
    DataFrame is returned. If there are no clustered points in the
    intersection, all other ring intersected points are returned.

    Parameters
    ----------
    filtered : Union[gpd.GeoDataFrame, pd.DataFrame]
        DESCRIPTION.
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity.
    next_act_l : str
        Lower case code of activity
    gen_dist : Union[int, float]
        Generated distance, that tells how far agent should go for the activity
    prev : Union[Tuple[float], List[float]]
        Previous visited x, y coordinates to measure distance from.
    inner_offset : Union[int, float]
        Positive or zero distance, that is deducted from generated distance
    outer_offset : Union[int, float]
        Positive or zero distance, that is added to generated distance
    sample_size : int
        Max number of points in a DataFrame of the picked cluster

    Returns
    -------
    Union[gpd.GeoDataFrame, pd.DataFrame]
        DataFrame with points, that fulfill clustering conditions

    """

    cldists = proj_distance_df(filtered, prev)
    clthresh = cldists[(cldists < (gen_dist + outer_offset)) &
                       (cldists >= (gen_dist - inner_offset))]
    if len(clthresh) == 0:
        return filtered
    clthresh = clthresh.sort_values()
    clfiltered = filtered.loc[clthresh.index]

    clusts = [cl for cl in clfiltered['cluster_id'].unique().tolist()
              if cl != 0 and not pd.isnull(cl)]
    if len(clusts) == 0 or len(clfiltered) == 0:
        return filtered
    caps = {
        cl: facilities[next_act_l][facilities[next_act_l]['cluster_id'] == cl]['capacity'].sum()
        for cl in clusts
    }
    caps = {
        cl: cap for cl, cap in caps.items()
        if not pd.isnull(cap) and cap != 0
    }

    if not caps:
        return clfiltered

    keys, tcap = zip(*caps.items())
    stcap = sum(tcap)
    tcapnorm = [cap / stcap for cap in tcap]
    pickcl = np.random.choice(keys, p=tcapnorm)

    pre_out = clfiltered[clfiltered['cluster_id'] == pickcl]
    if len(pre_out) == 0:
        return clfiltered
    return pre_out.sample(min(sample_size, len(pre_out)))


def group_upcoming_acts(
        acts: List[str],
        n: int = 2
        ) -> Tuple[bool, List[Tuple[str]]]:
    """
    Stack activities into a list of tuples of length ``n``. If first activity 
    is not home, it is automatically added, and the flag ``remove_first``
    turns into True. If there is only one activity in group, such group is
    not included in the results. In either cases missing activities are
    compensated by None.

    Parameters
    ----------
    acts : List[str]
        List containing string codes of agent's activities
    n : int, optional
        An integer describing how many activities are in each group

    Returns
    -------
    remove_first : bool
        Flag signalizing about removing of the first pair after all operations
    groupped : List[Tuple[str]]
        Tuples of string activities codes (from - to) in a list

    """
    groupped = []
    remove_first = acts[0] != v.acts['home']
    if remove_first:
        acts = [v.acts['home']] + acts
    for i, act in enumerate(acts):
        if i == 0 and act != v.acts['home']:
            remove_first = True
        pregroup = acts[i: i + n]
        prelen = len(pregroup)
        if prelen == 1:
            break
        elif prelen < n:
            pregroup = pregroup + [None] * (n - prelen)
        groupped.append(pregroup)

    return remove_first, groupped


def find_in_modal_split_table(
        cat: str,
        h: Helpers,
        prec_value1: str,
        prec_value2: str = None,
        allowed_modes: Union[list, tuple, set] = MODAL_SPLIT_MODES,
        allow_zero_probs: bool = True
        ) -> str:
    """
    Pick agent's mode based on his category, spatial references of the current
    and the next activity. Modes can also be limited (e.g. exclude car or pt).

    Parameters
    ----------
    cat : str
        Code of agent's socioeconomic category
    h : Helpers
        Dictionary with helper tables, loaded from `input.data` module.
    prec_value1 : str
        Spatial reference value of current activity, e.g. if `modal_split`'s
        precision is `area`, then precision may be any of its valid values
        (in case of Brno, areas range is from '1' to '8').
    prec_value2 : str, optional
        Spatial reference value of next activity, e.g. if `modal_split_target`'s
        precision is `area`, then precision may be any of its valid values
        (in case of Brno, areas range is from '1' to '8') The default is None.
        If spatial references do not contain `_target` in `modal_split` table,
        or this parameter is None, next activity's spatial reference is not
        taken into account.
    allowed_modes : Union[list, tuple, set], optional
        An iterable containing modes, that will be used for mode probabilities.
        If not full set of modes provided, probabilities are recalculated.
        The default equals to MODAL_SPLIT_MODES constant.
    allow_zero_probs : bool, optional
        Should all-zero probabilities be encountered, pick random mode.
        The default is True.

    Raises
    ------
    ValueError
        When there are no specified combination of category and spatial refs or
        when modes are unsupported or empty.

    Returns
    -------
    str
        Picked mode

    """

    if any((m not in MODAL_SPLIT_MODES) for m in set(allowed_modes)) or len(allowed_modes) == 0:
        raise ValueError('One or more values in allowed_modes is unsupported')

    modechoice = h['modal_split'][
        (h['modal_split'].category == cat) &
        (h['modal_split'][h['modal_split'].precision] == prec_value1)
        ]
    if prec_value2 is not None and h['modal_split'].target_precision is not None:
        col = f'{h["modal_split"].target_precision}_target'
        modechoice = modechoice[modechoice[col] == prec_value2]

    if len(modechoice) == 0:
        raise ValueError(
            f"No data for category '{cat}' from "
            f"{h['modal_split'].precision} {prec_value1}" +
            ('' if prec_value2 is None else
             f' to {h["modal_split"].target_precision} {prec_value2}')
        )

    modelist = list(allowed_modes)
    probs = modechoice[modelist].iloc[0]

    if allowed_modes != MODAL_SPLIT_MODES:
        psum = probs.sum()
        if psum == 0 and not allow_zero_probs:
            raise ValueError(
                'Attempted to perform a choice of mode with all-zero '
                f'probabilities. Provided category {cat}, '
                f'from {h["modal_split"].precision} {prec_value1} '
                f'to {h["modal_split"].target_precision} {prec_value2} '
                f'with allowed modes {modelist}'
            )
        elif psum == 0 and allow_zero_probs:
            logging.warning(
                'Attempted to perform a choice of mode with all-zero '
                f'probabilities. Provided category {cat}, '
                f'from {h["modal_split"].precision} {prec_value1} '
                f'to {h["modal_split"].target_precision} {prec_value2} '
                f'with allowed modes {modelist}. Making all probabilities '
                'equal, because allow_zero_probs is True'
            )
            probs[:] = 1
        probs = probs / probs.sum()
    mode = np.random.choice(modelist, p=probs)
    return mode


def choose_single_mode(
        cat: str,
        act1: str,
        act2: str,
        triplen: Union[int, float],
        stopwalk1: Union[int, float],
        stopwalk2: Union[int, float],
        h: Dict[str, Union[pd.DataFrame, gpd.GeoDataFrame]],
        spat_ref1: Dict[str, str],
        spat_ref2: Dict[str, str] = None,
        init_mode: str = None,
        walk_thresh: Union[int, float] = 1000,
        pt_stop_thresh: Union[int, float] = 750
        ) -> str:
    """
    Pick transport mode for trip with specified parameters. Supports
    choice based both on origin and destination spatial references.

    Mode type choice

    - If beeline distance between two activities is less than walk_thresh,
      then the agent will pick walking, but only if init_mode wasn't car,
      because people usually don't abandon their vehicles mid-way.
    - If distance is greater than walk_thresh:
        - If the initial mode was public transport, then it's kept,
          if pt stop is available (is closer than pt_stop_thresh). If not,
          then is picked one of modes, that is not public transport
          or walk (or car, if agent doesn't have a car license)
        - If the initial mode was car, it is preserved

    Parameters
    ----------
    cat : str
        Role of agent - e (employed), mss (middle school student), etc...
    act1 : str
        Activity type, where agent departs from
    act2 : str
        Activity type, where agent arrives to
    triplen : Union[int, float]
        Beeline distance between activities
    stopwalk1 : Union[int, float]
        Beeline distance to the closest public transport stop from act1
    stopwalk2 : Union[int, float]
        Beeline distance to the closest public transport stop from act2
    h : Dict[str, Union[pd.DataFrame, gpd.GeoDataFrame]]
        Dictionary with helper tables, loaded from input_data module.
        Table 'modal_split' is extracted from the dictionary.
    spat_ref1 : Dict[str, str]
        Spatial reference of act1, 'modal_split' precision is used
    spat_ref2 : Dict[str, str], optional
        Spatial reference of act2, 'modal_split_target' precision
        is used. Keep None to ignore this spatial reference
    init_mode : str, optional
        Initilally assigned mode for agent, that is used always, where possible
        If not assigned yet, keep None - will be assigned anyway
    tripnum : int
        Number of agent's trip (technically, rather number of activity)
    walk_thresh : Union[int, float], optional
        Threshold distance (m) between facilities beyond which walk mode
        is not chosen. The default is 1000.
    pt_stop_thresh : Union[int, float], optional
        Threshold distance (m) between facility and the closest pt stop
        beyond which pt mode is not chosen. The default is 750.

    Returns
    -------
    str
        Chosen mode for the specified trip

    """

    # print(cat, act1, act2, triplen, stopwalk1, stopwalk2, spat_ref1, spat_ref2, init_mode)
    if act2 in (v.acts['cycling'], v.acts['cycling'].upper()):
        # for activities that are performed only with bike mode
        return 'bike'
    elif act2 in (v.acts['walk'], v.acts['walk'].upper()):
        # for activities that are performed only with walk mode
        return 'walk'
    if triplen > walk_thresh and (stopwalk1 < pt_stop_thresh and
                                  stopwalk2 < pt_stop_thresh):
        # too far to walk, but both pt stops are reachable
        if init_mode is None or init_mode == 'walk':
            # if no initial mode set yet, do so, if it's not walk
            allowed = ['car', 'pt', 'carpool', 'bike']
            return find_in_modal_split_table(cat, h,
                                             spat_ref1[h['modal_split'].precision],
                                             spat_ref2[h['modal_split'].target_precision],
                                             allowed)
        # whatever the mode is, if it's not walk, keep using it
        return init_mode
    elif triplen > walk_thresh and (stopwalk1 > pt_stop_thresh or
                                    stopwalk2 > pt_stop_thresh):
        # both pt stops are far away and walking is too far either
        if cat not in ['ess', 'mss']:
            if init_mode != 'car':
                # pt is too far away, walk is too long,
                # cars are allowed, but are not the initial mode:
                # use probabilities of modes not involving pt or walk
                # in the spatial unit where does the agent come from
                allowed = ['car', 'carpool', 'bike']
                return find_in_modal_split_table(cat, h,
                                                 spat_ref1[h['modal_split'].precision],
                                                 spat_ref2[h['modal_split'].target_precision],
                                                 allowed)
            # pt is too far away, walk is too long,
            # cars are allowed, and are the initial mode:
            # stick to the initial mode (car)
            return 'car'
        else:
            # pt is too far away, walk is too long,
            # cars are not allowed for minors:
            # use probabilities of modes not invoving any of these
            # in the spatial unit where does the agent come from
            allowed = ['carpool', 'bike']
            return find_in_modal_split_table(cat, h,
                                             spat_ref1[h['modal_split'].precision],
                                             spat_ref2[h['modal_split'].target_precision],
                                             allowed)
    elif triplen < walk_thresh:
        # walk is not long: walk there!
        return 'walk'
    # any other case: use probabilities of modes not invoving walk, pt or car
    allowed = ['carpool', 'bike']
    return find_in_modal_split_table(cat, h,
                                     spat_ref1[h['modal_split'].precision],
                                     spat_ref2[h['modal_split'].target_precision],
                                     allowed)


def generate_dist_spatially(
        h: Helpers,
        curr_act: str,
        next_act: str,
        curr_spat_ref: Dict[str, str]
        ) -> Tuple[float, str]:
    """
    Generate distance for agent based on activities and their spatial reference

    Parameters
    ----------
    h : Dict[str, Union[pd.DataFrame, gpd.GeoDataFrame]]
        Dictionary with helper tables, loaded from input_data module.
        Tables 'distances' and 'dist_probabilities' are extracted from the
        dictionary.
    curr_act : str
        Current activity string code
    next_act : str
        Next activity string code
    curr_spat_ref : Dict[str, str]
        Current activity spatial references, that are used to estimate the next
        spatial reference using probabilities

    Returns
    -------
    dist : float
        Distance in meters, generated from Weibull distribution
    next_spat_ref : str
        Next spatial reference with precision of 'dist_probabilities'

    """
    # as way home is never generated, home act is considered a visit
    if next_act in [v.acts['home'], v.acts['home'].upper()]:
        next_act = v.acts['visit']
    curr_act = curr_act.lower()
    next_act = next_act.lower()
    acts_comb = f'{curr_act}_{next_act}'
    prob_col = acts_comb if acts_comb in h['target_probabilities'].columns else next_act
    dist_col = acts_comb if f'{acts_comb}_scale' in h['distances'].columns else next_act
    cond_prob = h['target_probabilities'][h['target_probabilities'].precision] == curr_spat_ref[h['target_probabilities'].precision]

    prob_probs = h['target_probabilities'].loc[cond_prob, prob_col]
    if prob_probs.sum() == 0:
        prob_probs = h['target_probabilities'].loc[cond_prob, next_act]
    prob_vals = h['target_probabilities'].loc[cond_prob, f"{h['target_probabilities'].target_precision}_target"]
    next_spat_ref = np.random.choice(prob_vals, p=prob_probs)

    cond_dist = (
        h['distances'][h['distances'].precision] == curr_spat_ref[h['distances'].precision]) & (
            h['distances'][f"{h['target_probabilities'].target_precision}_target"] == next_spat_ref
            )
    dist_scale = h['distances'][cond_dist][f'{dist_col}_scale'].item()
    if dist_scale == 0:
        dist_col = next_act
        dist_scale = h['distances'][cond_dist][f'{dist_col}_scale'].item()
    dist_shape = h['distances'][cond_dist][f'{dist_col}_shape'].item()
    dist = np.random.weibull(dist_shape) * dist_scale
    return dist, next_spat_ref


def csv_header(
        maxlen: int = 5,
        file: Union[str, Path] = 'population.csv'
        ):
    """
    Write (with replacement) a csv file for analysis containing only header

    Parameters
    ----------
    maxlen : int, optional
        Maximum number of activities, so the function knows, how many times it
        should repeat the columns. The default is 5.
    file : Union[str, Path], optional
        Path to the csv. The default is 'population.csv' of script folder.

    """
    header = 'pers_id;category;activities;init_mode;region;area;district;zone;'
    for i in range(maxlen):
        header += (f'facility{i};x{i};y{i};gendist{i};trip{i};pt_stop_walk{i};'
                   f'mode{i};starttime{i};endtime{i};')
    header = header[:-1]
    header += '\n'
    with open(file, 'w') as the_file:
        the_file.write(header)


def save_csv(
        agents_list: List[Agent],
        file: Union[str, Path] = 'population.csv'
        ):
    """
    Append agent's `csv_buffer`s to the specified file

    Parameters
    ----------
    agents_list : List[Agent]
        List with agents to write
    file : Union[str, Path], optional
        Path to the csv. The default is 'population.csv'.

    """
    buff = StringIO()
    for ag in agents_list:
        buff.write(ag.csv_buffer.getvalue())
    with open(file, 'a+') as the_file:
        the_file.write(buff.getvalue())
    buff.close()


def write_agents(
        agents_list: List[Agent],
        file: Union[str, Path],
        including_start_end: bool = False
):
    """
    Write agents in MATSim xml format from `xml_buffer` to the specified file.

    CHOOSING .GZ SUFFIX IN FILE WILL OVERWRITE WHATEVER THE FILE WAS!
    DON'T USE IN MULTIPLE THREADS AT ONCE WITH .GZ OR `including_start_end`!

    Parameters
    ----------
    agents_list : List[Agent]
        List of processed agents
    file : str, optional
        Path to output file. If has `.gz` suffix, file is compressed.
    including_start_end : bool, optional
        Whether to write agents including start and end of the XML file.
        The default is False.

    """

    if Path(file).suffix.endswith('.gz'):
        mode = 'wt'
        open_func = gzip.open
    else:
        mode = 'w' if not including_start_end else 'a+'
        open_func = open
    with open_func(file, mode=mode, encoding='utf-8') as f:
        if including_start_end:
            sstring = get_pop_start_string()
            f.write(sstring)
        for ag in agents_list:
            f.write(ag.xml_buffer.getvalue())
        if including_start_end:
            estring = get_pop_end_string()
            f.write(estring)


def get_closest_link(
        coord: Union[Tuple[float], List[float]],
        links: Union[pd.DataFrame, gpd.GeoDataFrame]
        ) -> str:
    """
    Get closest link to the specified coordinate, where it's allowed to spawn

    Parameters
    ----------
    coord : Union[Tuple[float], List[float]]
        Iterable with lon and lat of point
    links : Union[pd.DataFrame, gpd.GeoDataFrame]
        DataFrame of the links, that have column `nofacility` equal to 0

    Returns
    -------
    str
        String ID of the closest link

    """
    minid = links.distance(Point(coord)).idxmin()
    return links.loc[minid, 'link_id']


def get_pop_start_string() -> str:
    pop_start = (
        '<?xml version="1.0" ?>\n'
        '<!DOCTYPE population SYSTEM '
        '"http://www.matsim.org/files/dtd/population_v6.dtd">\n'
        '<population>\n'
    )
    return pop_start


def get_pop_end_string() -> str:
    return '</population>'


def start_pop_writer(
        pop_file: Union[str, Path] = 'population.xml'
        ):
    """
    Start (with replacement) an xml file for MATSim

    Parameters
    ----------
    pop_file : Union[str, Path], optional
        Path to the xml file. The default is 'population.xml'.

    """
    with open(pop_file, 'w') as f_write:
        f_write.write(get_pop_start_string())


def end_pop_writer(
        pop_file: Union[str, Path] = 'population.xml'
        ):
    """
    Write last tag to enclose population

    Parameters
    ----------
    pop_file : Union[str, Path], optional
        Path to the xml file. The default is 'population.xml'.

    """
    with open(pop_file, 'a+') as f_write:
        f_write.write(get_pop_end_string())


def get_pt_stop_walk(
        coord: Union[List[float], Tuple[float]],
        h: Helpers
        ) -> float:
    """
    Get the closest stop beeline distance in meters to the point.

    Parameters
    ----------
    coord : Union[List[float], Tuple[float]]
        Iterable with lon and lat of point
    h : Helpers
        Dictionary with helper tables, loaded from input_data module.
        Tables 'distances' and 'target_probabilities' are extracted from the
        dictionary.

    Returns
    -------
    float

    """
    return proj_distance_df(h['stops'], coord).min()


def get_spat_ref_dict(
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        act: str,
        fid: str
        ) -> Dict[str, str]:
    """
    Get spatial references dictionary of the specified facilities

    Parameters
    ----------
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity.
    act : str
        Activity code
    fid : str
        Facility ID, typically in `facility` column

    Returns
    -------
    Dict[str, str]
        Dictionary with keys `region`, `area`, `district`, `zone`

    """
    return facilities[act].loc[facilities[act]['facility'] == fid, SPATIAL_LEVELS_LIST].iloc[0].to_dict()


def pick_facilities(
        agent: Agent,
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        h: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        ):
    """
    Pick facilities for agent's diary, not taking spatial aspect into account.
    # !!! DEPRECATED, use ``agent.pick_dists_facilities_spatially()``

    Parameters
    ----------
    agent : Agent
        DESCRIPTION.
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity.
    h : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with helper tables, loaded from input_data.py.

    Returns
    -------
    None

    """
    fclts = []
    coords = []
    visited_dict = {}
    lastact = None

    for i, act in enumerate(agent.activities):
        gen_dist = agent.gendists[i]

        if act in visited_dict and act in v.capacity_affected and act != lastact:
            fclt, coord = visited_dict[act]
            fclts.append(fclt)
            coords.append(coord)
            continue

        if act == v.acts['home']:
            fclts.append(agent.home_facility)
            coords.append(agent.home_geom)
            continue

        reduce = must_reduce(act)
        isup = act.isupper()

        if act.lower() in [v.acts['worktrip'], v.acts['citylog'],
                           v.acts['other'],  v.acts['visit']]:
            if act.lower() == v.acts['visit']:
                act = v.acts['home']
            else:
                act = np.random.choice([f for f in facilities.keys()
                                        if f.lower() not in v.exclude_foster])
            if isup:
                act = act.upper()
            reduce = False

        pre_coord = None if i == 0 else coords[-1]
        if act in (v.acts['walk'], v.acts['walk'].upper(),
                   v.acts['cycling'], v.acts['cycling'].upper()):
            fclt, coord = agent.activities[i - 1], pre_coord
        else:
            fclt, coord = pick_any_place(
                facilities, act, gen_dist, h, pre_coord, reduce
            )
        fclts.append(fclt)
        coords.append(coord)

        if act not in visited_dict:
            visited_dict[act] = (fclt, coord)

        lastact = act

    agent.facilities = fclts
    agent.coords = coords


def pick_any_place(
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        act: str,
        gen_dist: Union[int, float],
        h: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        coord: Tuple[float],
        reduce: bool = False,
        extended: bool = False) -> Tuple[str, Tuple[float], Dict[str, str]]:
    """
    Pick facility by its code and optionally indices, not concerning spatial
    aspect.

    Parameters
    ----------
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity.
    act : str
        String code of desired activity
    gen_dist : Union[int, float]
        Generated distance to look for facility
    h : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with helper tables, loaded from input_data.py
    coord : Tuple[float]
        x, y coordinates of last visited point
    reduce : bool, optional
        Whether to reduce picked facility's capacity. The default is False.
    extended : bool, optional
        Whether to include spatial dictionary to output. The default is False.

    Returns
    -------
    Tuple[str, Tuple[float], Dict[str, str]]
        Picked facility ID, its coordinates and optionally spatial dictionary
        If `extended` parameter is ``True``, tuple length is 3, otherwise is 2

    """
    act_l = act.lower()
    filtered = include_indices(facilities, h, act_l)
    if not extended:
        facility_id, coords = get_min_diff(
            facilities, act_l, gen_dist, coord, reduce, filtered
        )
        return facility_id, coords
    else:
        facility_id, coords, spat_dict = get_min_diff(
            facilities, act_l, gen_dist, coord, reduce, filtered, extended
        )
        return facility_id, coords, spat_dict


def must_reduce(
        act: str
        ) -> bool:
    """
    Whether to reduce capacity of activity's facility. Capacity isn't reduced,
    if it's not in a list of affected activities or if its code is in upper
    case, meaning escorting trip, not actually visiting

    Parameters
    ----------
    act : str
        String code of activity

    Returns
    -------
    bool

    """
    if act in v.capacity_affected:
        return True
    elif act.isupper() or act not in v.capacity_affected:
        return False
    return True


def include_indices(
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        h: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        act_l: str,
        prec_val: str = None,
        ignore_index: bool = False
        ) -> Union[gpd.GeoDataFrame, pd.DataFrame]:
    """
    Try to select facilities by indices, if any are available for the specified
    activity and if requested. Respects spatial aspect, if needed.

    Parameters
    ----------
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity.
    h : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with helper tables, loaded from input_data.py.
        Table `indices`
    act_l : str
        **Lower case** (!) code of activity
    prec_val : str, optional
        If None, doesn't consider spatial precision level. If passed,
        must be a string code of PRECISION[`target_probabilities`] level.
        The default is None.
    ignore_index : bool, optional
        Indexing is omitted if ``prec_val`` is not None. The default is False.

    Raises
    ------
    RuntimeError
        Is thrown, if there are no facilities with picked index from `indices`

    Returns
    -------
    filtered : Union[gpd.GeoDataFrame, pd.DataFrame]
        Table of specified activity's facilities with applied filters

    """
    if prec_val is not None:
        filtered = facilities[act_l][facilities[act_l][h['target_probabilities'].target_precision] == prec_val]
        if ignore_index:
            return filtered
    else:
        filtered = facilities[act_l]
    indices = h['indices'][h['indices'].activity == act_l].copy()
    if len(indices) > 0:
        avail_idx = set(filtered['index'].unique())
        if set(indices['index']) != avail_idx:
            indices = indices[indices['index'].isin(avail_idx)]
            indices['prob'] = indices['prob'] / indices['prob'].sum()
        ind = np.random.choice(indices['index'], size=1,
                               replace=True, p=indices['prob']).item()
        filtered = filtered[filtered['index'] == ind]
        if len(filtered) == 0:
            raise RuntimeError(
                f'No {act_l} facilities with index {ind}, act {act_l}')
    return filtered


def include_relations(
        filtered: Union[gpd.GeoDataFrame, pd.DataFrame],
        h: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        act_l: str,
        spat_ref: Dict[str, str]
        ) -> Union[gpd.GeoDataFrame, pd.DataFrame]:
    """
    Additional filter by activity, depending on area where agent is from
    (or where he/she currently is) and the probabilities of available
    E.g. after first filter there are only `city` facilities, but the
    `relations` table specifies `area`s of all `region`s. So it normalizes
    probabilities based on the available facilities' `area`s

    Parameters
    ----------
    filtered : Union[gpd.GeoDataFrame, pd.DataFrame]
        Facilities left after indices and `target_probabilities` filter
    h : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with helper tables, loaded from input_data.py.
        Table `relations`
    act_l : str
        **Lower case** (!) code of activity
    spat_ref : Dict[str, str]
        Dictionary of spatial reference of a facility, where agent currently
        is or where is his home facility

    Returns
    -------
    Dict[str, str]

    """
    # after indices and spatial filtering
    if 'relations' in h:

        if act_l not in set(h['relations']['activity']):
            return filtered

        relations = h['relations'][h['relations']['activity'] == act_l]
        avail_spat_units = filtered[relations.target_precision].unique()
        targ = relations.target_precision + '_target'
        relations = relations[
            (relations[relations.precision] == spat_ref[relations.precision]) &
            (relations[targ].isin(avail_spat_units))
            ]
        normalized = relations['prob'] / relations['prob'].sum()
        sp_unit = np.random.choice(relations[targ], p=normalized)
        filtered = filtered[filtered[relations.target_precision] == sp_unit]
    return filtered


def get_min_diff(
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        act: str,
        gen_dist: Union[int, float],  # !!! optimize
        xycoords: Tuple[float],
        reduce: bool,
        facility_df: Union[gpd.GeoDataFrame, pd.DataFrame],
        extended: bool = False,
        fail_on_error: bool = False,
        closer_to_home: bool = False,
        home_coord: Tuple[float] = None,
        prev_act: str = None,
        next_act: str = None
        ) -> Union[Tuple[str, Tuple[float, float], Dict[str, str]],
                   Tuple[str, Tuple[float, float]]]:
    """
    Returns info about the facility, which has the smallest difference of
    distance between last visited coordinates and generated distance among
    such of other facilities.

    Parameters
    ----------
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity.
    act : str
        String code of activity.
    gen_dist : Union[int, float]
        Generated beeline distance to compare real distances to
    xycoords : Tuple[float]
        x, y coordinates of last visited point
    reduce : bool, optional
        Whether to reduce picked facility's capacity. The default is False.
    facility_df : Union[gpd.GeoDataFrame, pd.DataFrame]
        Table of specified activity's facilities with applied filters
    extended : bool, optional
        Whether to include spatial dictionary to output. The default is False.
    fail_on_error : bool, optional
        If no distances found, raise ``RuntimeError``. The default is False.
    home_coord : Tuple[float], optional
        Coordinates of home facility.
        Must be provided if ``closer_to_home`` is True.
    prev_act : str, optional
        Code of previous act. Is checked whether it *IS NOT* home.
    next_act : str, optional
        Code of the next act. Is checked, whether it *IS* home.

    Raises
    ------
    RuntimeError
        If no available facilities found within specified table or if
        not enough arguments.

    Returns
    -------
    Union[Tuple[str, Tuple[float], Dict[str, str]], Tuple[str, Tuple[float]]]
        Tuple of 2 or 3 elements

    """
    if closer_to_home and home_coord is None:
        raise RuntimeError(
            'When closer_to_home is True, home_coord must be provided'
            )

    if xycoords is None:
        pick = facility_df.index
    else:
        dists = proj_distance_df(facility_df, xycoords)
        diffs = (dists - gen_dist)  # .abs() ?
        diffs_weighted = diffs
        if act in v.centrality_affected:
            center = (facility_df['center_dist'] /
                      facility_df['center_dist'].max())
            diffs_weighted = diffs + diffs * center
        if act in v.capacity_weight_affected:
            weight = facility_df['capacity'] / facility_df['capacity'].max()
            diffs_weighted -= diffs * weight * 0.5
        if closer_to_home and prev_act != v.acts['home'] and next_act == v.acts['home']:
            next_to_home = proj_distance_df(facility_df, home_coord)
            curr_to_next = dists
            curr_to_home = proj_distance(xycoords, home_coord)
            homediff = next_to_home + curr_to_next - curr_to_home
            diffs_weighted += diffs * (homediff / homediff.max())

        diffs_weighted = diffs_weighted.abs()  # !!! no abs maybe
        check = diffs_weighted.min()
        # check = diffs_weighted[diffs_weighted <= 0].max()
        # if pd.isnull(check):
        #     check = diffs_weighted[diffs_weighted > 0].min()
        pick = diffs_weighted[diffs_weighted == check].index

    try:
        facility_index = random.choice(pick)
    except IndexError:
        logging.warning(f'Empty sample, activity: {act}, '
                        f'reduce: {reduce}, gen_dist: {gen_dist}')

        if not fail_on_error:
            # next time, if function fails even with
            # all facilities of type, throws an error
            return get_min_diff(
                facilities, act, gen_dist,
                xycoords, reduce, facilities[act],
                extended=extended,
                fail_on_error=True,
                closer_to_home=closer_to_home,
                home_coord=home_coord,
                prev_act=prev_act,
                next_act=next_act
            )
        raise RuntimeError(f'Search on empty {act} sample is unsuccessfull')

    row = facility_df.loc[facility_index]
    coords = row['x'], row['y']
    if reduce:
        reduce_capacity(act=act, fid=row.name, facilities=facilities)
    if not extended:
        return row['facility'], coords
    return row['facility'], coords, row[SPATIAL_LEVELS_LIST].to_dict()


def reduce_capacity(
        act: str,
        fid: str,
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        ):
    """
    Reduce capacity of facility if it has more than 2 spaces left, otherwise
    drop row completely. All changes are made in place.

    Parameters
    ----------
    act : str
        String code of activity
    fid : str
        String ID of facility
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity.

    """
    cap = facilities[act].at[fid, 'capacity'].item()
    if cap > 1:
        facilities[act].at[fid, 'capacity'] -= 1
    else:
        facilities[act].drop(fid, inplace=True)


def report_progress(
        path: Union[str, Path] = None,
        progress: float = .0,
        clean: bool = False
):
    if path is None:
        if not CACHE_FOLDER.exists():
            try:
                CACHE_FOLDER.mkdir(parents=True)
            except Exception:
                return
        path = CACHE_FOLDER / 'agents.progress'
    else:
        path = Path(path)
    try:
        with path.open(mode='w' if clean else 'a') as f:
            f.write(f'{progress}\n')
    except Exception:
        return


def check_capacity_sufficiency(
        agents_list: List[Agent],
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        action_on_lacking_capacity: Literal['error', 'warn', 'increase'] = 'error',
        reserved_ratio: float = 0.1
):
    """
    Check possible lacking capacity before processing start.

    Parameters
    ----------
    agents_list : List[Agent]
        List of Agent objects.
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity.
    action_on_lacking_capacity : Literal['error', 'warn', 'increase'], optional
        What to do, if capacity of some activity's facilities is potentially
        insufficient:
            `error`: raise RuntimeError;
            `warn`: just show a warning, but keep processing;
            `increase`: try to estimate needed capacities.
        The default is 'error'.
    reserved_ratio : float, optional
        Ratio to keep reserved (in range from 0 to 1). The default is 0.1.

    Raises
    ------
    ValueError
        If ``reserved_ratio`` is out of range
    RuntimeError
        If ``action_on_lacking_capacity`` is `error` and some capacity lacks

    """
    if not 0 <= reserved_ratio <= 1:
        raise ValueError('reserved_ratio must be in range from 0 to 1')

    needed_capacities = {
        act: 0 for act in v.capacity_affected
        if act in facilities
        }
    actual_capacities = {
        act: facilities[act]['capacity'].sum() for act in v.capacity_affected
        if act in facilities
        }
    for agent in agents_list:
        seen = set()
        for act in agent.activities:
            if act in needed_capacities and act not in seen:
                needed_capacities[act] += 1
                seen.add(act)

    fail = False
    for act, cap in needed_capacities.items():
        needed_capacity_with_reserve = round(cap + cap * reserved_ratio)
        if actual_capacities[act] <= needed_capacity_with_reserve:
            fail = True
            logging.warning(
                f'Facilities of "{act}" activity potentially have insufficient'
                f' capacity - actual {actual_capacities[act]}'
                f' vs. needed {needed_capacity_with_reserve}'
                f' (including {reserved_ratio * 100}% reserve)'
                )
            if action_on_lacking_capacity == 'increase':
                increase_ratio = needed_capacity_with_reserve / actual_capacities[act]
                facilities[act]['capacity'] = (
                    facilities[act]['capacity'] * increase_ratio
                    ).round().astype(int)
                logging.warning(f'Increased capacity of "{act}" activity')
        if action_on_lacking_capacity == 'error' and fail:
            raise RuntimeError('Failed due to potentially lacking capacity')


def handle_and_write_regular_agents(
        facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        agents_list: List[Agent],
        h: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
        process: int = 0,
        announce_every: int = 1000,
        report_every: int = 1000,
        prefer_private: bool = False,
        abandon_pt: bool = False,
        use_links: bool = False,
        include_teleported: bool = False,
        action_on_lacking_capacity: Literal['error', 'warn', 'increase'] = 'error',
        reserved_ratio: float = 0.1
        ) -> List[Agent]:
    """
    Process and write all passed agents according to conditions in helpers
    # !!! TODO: add more parameters to function declaration

    Parameters
    ----------
    facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with (Geo)DataFrames, containing info about
        facilities for every available activity.
    agents_list : List[Agent]
        DESCRIPTION.
    h : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
        Dictionary with helper tables, loaded from input_data.py.
        Table `indices`
    process : int, optional
        Process number, that will be appended to agent's ID. The default is 0.
    prefer_private : bool, optional
        Private modes will be preferred over pt. The default is False
    abandon_pt : bool, optional
        Consider abandoning pt after long distance. The default is False
    action_on_lacking_capacity : str, optional
        What to do, if capacity of some activity's facilities is potentially
        insufficient:
            `error`: raise RuntimeError;
            `warn`: just show a warning, but keep processing;
            `increase`: try to estimate needed capacities.
        The default is 'error'.
    reserved_ratio : float, optional
        Ratio to keep reserved (in range from 0 to 1). The default is 0.1.

    Returns
    -------
    List[Agent]
        List of fully processed agents

    """
    if report_every != 0:
        report_progress(clean=True)

    logging.basicConfig(
        format='%(asctime)s %(levelname)s %(message)s',
        level=logging.INFO
    )  # trigger here to ensure output out of threads

    check_capacity_sufficiency(
        agents_list, facilities, action_on_lacking_capacity, reserved_ratio
        )
    random.shuffle(agents_list)

    for i, agent in enumerate(agents_list):
        agent.info = f'{process}_{i}'
        agent.process(
            facilities, h,
            use_links=use_links, prefer_private=prefer_private,
            abandon_pt=abandon_pt, include_teleported=include_teleported,
        )

        if announce_every != 0 and i % announce_every == 0 and i > 0:
            logging.info(
                f'{i} agents, process {process}, '
                f'progress {round(i * 100 / len(agents_list), 2)}%'
            )
        if report_every != 0 and i % report_every == 0 and i > 0:
            report_progress(
                progress=round(i * 100 / len(agents_list), 2)
            )

    if report_every != 0:
        report_progress(progress=100.0)

    return agents_list
