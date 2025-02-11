# -*- coding: utf-8 -*-
"""
Created on Mon Jan 20 13:54:36 2025

@author: dgrishchuk
"""
import sys

import argparse
import warnings
import numpy as np
import pandas as pd
from lxml import etree
from pathlib import Path
from copy import deepcopy
from typing import Union, List, Dict, Any, Optional

from kammat.export.sumo.utils import write_element_tree


def get_tls_junctions(
        net_root: etree.Element,
        tls_cons: List[etree.Element]
) -> List[etree.Element]:
    tls_junctions_ids = set()
    tls_junctions = []
    for con in tls_cons:
        from_edge = con.attrib['from']
        from_lane = con.attrib['fromLane']
        from_lane_obj = net_root.xpath(
            f'//lane[@id = "{from_edge}_{from_lane}"]'
        )[0]
        from_edge_obj = from_lane_obj.getparent()

        if 'to' not in from_edge_obj.attrib:
            continue

        to_node = from_edge_obj.attrib['to']
        if to_node in tls_junctions_ids:
            continue

        to_node_obj = net_root.xpath(
            f'//junction[@id = "{to_node}"]'
        )[0]
        tls_junctions.append(to_node_obj)
        tls_junctions_ids.add(to_node)
    return tls_junctions


def get_unified_response_map(
        net_root: List[etree.Element],
        tls_junctions: List[etree.Element],
        tls_cons: List[etree.Element]
) -> Dict[int, str]:
    road_lanes = []
    ped_lanes = []
    response_map = {}
    for junction in tls_junctions:
        int_lanes = junction.attrib['intLanes'].split(' ')
        jid = junction.attrib['id']
        response_map[jid] = {}
        requests = junction.findall('request')
        for order, int_lane in enumerate(int_lanes):
            int_lane_obj = net_root.xpath(
                f'//lane[@id = "{int_lane}"]'
            )[0]
            int_edge_obj = int_lane_obj.getparent()
            int_edge = int_edge_obj.attrib['id']
            int_edg_spl = int_edge.split('_')
            is_ped = (  # crossing
                int_edg_spl[0].startswith(':') and
                int_edg_spl[-1].startswith('c')
            )
            request_obj = requests[order]
            # in natural order, from left to right, not the opposite!
            rev_response = request_obj.attrib['response'][::-1]
            response_map[jid][order] = rev_response
            if is_ped:
                ped_lanes.append({
                    'lane': int_lane,
                    'junction': jid,
                    'orig_index': order,
                    'rev_response': rev_response
                })
            else:
                road_lanes.append({
                    'lane': int_lane,
                    'junction': jid,
                    'orig_index': order,
                    'rev_response': rev_response
                })

    all_lanes = road_lanes + ped_lanes
    if len(all_lanes) != len(tls_cons):
        raise RuntimeError(
            'TLS lanes count is not equal to internal connections count'
        )

    for lane, con in zip(all_lanes, tls_cons):
        new_index = con.attrib['linkIndex']
        lane['new_index'] = int(new_index)

    new_response_map = {}
    for lane1 in all_lanes:
        orig_response1 = lane1['rev_response']
        new_response_list = ['0'] * (all_lanes[-1]['new_index'] + 1)
        for lane2 in all_lanes:
            if lane1['junction'] != lane2['junction']:
                orig_response2 = lane2['rev_response']
                # they are technically intersections, no need to pair
                # just suppose, they don't yield to anything
                new_response_list[lane2['new_index']] = (
                    orig_response2[lane2['orig_index']]
                )
            else:
                new_response_list[lane2['new_index']] = (
                    orig_response1[lane2['orig_index']]
                )
        new_response = ''.join(new_response_list)
        new_response_map[lane1['new_index']] = new_response
    return new_response_map


