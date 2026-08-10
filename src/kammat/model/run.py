# -*- coding: utf-8 -*-
"""
Created on Thu Jan 26 16:02:52 2023

@author: dgrishchuk
"""

import os
import lxml
from pathlib import Path
from typing import Union, List, Optional

from kammat.input.population.agent import Agent
from kammat.model.pt2matsim import (
    ABSOLUTE_PT2MATSIM_EXECUTABLE_PATH, run_pt2matsim
    )
from kammat.model.utils import (
    suggest_matsim_ram_limit, run_subprocess, get_matsim_runnable_class,
    get_matsim_version
    )
from kammat.model.vehicles import (
    load_modify_and_save_vehicles, copy_vehicles
    )
from kammat.model.config import (
    ABSOLUTE_EXAMPLE_MATSIM_CONFIG_PATH, load_and_modify_config
    )


def handle_pt_and_config(
        net_path: Union[str, Path],
        population_path: Union[str, Path],
        output_config_path: Union[str, Path],
        gtfs_folder: Union[str, Path] = None,
        pt2matsim_executable_path: Union[str, Path] = ABSOLUTE_PT2MATSIM_EXECUTABLE_PATH,
        pt2matsim_net_path: Union[str, Path] = None,
        pt2matsim_schedule_path: Union[str, Path] = None,
        pt2matsim_vehicles_path: Union[str, Path] = None,
        number_of_threads: int = os.cpu_count() - 2,
        last_iteration: int = 99,
        default_config_path: Union[str, Path] = ABSOLUTE_EXAMPLE_MATSIM_CONFIG_PATH,
        matsim_output_directory: Union[str, Path] = None,
        lane_definitions_path: Union[str, Path] = None,
        write_events_interval: int = 0,
        write_plans_interval: int = 0,
        disable_innovations_after_fraction: Union[int, float] = 0.9,
        main_mode: str = 'car,truck',
        analyzed_modes: str = 'car,truck',
        network_modes: str = 'car,truck',
        chain_based_modes: str = 'car,truck',
        mutation_range: int = 30 * 60,
        agents_list: List[Agent] = None
        ):
    """

    Handle inputs and change configs for pt2matsim and MATSim.

    Run pt2matsim, if ``gtfs_folder`` is specified, otherwise no pt in MATSim.

    Parameters
    ----------
    net_path : Union[str, Path]
        MATSim car network (without pt).
    population_path : Union[str, Path]
        Population's xml to use in the simulation.
    output_config_path : Union[str, Path]
        Where to save MATSim config.
    gtfs_folder : Union[str, Path], optional
        Path to GTFS folder (not zip). If None, pt2matsim does not run and
        transit is not used in simulation, otherwise triggers pt2matsim.
        The default is None.
    pt2matsim_executable_path : Union[str, Path], optional
        Specify this path, if other version of pt2matsim is used (not in bin).
        The default is ABSOLUTE_PT2MATSIM_EXECUTABLE_PATH. Is not used, when
        ``gtfs_folder`` is None.
    pt2matsim_net_path : Union[str, Path], optional
        Path to network that pt2matsim generates. Is not used, when
        ``gtfs_folder`` is None. The default is None.
    pt2matsim_schedule_path : Union[str, Path], optional
        Path to schedule that pt2matsim generates. Is not used, when
        ``gtfs_folder`` is None. The default is None.
    pt2matsim_vehicles_path : Union[str, Path], optional
        Path to vehicles that pt2matsim generates. Is not used, when
        ``gtfs_folder`` is None. The default is None.
    number_of_threads : int, optional
        Threads that will be used in pseudo-routing in pt2matsim and in MATSim.
        The default is os.cpu_count() - 2.
    last_iteration : int, optional
        Last iteration in MATSim config. The default is 99.
    default_config_path : Union[str, Path], optional
        Config to be changed.
        The default is ABSOLUTE_EXAMPLE_MATSIM_CONFIG_PATH.
    matsim_output_directory : Union[str, Path], optional
        Where should MATSim store results. The default is None, which puts
        output folder in the same directory as config.
    lane_definitions_path : Union[str, Path], optional
        If lane definitions are available, are used in config. The default
        is None.
    write_events_interval : int, optional
        The default is 0 - no intermediate events are written.
    write_plans_interval : int, optional
        The default is 0  - no intermediate plans are written.
    disable_innovations_after_fraction : Union[int, float], optional
        When innovations should turn off. The default is 0.9.
    main_mode : str, optional
        The default is 'car,truck'.
    analyzed_modes : str, optional
        The default is 'car,truck'.
    network_modes : str, optional
        The default is 'car,truck'.
    chain_based_modes : str, optional
        The default is 'car,truck'.
    mutation_range : int, optional
        Time range in seconds, within which agents are allowed to modify their
        departure time. The default is 30 * 60 - 30 minutes.
    agents_list : List[Agent], optional
        If activities definitions should be deduced from plans of agents
        generated in this framework, pass them as an argument.
        The default is None - no changes to activities definitions are applied
        in default config file.

    """
    if gtfs_folder is not None:
        run_pt2matsim(net_path=net_path,
                      gtfs_folder=gtfs_folder,
                      output_net_path=pt2matsim_net_path,
                      output_vehicles_path=pt2matsim_vehicles_path,
                      output_schedule_path=pt2matsim_schedule_path,
                      number_of_threads=number_of_threads,
                      executable_path=pt2matsim_executable_path)
        vehicles_path = pt2matsim_vehicles_path
        final_net_path = pt2matsim_net_path
        load_modify_and_save_vehicles(pt2matsim_vehicles_path,
                                      pt2matsim_vehicles_path)
        # essentially, just rewrite the file
    else:
        vehicles_path = Path(output_config_path).parent / 'vehicles.xml'
        final_net_path = net_path
        copy_vehicles(vehicles_path)
        # copy default vehicles to this path

    load_and_modify_config(net_path=final_net_path,
                           population_path=population_path,
                           number_of_threads=number_of_threads,
                           last_iteration=last_iteration,
                           output_config_path=output_config_path,
                           default_config_path=default_config_path,
                           matsim_output_directory=matsim_output_directory,
                           schedule_path=pt2matsim_schedule_path,
                           vehicles_path=vehicles_path,
                           lane_definitions_path=lane_definitions_path,
                           write_events_interval=write_events_interval,
                           write_plans_interval=write_plans_interval,
                           disable_innovations_after_fraction=disable_innovations_after_fraction,
                           main_mode=main_mode,
                           analyzed_modes=analyzed_modes,
                           network_modes=network_modes,
                           chain_based_modes=chain_based_modes,
                           mutation_range=mutation_range,
                           agents_list=agents_list,
                           write=True)


