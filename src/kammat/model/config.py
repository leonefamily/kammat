# -*- coding: utf-8 -*-
"""
Created on Thu Jan 26 14:49:30 2023

@author: dgrishchuk
"""

import os
import sys
import inspect
import argparse
from lxml import etree
from pathlib import Path
from typing import Union, List, Optional

from kammat.input.population.agent import Agent
from kammat.model.utils import modify_config
from kammat.defaults.constants import (
    EXAMPLE_MATSIM_CONFIG_PATH, PathPointer
)

ABSOLUTE_EXAMPLE_MATSIM_CONFIG_PATH = str(
    (Path(inspect.getfile(PathPointer)).parent / EXAMPLE_MATSIM_CONFIG_PATH).resolve()
)


def get_activities_definitions_from_population(
        agents_list: List[Agent],
        ) -> etree.Element:
    """
    Deduce activities earliest/latest/typical start from agents list

    Parameters
    ----------
    agents_list : List[Agent]
        DESCRIPTION.

    Returns
    -------
    etree.Element
        Element to replace original MATSim activities definitions

    """
    pass


def load_and_modify_config(
        net_path: Union[str, Path],
        population_path: Union[str, Path],
        number_of_threads: int = os.cpu_count() - 2,
        last_iteration: int = 99,
        output_config_path: Union[str, Path] = None,
        default_config_path: Union[str, Path] = ABSOLUTE_EXAMPLE_MATSIM_CONFIG_PATH,
        matsim_output_directory: Union[str, Path] = None,
        schedule_path: Union[str, Path] = None,
        vehicles_path: Union[str, Path] = None,
        lane_definitions_path: Union[str, Path] = None,
        write_events_interval: int = 0,
        write_plans_interval: int = 0,
        disable_innovations_after_fraction: Union[int, float] = 0.9,
        main_mode: str = 'car,truck',
        analyzed_modes: str = 'car,truck',
        network_modes: str = 'car,truck',
        chain_based_modes: str = 'car,truck',
        mutation_range: int = 30 * 60,
        agents_list: List[Agent] = None,
        write: bool = True,
        scoring_parameters_path: Union[str, Path] = None,
        minibus_parameters_path: Union[str, Path] = None,
        ) -> Optional[etree.ElementTree]:
    """
    Read default config (see .defaults.constants.EXAMPLE_MATSIM_CONFIG_PATH).

    Modify it based on parameters and optionally write it.

    Parameters
    ----------
    net_path : Union[str, Path]
        Path to MATSim network file
    population_path : Union[str, Path]
        Path to MATSim population file
    number_of_threads : int, optional
        The default is count of cores on the current machine minus 2
    last_iteration : int, optional
        The default is 99 (starts from 0)
    output_config_path: Union[str, Path], optional
        Where to save modified config. Required if `write` is False.
    default_config_path : Union[str, Path], optional
        The default is ABSOLUTE_EXAMPLE_MATSIM_CONFIG_PATH.
    matsim_output_directory : Union[str, Path], optional
        Where MATSim stores its iterations. The default is None, which makes
        folder to appear in the same directory as config file
    schedule_path : Union[str, Path], optional
        Where transit schedules are stored. The default is None, which makes
        simulation to diregard public transport presence
    vehicles_path : Union[str, Path], optional
        Where vehicle types (and vehicles themselves) are stored. The default
        is None, which makes simulation to generate them automatically.
    lane_definitions_path : Union[str, Path], optional
        Path to lanes definitions, if turn restrictions should be considered.
        The default is None - lanes are still used, but without restrictions.
    write_events_interval : int, optional
        Dump events every xth iteration. The default is 0 - disable dumping
    write_plans_interval : int, optional
        Dump plans every xth iteration. The default is 0 - disable dumping
    disable_innovations_after_fraction : Union[int, float], optional
        Stop mutating plans after this fraction. The default is 0.9 (90%)
    main_mode : str, optional
        The default is 'car,truck'.
    analyzed_modes : str, optional
        The default is 'car,truck'.
    network_modes : str, optional
        The default is 'car,truck'.
    chain_based_modes : str, optional
        The default is 'car,truck'.
    mutation_range : int, optional
        +- time in seconds, that agents may alter off of every activity end
        time. The default is 30 * 60.
    agents_list : List[Agent], optional
        If activities definitions should be deduced from plans of agents
        generated in this framework, pass them as an argument.
        The default is None - no changes to activities definitions are applied
        in default config file.
    write : bool, optional
        If True, write and return None. If False, return ElementTree.
        The default is True.
    scoring_parameters_path : Union[str, Path], optional
        If is not None, the provided file replaces activity parameters in the
        default config. The default is None.
    minibus_parameters_path : Union[str, Path], optional
        If is not None, the provided file creates minibus `p` parameters in the
        default config. The default is None.

    Returns
    -------
    Optional[etree.ElementTree]
        Only return, if ``write`` is False

    """
    if write and output_config_path is None:
        raise ValueError('output_config_path must be specified, if write is True')

    parser = etree.XMLParser(remove_comments=False)
    tree = etree.parse(default_config_path, parser=parser)

    replacements = {
        'inputNetworkFile': net_path,
        'inputPlansFile': population_path,
        'numberOfThreads': number_of_threads,
        'lastIteration': last_iteration,
        'writeEventsInterval': write_events_interval,
        'writePlansInterval': write_plans_interval,
        'mainMode': main_mode,
        'analyzedModes': analyzed_modes,
        'networkModes': network_modes,
        'chainBasedModes': chain_based_modes,
        'mutationRange': mutation_range,
        'fractionOfIterationsToDisableInnovation': (
            disable_innovations_after_fraction
            )
    }

    if output_config_path is not None:
        replacements['outputDirectory'] = (
            matsim_output_directory if matsim_output_directory is not None else
            Path(output_config_path).parent / 'output'
            )
    else:
        replacements['outputDirectory'] = './output'

    if vehicles_path is not None:
        replacements['vehiclesSource'] = 'modeVehicleTypesFromVehiclesData'
        replacements['vehiclesFile'] = vehicles_path
    else:
        replacements['vehiclesSource'] = 'defaultVehicle'

    if schedule_path is not None:
        replacements['transitScheduleFile'] = schedule_path
        replacements['useTransit'] = 'true'
        replacements['usingTransitInMobsim'] = 'true'
    else:
        replacements['transitScheduleFile'] = 'null'
        replacements['usingTransitInMobsim'] = 'false'
        replacements['useTransit'] = 'false'

    if lane_definitions_path is not None:
        replacements['laneDefinitionsFile'] = lane_definitions_path
        replacements['useLanes'] = 'true'
        replacements['enableLinkToLinkRouting'] = 'true'
        replacements['calculateLinkToLinkTravelTimes'] = 'true'
        replacements['separateModes'] = 'false'

    modify_config(replacements, tree)

    if agents_list is not None:
        acts_defs = get_activities_definitions_from_population(agents_list)
        # TODO include acts_defs into tree

    if scoring_parameters_path is not None:
        sp_parser = etree.XMLParser(remove_comments=False)
        new_spars = etree.parse(scoring_parameters_path, parser=sp_parser)
        include_scoring_parameters(
            new_spars=new_spars, config=tree
        )
    if minibus_parameters_path is not None:
        mp_parser = etree.XMLParser(remove_comments=False)
        mpars = etree.parse(minibus_parameters_path, parser=mp_parser)
        include_minibus_parameters(
            mpars=mpars, config=tree
        )

    if not write:
        return tree
    tree.write(str(output_config_path))


