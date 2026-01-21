# -*- coding: utf-8 -*-
"""
Created on Fri Dec 16 19:04:28 2022

@author: dgrishchuk
"""

from typing import Dict, List, Union, Tuple, Optional
from pathlib import Path
import json

SAVE_STATE_PATH = Path(__file__).parent / 'variables.json'


class Variables:

    __isfrozen = False

    def _freeze(self):
        self.__isfrozen = True

    def escort(
            self,
            act: str
    ) -> str:
        return self.acts[act].upper()

    def revert_abbreviation(
            self,
            abbr_act: str
            ) -> str:
        """
        Returns first occurence of the full name of activity, and will skip
        further occurencies

        Parameters
        ----------
        abbr_act : str
            Abbreviated activity code

        Raises
        ------
        KeyError
            If there are no acitivities with such abbreviation

        Returns
        -------
        str

        """
        for a, aa in zip(self.acts.keys(), self.acts.values()):
            # activity, abbreviated activity
            if aa == abbr_act:
                return a
        raise KeyError(f'There is no activity with abbreviation {abbr_act}')

    def load_state(
            self,
            ip:  Union[str, Path] = SAVE_STATE_PATH
    ):
        """
        Load saved state

        Parameters
        ----------
        ip : Union[str, Path], optional
            Input path. The default is SAVE_STATE_PATH.

        Raises
        ------
        RuntimeError
            DESCRIPTION.

        """
        if Path(ip).exists():
            with open(ip, mode='r', encoding='utf-8') as fp:
                try:
                    d = json.load(fp)
                except Exception:
                    raise RuntimeError(f'Save state file "{ip}" is corrupted, '
                                       'try to delete it and configure '
                                       'variables again')
                for k, v in d.items():
                    if k not in self.__dict__:
                        raise RuntimeError('You are trying to assign an '
                                           f'unsupported variable {k}')
                    setattr(
                        self, k, (v if not isinstance(v, list) else tuple(v))
                    )

    def save_state(
            self,
            op: Union[str, Path] = SAVE_STATE_PATH
    ):
        """
        Save state

        Parameters
        ----------
        op : Union[str, Path], optional
            Output path. The default is SAVE_STATE_PATH.

        """
        with open(op, mode='w', encoding='utf-8') as fp:
            json.dump(self.__dict__, fp, indent=4)

    def __setattr__(self, key, value):
        if self.__isfrozen and not hasattr(self, key):
            raise TypeError(f"{self} is a frozen class")
        object.__setattr__(self, key, value)

    def __init__(
            self,
            reset_saved: bool = True
    ):

        self.acts: Dict[str, str] = {
            'home': 'hom',
            'work': 'wor',
            'sport': 'spo',
            'government': 'gov',
            'post': 'pos',
            'bank': 'ban',
            'buying': 'buy',
            'kindergarten': 'kin',
            'elemschool': 'ele',
            'midschool': 'mid',
            'university': 'uni',
            'artschool': 'art',
            'circle': 'cir',
            'doctor': 'doc',
            'restaurant': 'res',
            'culture': 'cul',
            'visit': 'vis',
            'church': 'chu',
            'cemetery': 'cem',
            'cottage': 'cot',
            'journey': 'tri',
            'bodycare': 'bod',
            'worktrip': 'wtr',
            'other': 'oth',
            'transit': 'tra',
            'freight': 'fre',
            'citylog': 'cit',
            'walk': 'wal',
            'cycling': 'cyc',
            'leisure': 'lei',
            'personal': 'per',
            'high_speed_rail': 'hsr'
        }

        self.speeds: Dict[str, float] = {
            'car': 500.0,
            'truck': 450.0,
            'pt': 350.0,
            'bike': 200.0,
            'carpool': 500.0,
            'walk': 80.0
            }
        # uniform teleportation speed along bee-line between activities

        self.capacity_affected: Tuple[str] = (self.acts['work'],
                                              self.acts['elemschool'],
                                              self.acts['midschool'],
                                              self.acts['university'])
        # capacity of these facilities is going to reduce when agents pick them

        self.cluster_affected: Tuple[str] = (self.acts['work'],
                                             self.acts['buying'])
        # activities to use clusters on

        self.cluster_dist_thresh: float = 300
        # max distance in meters to draw in front of agent's generated radius

        self.capacity_weight: float = 0.5
        # weight of capacity (big facilities will attract more people)
        # if equals zero - capacity weighting swithes off

        self.capacity_weight_affected: Tuple[str] = (self.acts['work'],
                                                     self.escort('work'),
                                                     self.acts['buying'],
                                                     self.escort('buying'),
                                                     self.acts['midschool'],
                                                     self.escort('midschool'),
                                                     self.acts['elemschool'],
                                                     self.escort('elemschool'),
                                                     self.acts['university'],
                                                     self.escort('university'))
        # facilities with bigger capacity will attract more agents by reducing
        # distance difference

        self.capacity_split_affected: Tuple[str] = self.capacity_affected
        # if calculation is multiprocess, capacity of these facilities is going
        # to evenly redistribute across all processes, e.g. if facility has
        # capacity 600 and there are 6 processes, every process will have
        # capacity 100 on this facility

        self.shuffle_dup_facility: Tuple[str] = (self.acts['work'],
                                                 self.acts['worktrip'],
                                                 self.acts['elemschool'],
                                                 self.acts['midschool'],
                                                 self.acts['university'],
                                                 self.escort('elemschool'),
                                                 self.escort('kindergarten'))
        # activities, that will switch for other facility, if the previous
        # activity was the same

        self.no_move_acts: Tuple[str] = (self.acts['cycling'],
                                         self.escort('cycling'),
                                         self.acts['walk'],
                                         self.escort('walk'))
        # activities, that will consume time, but stays at the same facility
        # for the whole time of its duration

        self.no_gen_dist: Tuple[str] = (self.acts['home'],
                                        self.escort('home'),
                                        *self.no_move_acts)
        # activities, that copy coordinates of their previous facility,
        # therefore distance doesn't generate at all (equals 0)

        self.cuckoo_acts: Tuple[str] = (self.acts['worktrip'],
                                        self.acts['other'],
                                        self.acts['visit'],
                                        self.acts['citylog'])
        # activities, that don't have their own facilities and will require
        # foster facility, just as cockoo does, when it needs to lay eggs

        self.stop_distance_thresh: Union[int, float] = 750
        # distance in meters, after which walking to a public transport stop
        # is considered too long, and the public transport itself - unreachable

        self.centrality_affected: Tuple[str] = (self.acts['work'],
                                                self.escort('work'))
        # activities, that agents will tend to pick closer to the center
        # of the modelled spatial scope

        self.center_coords: Optional[Tuple[float]] = (-598102.6402000003,
                                                      -1160817.5940000005)
        # x, y coordinates of the center of the modelled scope. If None,
        # coordinates will be picked automatically by the biggest facilities
        # concentration

        self.exclude_foster: Tuple[str] = (self.acts['other'],
                                           self.acts['home'],
                                           self.acts['citylog'],
                                           self.acts['transit'],
                                           self.acts['freight'],
                                           self.acts['visit'],
                                           self.acts['walk'],
                                           self.acts['cycling'],
                                           self.acts['journey'],
                                           self.acts['high_speed_rail'])
        # activities not to be picked randomly, if foster facility is needed

        self.special_acts: Tuple[str] = (self.acts['freight'],
                                         self.acts['citylog'])
        # acts that diaries don't have to have (behavior is defined elsewhere)

        self.reach_percentage: Union[int, float] = 0.9
        # what percentage of facilities should be UNreachable to run reach
        # increase strategy

        self.reach_thresh: Union[int, float] = 1
        # maximum length of reach increase in relative numbers (is multiplied
        # by the originally generated distance)

        self.lasting_limit: Union[int, float] = 14
        # limit of agent's activities from first start to last end in hours

        self.reach_acts: Tuple[str] = (self.acts['restaurant'],
                                       self.escort('restaurant'),
                                       self.acts['bank'],
                                       self.escort('bank'),
                                       self.acts['kindergarten'],
                                       self.escort('kindergarten'),
                                       self.acts['cemetery'],
                                       self.escort('cemetery'),
                                       self.acts['bodycare'],
                                       self.escort('bodycare'),
                                       self.acts['circle'],
                                       self.escort('circle'),
                                       self.acts['culture'],
                                       self.escort('culture'),
                                       self.acts['government'],
                                       self.escort('government'),
                                       self.acts['journey'],
                                       self.escort('journey'),
                                       self.acts['post'],
                                       self.escort('post'),
                                       self.acts['visit'],
                                       self.escort('visit'),
                                       self.acts['work'],
                                       self.escort('work'))
        # activities, which will have enabled reach increase strategy
        # to prevent agents, who have small generated distance, from
        # settling at the closest point to the spatial unit's border,
        # when spatial distance probability is active

        self.last_facilities_path: str = None
        # facilities file that was used with the last run

        self.last_facilities_change_time: int = None
        # timestamp to define, that even with the same name, the contents are
        # the same too

        self.last_transit_points_path: str = None
        self.last_transit_points_change_time: int = None

        self.last_freight_points_path: str = None
        self.last_freight_points_change_time: int = None

        self.last_citylog_points_path: str = None
        self.last_citylog_points_change_time: int = None

        self.last_categories_path: str = None
        self.last_categories_change_time: int = None

        self.last_distances_path: str = None
        self.last_distances_change_time: int = None

        self.last_target_probabilities_path: str = None
        self.last_target_probabilities_change_time: int = None

        self.last_staying_path: str = None
        self.last_staying_change_time: int = None

        self.links_cache: Dict[Tuple[float], str] = {}
        # keep closest links cache when looking for a custom ones

        self._freeze()
        # prevent new attributes from being added after this point

        if reset_saved:
            self.load_state()
