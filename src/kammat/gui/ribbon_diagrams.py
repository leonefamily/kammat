# -*- coding: utf-8 -*-
"""
Created on Thu Feb  9 11:56:31 2023

@author: dgrishchuk
"""

import io
import sys
import argparse
from typing import List
from PIL import ImageTk, Image

from kammat.output.road import (
    load_network, get_ribbon_diagram, get_ribbon_diagram_by_links,
    RIBBON_DIAGRAMS_DF_COLS
)
from kammat.output.counts import read_link_turns
from kammat.gui.utils import (
    save_settings, restore_settings, update_visibility,
    handle_time_change
)
from kammat.defaults.constants import CSV_STYLE

import PySimpleGUI as sg
sg.theme('default1')

APP_NAME = 'ribbon_diagrams'
HIDDEN_BEFORE_LOAD = ['-TMHINT-', '-D1-', '-START-', '-STARTHMS-', '-D2-', '-END-', 
                      '-ENDHMS-',  '-NODEIDTEXT-', '-NODEID-',
                      '-MODEHINT-', '-MODECAR-', '-MODETRUCK-', '-TYPEHINT-',
                      '-TYPENODE-', '-TYPELINK-',  '-D3-', '-FIND-']
HIDDEN_BEFORE_PLOT = ['-COL-', '-COLIMG-', '-IMAGE-', '-SAVEPLOT-',
                      '-TAB-', '-SAVETAB-', '-DPIHINT-', '-DPI-']


def parse_args(
        args_list: List[str] = sys.argv[1:]
        ) -> argparse.Namespace:
    """
    Prefill fields with these arguments.

    Parameters
    ----------
    args_list : List[str]
        Arguments and their parts as if they were split by shell.

    Returns
    -------
    argparse.Namespace

    """
    parser = argparse.ArgumentParser()
    parser.add_argument('-t', '--turns-path')
    parser.add_argument('-n', '--net-path')
    args = parser.parse_args()
    return args


def handle_link_node_change(
        window: sg.Window,
        clear_field: bool = True
):
    if window['-TYPENODE-'].get():
        window['-NODEIDTEXT-'].update(value='Node ID')
        if clear_field:
            window['-NODEID-'].update(value='')
    if window['-TYPELINK-'].get():
        window['-NODEIDTEXT-'].update(value='Link IDs')
        if clear_field:
            window['-NODEID-'].update(value='')


