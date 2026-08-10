# -*- coding: utf-8 -*-
"""
Created on Tue Feb  7 11:24:59 2023

@author: dgrishchuk
"""

import io
import sys
import argparse
import traceback
from typing import List
from PIL import ImageTk, Image

from kammat.output.road import (
    get_link_count_stats, get_link_stats_plot, reaggregate_counts,
    load_network, merge_net_counts, link_stats_to_df, LINK_STATS_DF_COLS
)
from kammat.output.counts import read_link_counts
from kammat.gui.utils import (
    save_settings, restore_settings, handle_time_change
)
from kammat.defaults.constants import CSV_STYLE

import PySimpleGUI as sg
sg.theme('default1')

APP_NAME = 'vehicle_counts'
HIDDEN_BEFORE_LOAD = [
    '-LINKIDTEXT-', '-LINKID-', '-AGGTEXT-', '-AGG-', '-FILLER-', '-FIND-',
    '-TMHINT-', '-D1-', '-START-', '-STARTHMS-', '-D2-', '-END-', '-ENDHMS-']
HIDDEN_BEFORE_PLOT = ['-COL-', '-IMAGE-', '-SAVEPLOT-', '-TAB-', '-SAVETAB-']


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
    parser.add_argument('-c', '--counts-path')
    parser.add_argument('-n', '--net-path')
    args = parser.parse_args()
    return args


def update_visibility(
        window: sg.Window,
        keys_list: List[str],
        visible: bool = True
        ):
    for key in keys_list:
        window[key].update(visible=visible)


def main(
        counts_path: str = None,
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
        [sg.Text('Counts file', size=10),
         sg.Input(counts_path, key='-COUNTSPATH-', size=50, expand_x=True),
         sg.FileBrowse(key='-COUNTS-', size=6,
                       file_types=(("Counts JSON file", "*.json"),
                                   ("Counts JSON file", "*.json.gz")))],
        [sg.Text('Network file', size=10),
         sg.Input(net_path, key='-NETPATH-', size=50, expand_x=True),
         sg.FileBrowse(key='-NET-', size=6,
                       file_types=(("MATSim network file", "*.xml.gz"),
                                   ("MATSim network file", "*.xml")))],
        [sg.Text('', expand_x=True), sg.Button('Load', key='-LOAD-', size=6)],
        [sg.Text('Link ID', key='-LINKIDTEXT-', size=10, visible=False),
         sg.Input('', key='-LINKID-', size=50, visible=False, expand_x=True)],
        [sg.Text('Aggregation', size=10, key='-AGGTEXT-', visible=False),
         sg.Slider(range=(900, 7200), default_value=3600, visible=False,
                   orientation='h', resolution=900, key='-AGG-')],
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
        [sg.Text('', expand_x=True, visible=False, key='-FILLER-'),
         sg.Button('Find', key='-FIND-', size=6, visible=False)],
        [sg.Column([
            [sg.Image(None, size=(800, 400), key='-IMAGE-', visible=False)],
            [sg.Button('Save plot...', key='-SAVEPLOT-',
                       visible=False, size=10,
                       file_types=(('PNG', '.png'), ('JPG', '.jpg')),)],
            [sg.Table(values=[], headings=LINK_STATS_DF_COLS, key='-TAB-',
                      num_rows=5, expand_x=True, visible=False)],
            [sg.Button('Save table...', key='-SAVETAB-',
                       visible=False, size=10,
                       file_types=(('Comma separated values', '*.csv'),
                                   ('Excel binary file', '*.xlsx')),)]
            ],
            visible=False, key='-COL-', expand_x=True,
            expand_y=True, size=(820, 580))]
    ]

    window = sg.Window('Vehicle counts over time', layout, finalize=True)
    restore_settings(window, APP_NAME)
    handle_time_change(window=window)

    if counts_path is not None:
        window['-COUNTSPATH-'].update(counts_path)
    if net_path is not None:
        window['-NETPATH-'].update(net_path)

    link_id = None

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
                        window['-COUNTSPATH-'].get()]):
                window['-INFO-'].update(
                    'Fill all fields', text_color='firebrick1'
                    )
            else:
                window['-INFO-'].update(
                    'Loading files... Might take a while', text_color='black'
                    )
                try:
                    counts = read_link_counts(window['-COUNTSPATH-'].get())
                    net = load_network(window['-NETPATH-'].get(), as_geo=False)
                    net = merge_net_counts(net, counts)
                    window['-INFO-'].update('Files loaded')
                    update_visibility(window, HIDDEN_BEFORE_LOAD, True)
                except Exception as e:
                    window['-INFO-'].update(
                        f'Error: {e}', text_color='firebrick1'
                        )
                    print(traceback.format_exc())
        elif event == '-FIND-':
            # if link_id == window['-LINKID-'].get():
            #     window['-INFO-'].update(
            #         'Trying to plot the same link', text_color='black'
            #         )
            #     continue
            save_settings(window, APP_NAME)
            try:
                link_id = window['-LINKID-'].get()
                new_counts = reaggregate_counts(
                    counts,
                    aggregate_by=values['-AGG-'],
                    start=values['-START-'], 
                    end=values['-END-']
                )
                link_stats = get_link_count_stats(new_counts, link_id)
                link_stats_df = link_stats_to_df(link_stats)
                fig = get_link_stats_plot(link_stats, net)
                window['-INFO-'].update(
                    'Got plot and table', text_color='black'
                )
                update_visibility(window, HIDDEN_BEFORE_PLOT, True)
                # put image to view
                img_buffer = io.BytesIO()
                fig.savefig(img_buffer)
                img = ImageTk.PhotoImage(
                    Image.open(img_buffer).resize((800, 400))
                    )
                window['-IMAGE-'].update(data=img)
                window['-TAB-'].update(
                    values=[list(row) for row in link_stats_df.values]
                    )
            except Exception as e:
                window['-INFO-'].update(f'Error: {e}', text_color='firebrick1')
                update_visibility(window, HIDDEN_BEFORE_PLOT, False)
        elif event == '-SAVEPLOT-':
            save_settings(window, APP_NAME)
            filename = sg.popup_get_file(
                message='Save plot', save_as=True,
                no_window=True,
                default_path=link_id, keep_on_top=True,
                file_types=(("JPEG file", "*.jpg"), ("PNG file", "*.png"))
                )
            if filename:
                try:
                    fig.savefig(filename, dpi=200,
                                transparent=filename.endswith('.png'))
                except Exception as e:
                    window['-INFO-'].update(
                        f'Error: {e}', text_color='firebrick1'
                        )
        elif event == '-SAVETAB-':
            save_settings(window, APP_NAME)
            filename = sg.popup_get_file(
                message='Save table', save_as=True,
                default_path=link_id, keep_on_top=True,
                no_window=True,
                file_types=(("Comma separated values", "*.csv"),
                            ("Excel spreadsheet", "*.xlsx"))
                )
            if filename:
                try:
                    if filename.endswith('.xlsx'):
                        link_stats_df.to_excel(filename, index=False)
                    else:
                        link_stats_df.to_csv(
                            filename, index=False, **CSV_STYLE
                            )
                except Exception as e:
                    window['-INFO-'].update(
                        f'Error: {e}', text_color='firebrick1'
                        )
        elif event in ['-START-', '-END-']:
            handle_time_change(window=window, event=event, values=values)
    window.close()


if __name__ == '__main__':
    args = parse_args()
    main(
        counts_path=args.counts_path,
        net_path=args.net_path
    )