def fix_major_greens(
        phases_reduced: List[Dict[str, str]],
        new_response_map: Dict[int, str]
) -> List[Dict[str, str]]:
    new_phases = deepcopy(phases_reduced)
    for num, phase in enumerate(phases_reduced):
        orig_state_list = list(phase['state'])
        new_state_list = list(phase['state'])
        for i, cur_sig in enumerate(orig_state_list):
            if cur_sig.lower() != 'g':
                # no reason to make major yellow or major red, only green
                continue
            curr_sig_major = []
            curr_response = new_response_map[i]
            for j, flow_response in enumerate(curr_response):
                if i == j:
                    continue
                # we want to make sure that no flows (j) that are superior
                # to the current flow (i) have the green light at this phase
                # If they do, we can't make it major green
                curr_sig_yields = bool(int(flow_response))
                opp_sig_is_green = bool(orig_state_list[j].lower() == 'g')
                if curr_sig_yields and opp_sig_is_green:
                    curr_sig_major.append(False)
                else:
                    curr_sig_major.append(True)
            if all(curr_sig_major):
                new_state_list[i] = 'G'
        new_phases[num]['state'] = ''.join(new_state_list)
    return new_phases


def handle_major_phases(
        phases_reduced: List[Dict[str, str]],
        net_path: Union[str, Path],
        tls_index: str
) -> List[Dict[str, str]]:
    parser = etree.XMLParser(remove_blank_text=True)
    net_tree = etree.parse(net_path, parser=parser)
    net_root = net_tree.getroot()

    tls_cons = list(
        sorted(
            net_root.xpath(f"//connection[@tl = '{tls_index}']"),
            key=lambda x: int(x.attrib['linkIndex'])
        )
    )
    if phases_reduced and tls_cons:
        statelen = len(phases_reduced[0]['state']) - 1
        lindex = int(
            max(
                tls_cons,
                key=lambda x: int(x.attrib['linkIndex'])
            ).attrib['linkIndex']
        )
        if statelen != lindex:
            raise ValueError(
                f'Probably wrong number of the last signal, should be {lindex}'
                f', got {statelen}'
            )
    tls_junctions = get_tls_junctions(
        net_root=net_root,
        tls_cons=tls_cons
    )
    new_response_map = get_unified_response_map(
        net_root=net_root,
        tls_junctions=tls_junctions,
        tls_cons=tls_cons
    )
    new_phases = fix_major_greens(
        phases_reduced=phases_reduced,
        new_response_map=new_response_map
    )
    return new_phases