def include_scoring_parameters(
        new_spars: etree._ElementTree,
        config: etree._ElementTree
):
    """
    Replace existing scoring parameters.
    
    Changes are done in place.

    Parameters
    ----------
    new_spars : etree._ElementTree
        Tree of new scoring parameters.
    config : etree._ElementTree
        Default config tree.

    """
    config_spars = config.xpath(
        "//parameterset[@type='scoringParameters']"
    )[0]
    config_actpars = config_spars.xpath(
        "//parameterset[@type='activityParams']"
    )
    for old_actpar in config_actpars:
        config_spars.remove(old_actpar)

    for new_actpar in new_spars.xpath("//parameterset[@type='activityParams']"):
        config_spars.insert(-1, new_actpar)


def include_minibus_parameters(
        mpars: etree._ElementTree,
        config: etree._ElementTree
):
    """
    Add minibus parameters and possibly remove conflicting ptCounts module.
    
    Changes are done in place.

    Parameters
    ----------
    mpars : etree._ElementTree
        Minibus parameters tree.
    config : etree._ElementTree
        Default config tree.

    """
    config_ptcounts = config.xpath("//module[@name='ptCounts']")
    config_root = config.xpath("//config")[0]
    mpars_root = mpars.xpath("//config")[0]
    for old_ptcount in config_ptcounts:
        config_root.remove(old_ptcount)
        
    for pmodule in mpars_root.xpath("//module[@name='p']"):
        config_root.insert(-1, pmodule)