def main(
        turns_path: str = None,
        net_path: str = None
        ):
    """
    A graphic interface for visualizing vehicle counts satistics.

    Can save plots and tables with statistics.

    Parameters
    ----------
    counts_path : str, optional
        Counts of vehicles on the network, product of ``output.read`` package
    net_path : str, optional
        Path to MATSim network used in the same run, that produced the counts

    """
    layout = [
        [sg.Text('', key='-INFO-', size=60,
                 font=("Courier New", sg.DEFAULT_FONT[1]))],
        [sg.Text('Turns/events', size=10),
         sg.Input(turns_path, key='-TURNSPATH-', size=50, expand_x=True),
         sg.FileBrowse(key='-TURNS-', size=6,
                       file_types=(("Turns JSON file", "*.json"),
                                   ("Turns JSON file", "*.json.gz"),
                                   ("Events DB file", "*.db")))],
        [sg.Text('Network file', size=10),
         sg.Input(net_path, key='-NETPATH-', size=50, expand_x=True),
         sg.FileBrowse(key='-NET-', size=6,
                       file_types=(("MATSim network file", "*.xml.gz"),
                                   ("MATSim network file", "*.xml")))],
        [sg.Text('', expand_x=True), sg.Button('Load', key='-LOAD-', size=6)],
        [sg.Text('Find by:', size=10, key='-TYPEHINT-', visible=False),
         sg.Radio('node ID', group_id='-TYPE-', default=True, key='-TYPENODE-',
                  visible=False, enable_events=True),
         sg.Radio('link IDs', group_id='-TYPE-', key='-TYPELINK-',
                  visible=False, enable_events=True)],
        [sg.Text('Node ID', key='-NODEIDTEXT-', size=10, visible=False),
         sg.Input('', key='-NODEID-', size=50, visible=False, expand_x=True)],
        [sg.Text('Time start/end', size=10, visible=False, key='-TMHINT-'),
         sg.Slider(range=(0, 86400), default_value=0, resolution=900,
                   key='-START-', orientation='h', enable_events=True,
                   visible=False),
         sg.Slider(range=(0, 86400), default_value=86400, resolution=900,
                   key='-END-', orientation='h', enable_events=True,
                   visible=False)],
        [sg.Text('', key='-D1-', size=10, visible=False),
         sg.Text('00:00:00', key='-STARTHMS-', size=10, visible=False),
         sg.Text('', key='-D2-', size=10, visible=False),
         sg.Text('24:00:00', key='-ENDHMS-', size=10, visible=False)],
        [sg.Text('Mode:', size=10, key='-MODEHINT-', visible=False),
         sg.Radio('car', group_id='-MODE-', default=True, key='-MODECAR-', visible=False),
         sg.Radio('truck', group_id='-MODE-', key='-MODETRUCK-', visible=False),
         sg.Text('', key='-D3-', expand_x=True, visible=False),
         sg.Button('Find', key='-FIND-', size=6, visible=False)],
        [sg.Column([
            [sg.Column([
                [sg.Image(None, size=(800, 2000), key='-IMAGE-', visible=False)],
                ],
                visible=False, key='-COLIMG-', expand_x=True,
                expand_y=True, size=(800, 400), scrollable=True,
                vertical_scroll_only=True)],
            # [sg.Image(None, size=(800, 400), key='-IMAGE-', visible=False)],
            [sg.Button('Save plot...', key='-SAVEPLOT-',
                       visible=False, size=10,
                       file_types=(('PNG', '.png'), ('JPG', '.jpg')),),
             sg.Text('       DPI', key='-DPIHINT-', visible=False),
             sg.Slider(range=(50, 1000), default_value=200, visible=False,
                       resolution=10, orientation='h', key='-DPI-')],
            [sg.Table(values=[], headings=RIBBON_DIAGRAMS_DF_COLS, key='-TAB-',
                      num_rows=5, expand_x=True, visible=False)],
            [sg.Button('Save table...', key='-SAVETAB-',
                       visible=False, size=10,
                       file_types=(('Comma separated values', '*.csv'),
                                   ('Excel binary file', '*.xlsx')),)]
            ],
            visible=False, key='-COL-', expand_x=True,
            expand_y=True, size=(820, 580), scrollable=False,
            vertical_scroll_only=True)]
    ]

    window = sg.Window('Node ribbon diagrams', layout, finalize=True)
    restore_settings(window, APP_NAME)
    handle_time_change(window=window)
    handle_link_node_change(window=window, clear_field=False)

    if turns_path is not None:
        window['-TURNSPATH-'].update(turns_path)
    if net_path is not None:
        window['-NETPATH-'].update(net_path)

    node_id = None
    mode = 'car'

    while True:
        event, values = window.read()
        if event == sg.WIN_CLOSED:
            break
        window['-INFO-'].update(value='', text_color='black')
        if event == '-LOAD-':
            update_visibility(window, HIDDEN_BEFORE_PLOT, False)
            update_visibility(window, HIDDEN_BEFORE_LOAD, False)
            save_settings(window, APP_NAME)
            if not all([window['-NETPATH-'].get(),
                        window['-TURNSPATH-'].get()]):
                window['-INFO-'].update(
                    'Fill all fields', text_color='firebrick1'
                )
            else:
                window['-INFO-'].update(
                    'Loading files... Might take a while', text_color='black'
                )
                try:
                    if not window['-TURNSPATH-'].get().endswith('.db'):
                        turns = read_link_turns(window['-TURNSPATH-'].get())
                    else:
                        turns = None
                    net = load_network(window['-NETPATH-'].get())
                    window['-INFO-'].update('Files loaded')
                    update_visibility(window, HIDDEN_BEFORE_LOAD, True)
                except Exception as e:
                    window['-INFO-'].update(
                        f'Error: {e}', text_color='firebrick1'
                    )
        elif event == '-FIND-':
            save_settings(window, APP_NAME)
            try:
                if '-MODECAR-' in values and values['-MODECAR-']:
                    mode = 'car'
                elif '-MODETRUCK-' in values and values['-MODETRUCK-']:
                    mode = 'truck'
                if '-TYPENODE-' in values and values['-TYPENODE-']:
                    node_id = window['-NODEID-'].get()
                    if turns is None:
                        fig, tables = get_ribbon_diagram(
                            net, None, node_id, mode=mode,
                            start=int(values['-START-']),
                            end=int(values['-END-']),
                            db_path=window['-TURNSPATH-'].get()
                        )
                    else:
                        fig, tables = get_ribbon_diagram(
                            net, turns, node_id, mode=mode,
                            start=int(values['-START-']),
                            end=int(values['-END-'])
                        )
                    dpath = node_id
                elif '-TYPELINK-' in values and values['-TYPELINK-']:
                    link_ids = values['-NODEID-'].split()
                    fig, tables = get_ribbon_diagram_by_links(
                        net=net, turns=turns, links=link_ids, mode=mode,
                        start=values['-START-'], end=values['-END-']
                    )
                    dpath = ','.join(link_ids)[:30]
                window['-INFO-'].update(
                    'Got plot and table', text_color='black'
                )
                update_visibility(window, HIDDEN_BEFORE_PLOT, True)
                # put image to view
                img_buffer = io.BytesIO()
                fig.savefig(
                    img_buffer,
                    dpi=values['-DPI-'],
                    bbox_inches="tight"
                )
                basewidth = 800
                nimg = Image.open(img_buffer)
                wpercent = basewidth / float(nimg.size[0])
                hsize = int(nimg.size[1] * wpercent)
                nimg = nimg.resize((basewidth, hsize),
                                   Image.LANCZOS)

                img = ImageTk.PhotoImage(nimg)
                window['-IMAGE-'].update(data=img)
                window['-TAB-'].update(
                    values=[list(row) for row in tables['turns'].values]
                )
            except Exception as e:
                window['-INFO-'].update(f'Error: {e}', text_color='firebrick1')
                update_visibility(window, HIDDEN_BEFORE_PLOT, False)
        elif event == '-SAVEPLOT-':
            save_settings(window, APP_NAME)
            filename = sg.popup_get_file(
                message='Save plot', save_as=True,
                no_window=True,
                default_path=dpath,
                keep_on_top=True,
                file_types=(("JPEG file", "*.jpg"), ("PNG file", "*.png"))
            )
            if filename:
                try:
                    fig.savefig(filename, dpi=200, bbox_inches="tight",
                                transparent=filename.endswith('.png'))
                except Exception as e:
                    window['-INFO-'].update(
                        f'Error: {e}', text_color='firebrick1'
                    )
        elif event == '-SAVETAB-':
            save_settings(window, APP_NAME)
            filename = sg.popup_get_file(
                message='Save table', save_as=True,
                default_path=node_id, keep_on_top=True,
                no_window=True,
                file_types=(("Comma separated values", "*.csv"),
                            ("Excel spreadsheet", "*.xlsx"))
                )
            if filename:
                try:
                    if filename.endswith('.xlsx'):
                        tables['turns'].to_excel(filename, index=False)
                    else:
                        tables['turns'].to_csv(
                            filename,
                            index=False,
                            **CSV_STYLE,
                            encoding='utf-8-sig'
                        )
                except Exception as e:
                    window['-INFO-'].update(
                        f'Error: {e}', text_color='firebrick1'
                        )
        elif event in ['-START-', '-END-']:
            handle_time_change(window=window, event=event, values=values)
        elif event in ['-TYPENODE-', '-TYPELINK-']:
            handle_link_node_change(window=window)
    window.close()


if __name__ == '__main__':
    args = parse_args()
    main(
        turns_path=args.turns_path,
        net_path=args.net_path
        )