def main(
        table_path: Union[str, Path],
        tls_index: str,
        tls_save_path: Union[str, Path],
        last_tls_connection_id: int,
        cycle_duration: int = 100,
        vehicles_yellow_duration: int = 3,
        vehicles_red_yellow_duration: int = 2,
        pedestrian_yellow_duration: int = 0,
        pedestrian_phase_prefix: str = 'P',
        vehicles_phase_prefix: str = 'V',
        tls_program_id: str = '1000',
        net_path: Optional[Union[str, Path]] = None
):
    tls_program_connections = last_tls_connection_id + 1

    table_path_obj = Path(table_path)
    if table_path_obj.suffix == '.xlsx':
        table = pd.read_excel(table_path_obj)
    else:
        table = pd.read_csv(table_path_obj)
    todrop = table[
        table['ID'].isna() |
        table['Signal group'].isna() |
        table['Init'].isna()
    ].index
    if len(todrop) != 0:
        warnings.warn(
            f'These indices from original table will be dropped: {todrop}'
        )
        table.drop(todrop, inplace=True)
    if 'Init2' not in table.columns:
        table[['Init2', 'Term2']] = np.nan
    exceeds_duration = (
            (table['Init'] > cycle_duration) |
            (table['Init2'] > cycle_duration)
    ).any()
    if exceeds_duration:
        raise ValueError(
            'There are Init values that are bigger than `cycle_duration`'
        )

    groups = {}
    phases = {
        sec: 'r' * tls_program_connections for sec in range(cycle_duration)
    }
    groups_names = {
        sec: set() for sec in range(cycle_duration)
    }

    for n, row in table.iterrows():
        sgroup = row['Signal group']
        ids = [int(s.strip()) for s in row['ID'].split(',')]
        groups[sgroup] = {'g': set(), 'y': set(), 'u': set()}
        # yellows
        yellow_duration = (
            pedestrian_yellow_duration if
            sgroup.startswith(pedestrian_phase_prefix) else
            vehicles_yellow_duration
        )
        for i in range(yellow_duration):
            sec = row['Term'] + i
            sec %= cycle_duration
            groups[sgroup]['y'].add(sec)
            phases[sec] = ''.join(
                'y' if num in ids else sig
                for num, sig in enumerate(phases[sec])
            )
            groups_names[sec].add(sgroup)
            if not pd.isna(row['Term2']):
                sec2 = row['Term2'] + i
                sec2 %= cycle_duration
                groups[sgroup]['y'].add(sec2)
                phases[sec2] = ''.join(
                    'y' if num in ids else sig
                    for num, sig in enumerate(phases[sec2])
                )
                groups_names[sec2].add(sgroup)
        # red-yellows
        ryellow_duration = (
            vehicles_red_yellow_duration if
            sgroup.startswith(vehicles_phase_prefix) else 0
        )
        for i in range(ryellow_duration):
            sec = row['Init'] + i
            sec %= cycle_duration
            groups[sgroup]['u'].add(sec)
            phases[sec] = ''.join(
                'u' if num in ids else sig
                for num, sig in enumerate(phases[sec])
            )
            groups_names[sec].add(sgroup)
            if not pd.isna(row['Init2']):
                sec2 = row['Init2'] + i
                sec2 %= cycle_duration
                groups[sgroup]['u'].add(sec2)
                phases[sec2] = ''.join(
                    'u' if num in ids else sig
                    for num, sig in enumerate(phases[sec2])
                )
                groups_names[sec2].add(sgroup)
        # greens
        fin = (
            row['Term'] + cycle_duration
            if row['Term'] < row['Init'] + ryellow_duration
            else row['Term']
        )
        sec = row['Init'] + ryellow_duration
        while sec < fin:
            groups[sgroup]['g'].add(sec % cycle_duration)
            phases[sec % cycle_duration] = ''.join(
                'g' if num in ids else sig
                for num, sig in enumerate(phases[sec % cycle_duration])
            )
            groups_names[sec % cycle_duration].add(sgroup)
            sec += 1
        if not pd.isna(row['Term2']):
            fin2 = (
                row['Term2'] + cycle_duration
                if row['Term2'] < row['Init2'] + ryellow_duration
                else row['Term2']
            )
            sec2 = row['Init2'] + ryellow_duration
            while sec2 < fin2:
                groups[sgroup]['g'].add(sec2 % cycle_duration)
                phases[sec2 % cycle_duration] = ''.join(
                    'g' if num in ids else sig
                    for num, sig in enumerate(phases[sec2 % cycle_duration])
                )
                groups_names[sec2 % cycle_duration].add(sgroup)
                sec2 += 1

    phases_reduced = []
    for j, (k, v) in enumerate(phases.items()):
        sgname = '_'.join(groups_names[k]) + f'_{j}'
        if j != 0:
            if v != phases_reduced[-1]['state']:
                phases_reduced[-1]['end'] = j
                phases_reduced[-1]['duration'] = (
                    j - phases_reduced[-1]['start']
                )
                phases_reduced.append({
                    'state': v,
                    'start': j,
                    'name': sgname
                })
        else:
            phases_reduced.append({
                'state': v,
                'start': j,
                'name': sgname
            })
    if phases_reduced:
        phases_reduced[-1]['duration'] = (
            cycle_duration - phases_reduced[-1]['start']
        )
    else:
        raise RuntimeError(
            'No phases were created'
        )

    all_red = set(range(tls_program_connections))
    for pr in phases_reduced:
        if 'start' in pr:
            del pr['start']
        if 'end' in pr:
            del pr['end']
        for num, sig in enumerate(pr['state']):
            if sig != 'r' and num in all_red:
                all_red.remove(num)
        for k, v in pr.items():
            pr[k] = str(v)

    if all_red:
        warnings.warn(
            f'There are linkIndexes that are always red: '
            f'{", ".join(str(num) for num in all_red)}'
        )

    new_phases = handle_major_phases(
        phases_reduced=phases_reduced,
        net_path=net_path,
        tls_index=tls_index
    )
    phases_tree = prepare_phases_tree(
        phases_reduced=new_phases,
        tls_index=tls_index,
        tls_program_id=tls_program_id
    )
    write_element_tree(
        tree=phases_tree,
        path=tls_save_path,
        # merge_if_exists=True
    )