def run_matsim(
        executable_path: Union[str, Path],
        config_path: Union[str, Path],
        java_bin: Union[str, Path] = 'java',
        ram_limit: str = suggest_matsim_ram_limit(),
        custom_class: Optional[str] = None
        ):
    """
    Run MATSim executable with specified RAM limit and config settings.

    Subprocess is active as long as MATSim runs.

    Parameters
    ----------
    executable_path : Union[str, Path]
        Path to MATSim executable.
    config_path : Union[str, Path]
        Path to config prepared for run in MATSim,
    java_bin : Union[str, Path], optional
        Path to the Java binary to be used in the system call. The default is
        `java`.
    ram_limit : str, optional
        Max heap size for Java. The default is 70% of RAM on current machine.
    custom_class : str, optional
        Class to be executed.

    """
    ver = get_matsim_version(matsim_executable=executable_path)
    if custom_class:
        cl = custom_class
    else:
        cl = get_matsim_runnable_class(matsim_version=ver)
    cmd = (
        f'"{java_bin}" -cp "{executable_path}" -Xmx{ram_limit} '
        f'{cl} "{config_path}"'
    )
    run_subprocess(cmd)


def get_matsim_progress_from_config(
        config_path: Union[str, Path],
        percent: bool = True,
        precision: int = 2
        ) -> float:
    """
    Parse config, get output folder, last iteration number, calculate progress.

    Parameters
    ----------
    config_path : Union[str, Path]
        Where the current config is located.
    percent : bool, optional
        Whether to count percentage instead of fraction. The default is True.
    precision : int, optional
        Round up to this amount of decimal signs. The default is 2.

    Returns
    -------
    float

    """
    tree = lxml.etree.parse(str(config_path))
    outdir = None
    iters = None

    for element in tree.getroot().iter():
        if element.tag == 'param' and element.attrib['name'] == 'outputDirectory':
            if Path(element.attrib['value']).is_absolute():
                outdir = Path(element.attrib['value'])
            else:
                outdir = (Path(config_path).parent / element.attrib['value']).resolve()
        elif element.tag == 'param' and element.attrib['name'] == 'lastIteration':
            iters = int(float(element.attrib['value']))

    if outdir is None:
        return .0

    return get_matsim_progress_from_data(outdir, iters, percent, precision)