def parse_args(
        args_list: List[str] = sys.argv[1:]
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-n', '--net-path')
    parser.add_argument('-p', '--population-path')
    parser.add_argument('-C', '--output-config-path')
    parser.add_argument('-S', '--schedule-path')
    parser.add_argument('-V', '--vehicles-path')
    parser.add_argument('-t', '--number-of-threads', type=int,
                        default=os.cpu_count() - 2)
    parser.add_argument('-i', '--last-iteration', type=int)
    parser.add_argument('-c', '--default-config-path',
                        default=ABSOLUTE_EXAMPLE_MATSIM_CONFIG_PATH)
    parser.add_argument('-mo', '--matsim-output-directory')
    parser.add_argument('-ld', '--lane-definitions-path')
    parser.add_argument('-ei', '--write-events-interval', type=int, default=0)
    parser.add_argument('-pi', '--write-plans-interval', type=int, default=0)
    parser.add_argument(
        '-di', '--disable-innovations-after-fraction',
        type=float, default=0.9
    )
    parser.add_argument('-mm', '--main-mode', default='car,truck')
    parser.add_argument('-am', '--analyzed-modes', default='car,truck')
    parser.add_argument('-nm', '--network-modes', default='car,truck')
    parser.add_argument('-cm', '--chain-based-modes', default='car,truck')
    parser.add_argument('-mr', '--mutation-range', default=30 * 60)
    parser.add_argument('-sp', '--scoring-parameters-path')
    parser.add_argument('-mp', '--minibus-parameters-path')
    args = parser.parse_args(args_list)
    return args


if __name__ == '__main__':
    args = parse_args()
    load_and_modify_config(
        net_path=args.net_path,
        population_path=args.population_path,
        output_config_path=args.output_config_path,
        schedule_path=args.schedule_path,
        vehicles_path=args.vehicles_path,
        number_of_threads=args.number_of_threads,
        last_iteration=args.last_iteration,
        default_config_path=args.default_config_path,
        matsim_output_directory=args.matsim_output_directory,
        lane_definitions_path=args.lane_definitions_path,
        write_events_interval=args.write_events_interval,
        write_plans_interval=args.write_plans_interval,
        disable_innovations_after_fraction=args.disable_innovations_after_fraction,
        main_mode=args.main_mode,
        analyzed_modes=args.analyzed_modes,
        network_modes=args.network_modes,
        chain_based_modes=args.chain_based_modes,
        mutation_range=args.mutation_range,
        scoring_parameters_path=args.scoring_parameters_path,
        minibus_parameters_path=args.minibus_parameters_path
    )