def prepare_phases_tree(
        phases_reduced: List[Dict[str, Any]],
        tls_index: str,
        tls_type: str = 'static',
        tls_program_id: str = 'gen0',
        offset: Union[int, float] = 0
) -> etree.ElementTree:
    root = etree.Element('additional')
    root.set(
        "{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation",
        "http://sumo.dlr.de/xsd/additional_file.xsd"
    )
    tls = etree.SubElement(root, 'tlLogic', attrib={
        'id': str(tls_index),
        'type': str(tls_type),
        'programID': str(tls_program_id),
        'offset': str(offset)
    })
    for phase in phases_reduced:
        phase_el = etree.SubElement(tls, 'phase', attrib=phase)
    phases_tree = root.getroottree()
    return phases_tree


def parse_args(
        args_list: Optional[List[str]] = None
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-t', '--table-path',
        help='TLS phases durations path',
        required=True
    )
    parser.add_argument(
        '-i', '--tls-index',
        help='TLS index as in SUMO',
        required=True
    )
    parser.add_argument(
        '-s', '--tls-save-path',
        help="Path to save SUMO's native TLS additional file",
        required=True
    )
    parser.add_argument(
        '-I', '--last-tls-connection-id',
        help='Character that signifies a pedestrian phase',
    )
    parser.add_argument(
        '-c', '--cycle-duration',
        help='Full cycle duration of all phases',
        type=int,
        default=100
    )
    parser.add_argument(
        '-p', '--tls-program-id',
        help='New TLS program ID',
        default='1000'
    )
    parser.add_argument(
        '-Y', '--vehicles-yellow-duration',
        help='Duration of yellow after green for road vehicles',
        type=int,
        default=3
    )
    parser.add_argument(
        '-R', '--vehicles-red-yellow-duration',
        help='Duration of yellow after red and before green for road vehicles',
        type=int,
        default=2
    )
    parser.add_argument(
        '-y', '--pedestrian-yellow-duration',
        help='Duration of yellow after green for road vehicles',
        type=int,
        default=0
    )
    parser.add_argument(
        '-V', '--vehicles-phase-prefix',
        help='Character that signifies a normal road vehicle phase (not PT)',
        default='V'
    )
    parser.add_argument(
        '-v', '--pedestrian-phase-prefix',
        help='Character that signifies a pedestrian phase',
        default='P'
    )
    parser.add_argument(
        '-n', '--net-path',
        help='Path to SUMO net to refine major and minor greens '
             'where possible ',
        default='P'
    )
    args_list = sys.argv[1:] if args_list is None else args_list
    args = parser.parse_args(args_list)
    return args


if __name__ == '__main__':
    args = parse_args()
    main(
        table_path=args.table_path,
        tls_index=args.tls_index,
        tls_save_path=args.tls_save_path,
        last_tls_connection_id=args.last_tls_connection_id,
        cycle_duration=args.cycle_duration,
        vehicles_yellow_duration=args.vehicles_yellow_duration,
        vehicles_red_yellow_duration=args.vehicles_red_yellow_duration,
        pedestrian_yellow_duration=args.pedestrian_yellow_duration,
        pedestrian_phase_prefix=args.pedestrian_phase_prefix,
        vehicles_phase_prefix=args.vehicles_phase_prefix,
        tls_program_id=args.tls_program_id,
        net_path=args.net_path
    )