def get_matsim_progress_from_data(
        output_directory: Union[str, Path],
        last_iteration: int,
        percent: bool = True,
        precision: int = 2
        ) -> float:
    """
    Calculate the progress based on current count of folders with iterations.

    Parameters
    ----------
    output_directory : Union[str, Path]
        Where output directory is
    last_iteration : int
        Last iteration as specified by configuration
    percent : bool, optional
        Whether to count percentage instead of fraction. The default is True.
    precision : int, optional
        Round up to this amount of decimal signs. The default is 2.

    Returns
    -------
    float

    """
    iters = last_iteration + 1

    curr_iters = len(list((Path(output_directory) / 'ITERS').glob('it.*')))
    base_result = curr_iters * (100 if percent else 1) / iters

    return round(base_result, precision)


# def parse_args(
#         args_list: List[str] = sys.argv[1:]
#         ) -> argparse.Namespace:
#     parser = argparse.ArgumentParser()
#     parser.add_argument('-M', '--matsim', action='store_true')
#     parser.add_argument('-e', '--executable-path')
#     parser.add_argument('-c', '--config-path')
#     parser.add_argument('-r', '--ram-limit')
#     parser.add_argument('-P', '--pt', action='store_true')
#     parser.add_argument('-n', '--net-path')
#     parser.add_argument('-p', '--population-path')
#     parser.add_argument('-oc', '--output-config-path')
#     parser.add_argument('-p2e', '--pt2matsim-executable-path',
#                         default=ABSOLUTE_PT2MATSIM_EXECUTABLE_PATH)
#     parser.add_argument('-p2s', '--pt2matsim-schedule-path')
#     parser.add_argument('-p2v', '--pt2matsim-vehicles-path')
#     parser.add_argument('-t', '--number-of-threads',
#                         type=int, default=os.cpu_count() - 2)
#     parser.add_argument('-i', '--last-iteration', type=int)
#     parser.add_argument('-dc', '--default-config-path',
#                         default=ABSOLUTE_EXAMPLE_MATSIM_CONFIG_PATH)
#     parser.add_argument('-mo', '--matsim-output-directory')
#     parser.add_argument('-ld', '--lane-definitions-path')
#     parser.add_argument('-ei', '--write-events-interval', type=int, default=0)
#     parser.add_argument('-pi', '--write-plans-interval', type=int, default=0)
#     parser.add_argument('-di', '--disable-innovations-after-fraction',
#                         type=float, default=0.9)
#     parser.add_argument('-mm', '--main-mode', default='car,truck')
#     parser.add_argument('-am', '--analyzed-modes', default='car,truck')
#     parser.add_argument('-nm', '--network-modes', default='car,truck')
#     parser.add_argument('-cm', '--chain-based-modes', default='car,truck')
#     parser.add_argument('-mr', '--mutation-range', default=30 * 60)
#     args = parser.parse_args(args_list)
#     return args
#
#
# if __name__ == '__main__':
#     args = parse_args()
#     if args.pt:
#         handle_pt_and_config(
#             executable_path=args.pt2matsim_executable_path,
#             net_path=args.net_path,
#             population_path=args.population_path,
#             output_config_path=args.output_config_path,
#             pt2matsim_executable_path=args.pt2matsim_executable_path,
#             pt2matsim_schedule_path=args.pt2matsim_schedule_path,
#             pt2matsim_vehicles_path=args.pt2matsim_vehicles_path,
#             number_of_threads=args.number_of_threads,
#             last_iteration=args.last_iteration,
#             default_config_path=args.default_config_path,
#             matsim_output_directory=args.matsim_output_directory,
#             lane_definitions_path=args.lane_definitions_path,
#             write_events_interval=args.write_events_interval,
#             write_plans_interval=args.write_plans_interval,
#             disable_innovations_after_fraction=args.disable_innovations_after_fraction,
#             main_mode=args.main_mode,
#             analyzed_modes=args.analyzed_modes,
#             network_modes=args.network_modes,
#             chain_based_modes=args.chain_based_modes,
#             mutation_range=args.mutation_range
#             )
#     if args.matsim:
#         run_matsim(
#             executable_path=args.executable_path,
#             config_path=args.config_path,
#             ram_limit=args.ram_limit
#             )
