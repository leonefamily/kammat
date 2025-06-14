# -*- coding: utf-8 -*-
"""
Created on Fri Dec 16 15:47:06 2022

@author: dgrishchuk
"""

import pandas as pd
from typing import Dict, Union


class Relations(pd.DataFrame):
    _metadata = ['precision', 'target_precision', 'all_activities']

    @property
    def _constructor(self):
        return Relations

    def set_metadata(
            self,
            metadata: Dict[str, str]):
        """
        Set metadata to the instance's attributes

        Parameters
        ----------
        metadata : Dict[str, str]
            Metadata, e.g. spatial precision

        """
        for k, v in metadata.items():
            setattr(self, k, v)

    def __setattr__(self, attr, val):
        if attr in ['precision', 'target_precision', 'all_activities']:
            object.__setattr__(self, attr, val)
        else:
            super().__setattr__(attr, val)


class Indices(pd.DataFrame):

    @property
    def _constructor(self):
        return Indices


class ModalSplit(pd.DataFrame):
    _metadata = ['precision', 'target_precision']

    @property
    def _constructor(self):
        return ModalSplit

    def set_metadata(
            self,
            metadata: Dict[str, str]):
        """
        Set metadata to the instance's attributes

        Parameters
        ----------
        metadata : Dict[str, str]
            Metadata, e.g. spatial precision

        """
        for k, v in metadata.items():
            setattr(self, k, v)

    def __setattr__(self, attr, val):
        if attr in ['precision', 'target_precision']:
            object.__setattr__(self, attr, val)
        else:
            super().__setattr__(attr, val)


class Times(pd.DataFrame):

    _metadata = ['precision']

    @property
    def _constructor(self):
        return Times

    def __setattr__(self, attr, val):
        if attr in ['base_types', 'all_types']:
            object.__setattr__(self, attr, val)
        else:
            super().__setattr__(attr, val)


class CityLogistics(pd.DataFrame):
    _metadata = ['base_types', 'all_types']

    @property
    def _constructor(self):
        return CityLogistics

    def set_metadata(
            self,
            metadata: Dict[str, str]):
        """
        Set metadata to the instance's attributes

        Parameters
        ----------
        metadata : Dict[str, str]
            Metadata, e.g. spatial precision

        """
        for k, v in metadata.items():
            setattr(self, k, v)

    def __setattr__(self, attr, val):
        if attr in ['base_types', 'all_types']:
            object.__setattr__(self, attr, val)
        else:
            super().__setattr__(attr, val)


class TimeCourses(pd.DataFrame):

    @property
    def _constructor(self):
        return TimeCourses


class OnewayFlows(pd.DataFrame):

    @property
    def _constructor(self):
        return OnewayFlows


class TargetProbabilities(pd.DataFrame):
    _metadata = ['precision', 'target_precision']

    @property
    def _constructor(self):
        return TargetProbabilities

    def set_metadata(
            self,
            metadata: Dict[str, str]):
        """
        Set metadata to the instance's attributes

        Parameters
        ----------
        metadata : Dict[str, str]
            Metadata, e.g. spatial precision

        """
        for k, v in metadata.items():
            setattr(self, k, v)

    def __setattr__(self, attr, val):
        if attr in ['precision', 'target_precision']:
            object.__setattr__(self, attr, val)
        else:
            super().__setattr__(attr, val)


class Distances(pd.DataFrame):
    _metadata = ['precision', 'target_precision']

    @property
    def _constructor(self):
        return Distances

    def set_metadata(
            self,
            metadata: Dict[str, str]):
        """
        Set metadata to the instance's attributes

        Parameters
        ----------
        metadata : Dict[str, str]
            Metadata, e.g. spatial precision

        """
        for k, v in metadata.items():
            setattr(self, k, v)

    def __setattr__(self, attr, val):
        if attr in ['precision', 'target_precision']:
            object.__setattr__(self, attr, val)
        else:
            super().__setattr__(attr, val)


class Categories(pd.DataFrame):
    _metadata = ['precision', 'categories']

    @property
    def _constructor(self):
        return Categories

    def set_metadata(
            self,
            metadata: Dict[str, str]):
        """
        Set metadata to the instance's attributes

        Parameters
        ----------
        metadata : Dict[str, str]
            Metadata, e.g. spatial precision

        """
        for k, v in metadata.items():
            setattr(self, k, v)

    def __setattr__(self, attr, val):
        if attr in ['precision', 'categories']:
            object.__setattr__(self, attr, val)
        else:
            super().__setattr__(attr, val)


class Diaries(pd.DataFrame):

    _metadata = ['precision', 'type', 'all_activities']

    @property
    def _constructor(self):
        return Diaries

    def set_metadata(
            self,
            metadata: Dict[str, str]):
        """
        Set metadata to the instance's attributes

        Parameters
        ----------
        metadata : Dict[str, str]
            Metadata, e.g. spatial precision

        """
        for k, v in metadata.items():
            setattr(self, k, v)

    def __setattr__(self, attr, val):
        if attr in ['precision', 'type', 'all_activities']:
            object.__setattr__(self, attr, val)
        else:
            super().__setattr__(attr, val)


class Staying(pd.DataFrame):

    _metadata = ['precision']

    @property
    def _constructor(self):
        return Staying

    def __setattr__(self, attr, val):
        if attr in ['precision']:
            object.__setattr__(self, attr, val)
        else:
            super().__setattr__(attr, val)


Helpers = Dict[str, Union[Diaries, Distances, TargetProbabilities,
                          Times, Indices, CityLogistics, Staying,
                          ModalSplit, TimeCourses, Categories, Relations,
                          pd.DataFrame]]
