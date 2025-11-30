# -*- coding: utf-8 -*-
"""
Created on Mon Feb 13 12:22:57 2023

@author: dgrishchuk
"""

import sys
import shlex
import argparse
from typing import List

from kammat.output.road import load_network
from kammat.output.counts import read_pt_counts
from kammat.output.pt import (
    load_pt_schedule, merge_net_pt_counts, get_transit_stops,
    pt_net_to_plot_gdf, get_pt_stats, add_stop_name_columns, add_lines_column,
    get_pt_links_time_stats, get_pt_link_time_plot, get_pt_link_time_plot_df,
    get_line_route_plot
)
from kammat.output.utils import (
    PT_STATS_DF_COLS, PT_LINK_STATS_DF_COLS
)
from kammat.gui.utils import (
    save_settings, restore_settings, update_visibility, put_plot_to_image,
    handle_time_change
)

from kammat.defaults.constants import CSV_STYLE

import PySimpleGUI as sg
sg.theme('default1')

APP_NAME = 'pt_counts'
HIDDEN_BEFORE_LOAD = ['-AGGTEXT-', '-AGG-', '-LINKIDTEXT-', 
                      '-LINKID-', '-LINESTEXT-', '-LINES-', '-FILLER-', '-FIND-',
                      '-TMHINT-', '-D1-', '-START-', '-STARTHMS-', '-D2-',
                      '-END-', '-ENDHMS-']
HIDDEN_BEFORE_PLOT = ['-SWITCHER-', '-COL-', '-IMAGE-', '-SAVEPLOT-']
HIDDEN_BEFORE_PLOT_LINE = ['-LINETAB-', '-SAVELINETAB-', '-SAVELINESHP-']
HIDDEN_BEFORE_PLOT_LINK = ['-LINKTAB-', '-SAVELINKTAB-']


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
    parser.add_argument('-c', '--pt-counts-path')
    parser.add_argument('-n', '--net-path')
    parser.add_argument('-s', '--schedule-path')
    args = parser.parse_args()
    return args


def main(
        pt_counts_path: str = None,
        net_path: str = None,
        schedule_path: str = None,
        aggregate_by: int = 3600
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
    linelinks_tab = [[sg.Column([
       [sg.Image(None, size=(800, 400), key='-IMAGE-', visible=False)],
       [sg.Button('Save plot...', key='-SAVEPLOT-',
                  visible=False, size=10,
                  file_types=(('PNG', '.png'), ('JPG', '.jpg')),)],
       [sg.Table(values=[], headings=PT_STATS_DF_COLS, key='-LINETAB-',
                 num_rows=5, expand_x=True, visible=False),
       sg.Table(values=[], headings=PT_LINK_STATS_DF_COLS, key='-LINKTAB-',
                 num_rows=5, expand_x=True, visible=False)],
       [sg.Button('Save table...', key='-SAVELINKTAB-',
                  visible=False, size=10,
                  file_types=(('Comma separated values', '*.csv'),
                              ('Excel binary file', '*.xlsx')),),
       sg.Button('Save table...', key='-SAVELINETAB-',
                  visible=False, size=10,
                  file_types=(('Comma separated values', '*.csv'),
                              ('Excel binary file', '*.xlsx')),),
       sg.Button('Save shapefile...', key='-SAVELINESHP-',
                  visible=False, file_types=(('ESRI shapefile', '*.shp'),))]
       ],
       visible=False, key='-COL-', expand_x=True, scrollable=True,
       vertical_scroll_only=True, expand_y=True, size=(820, 580))]]

    stops_tab = [[sg.Column([
       [sg.Image(None, size=(800, 400), key='-IMAGESTOP-', visible=False)],
       [sg.Button('Save plot...', key='-SAVEPLOTSTOP-',
                  visible=False, size=10,
                  file_types=(('PNG', '.png'), ('JPG', '.jpg')),)],
       [sg.Table(values=[], headings=PT_LINK_STATS_DF_COLS, key='-STOPTAB-',
                 num_rows=5, expand_x=True, visible=False)],
       [sg.Button('Save table...', key='-SAVESTOPTAB-',
                  visible=False, size=10,
                  file_types=(('Comma separated values', '*.csv'),
                              ('Excel binary file', '*.xlsx')),),
       sg.Button('Save shapefile...', key='-SAVESTOPSHP-',
                  visible=False, file_types=(('ESRI shapefile', '*.shp'),))]
       ],
       visible=False, key='-STOPCOL-', expand_x=True, scrollable=True,
       vertical_scroll_only=True, expand_y=True, size=(820, 580))]]

    layout = [
        [sg.Text('', key='-INFO-', size=60,
                 font=("Courier New", sg.DEFAULT_FONT[1]))],
        [sg.Text('PT counts file', size=10),
         sg.Input(pt_counts_path if pt_counts_path else '',
                  key='-PTCOUNTSPATH-', size=50, expand_x=True),
         sg.FileBrowse(key='-PTCOUNTS-', size=6,
                       file_types=(("PT counts JSON file", "*.json"),
                                   ("PT counts JSON file", "*.json.gz")))],
        [sg.Text('Network file', size=10),
         sg.Input(net_path if net_path else '',
                  key='-NETPATH-', size=50, expand_x=True),
         sg.FileBrowse(key='-NET-', size=6,
                       file_types=(("MATSim network file", "*.xml.gz"),
                                   ("MATSim network file", "*.xml")))],
        [sg.Text('PT schedule file', size=10),
         sg.Input(net_path, key='-SCHEDPATH-', size=50, expand_x=True),
         sg.FileBrowse(key='-SCHED-', size=6,
                       file_types=(("MATSim PT schedule file", "*.xml.gz"),
                                   ("MATSim PT schedule file", "*.xml")))],
        [sg.Text('', expand_x=True), sg.Button('Load', key='-LOAD-', size=6)],
        [sg.Text('Line names', key='-LINESTEXT-', size=10, visible=False),
         sg.Input(
             '', key='-LINES-', expand_x=True, visible=False,
             tooltip='Separate by spaces, enclose IDs in quotes if needed'
             )],
        [sg.Text('Link ID', key='-LINKIDTEXT-', size=10, visible=False),
         sg.Input('', key='-LINKID-', visible=False, expand_x=True)],
        [sg.Text('Aggregation', size=10, key='-AGGTEXT-', visible=False),
         sg.Slider(range=(0, 7200), default_value=3600, visible=False,
                   orientation='h', resolution=300, key='-AGG-')],
         [sg.Text('Time start/end', size=10, visible=False, key='-TMHINT-'),
          sg.Slider(range=(0, 86400), default_value=0, resolution=300,
                    key='-START-', orientation='h', enable_events=True,
                    visible=False),
          sg.Slider(range=(0, 86400), default_value=86400, resolution=300,
                    key='-END-', orientation='h', enable_events=True,
                    visible=False)],
         [sg.Text('', key='-D1-', size=10, visible=False),
          sg.Text('00:00:00', key='-STARTHMS-', size=10, visible=False),
          sg.Text('', key='-D2-', size=10, visible=False),
          sg.Text('24:00:00', key='-ENDHMS-', size=10, visible=False)],
         [sg.Text('', expand_x=True, visible=False, key='-FILLER-'),
          sg.Button('Find', key='-FIND-', size=6, visible=False)],        
         [sg.TabGroup(
             [[sg.Tab("Links", linelinks_tab), sg.Tab("Stops", stops_tab)]],
             key='-SWITCHER-', visible=False)]
    ]

    window = sg.Window('Vehicle counts over time', layout, finalize=True)
    restore_settings(window, APP_NAME)
    handle_time_change(window=window)

    if pt_counts_path is not None:
        window['-PTCOUNTSPATH-'].update(pt_counts_path)
    if net_path is not None:
        window['-NETPATH-'].update(net_path)
    if schedule_path is not None:
        window['-SCHEDPATH-'].update(schedule_path)

    # link_id = ''
    # line_ids = ''

    while True:
        event, values = window.read()
        if event == sg.WIN_CLOSED:
            break
        window['-INFO-'].update(value='', text_color='black')
        if event == '-LOAD-':
            update_visibility(window, HIDDEN_BEFORE_PLOT_LINE, False)
            update_visibility(window, HIDDEN_BEFORE_PLOT_LINK, False)
            update_visibility(window, HIDDEN_BEFORE_LOAD, False)
            save_settings(window, APP_NAME)
            if not all([window['-NETPATH-'].get(),
                        window['-PTCOUNTSPATH-'].get(),
                        window['-SCHEDPATH-'].get()]):
                window['-INFO-'].update(
                    'Fill all fields', text_color='firebrick1'
                    )
            else:
                window['-INFO-'].update(
                    'Loading files... Might take a while', text_color='black'
                    )
                try:
                    pt_counts = read_pt_counts(window['-PTCOUNTSPATH-'].get())
                    pt_schedule = load_pt_schedule(window['-SCHEDPATH-'].get())
                    pt_stops = get_transit_stops(pt_schedule)
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
                lsplit = shlex.split(window['-LINES-'].get())
                if not lsplit:
                    lsplit = None
                pt_links_stats, stops_stats = get_pt_stats(
                    pt_counts, pt_schedule, pt_stops,
                    lines=lsplit, link_id=values['-LINKID-'],
                    start=values['-START-'], end=values['-END-']
                )
                pt_net = merge_net_pt_counts(net, pt_links_stats)
                pt_net = add_stop_name_columns(pt_net, pt_stops)
                pt_net = add_lines_column(pt_net, pt_schedule)
                pt_net = pt_net_to_plot_gdf(pt_net, lsplit)

                if values['-LINKID-']:
                    pt_links_time_stats = get_pt_links_time_stats(
                        pt_counts, pt_schedule, pt_stops, lsplit,
                        link_ids=[values['-LINKID-']],
                        aggregate_by=values['-AGG-'],
                        start=values['-START-'],
                        end=values['-END-']
                    )
                    table = get_pt_link_time_plot_df(
                        pt_links_time_stats, pt_net, window['-LINKID-'].get()
                        )
                    tablename, tabletype = '-LINKTAB-', 'link'
                    showtable = table[list(PT_LINK_STATS_DF_COLS)]
                    fig = get_pt_link_time_plot(
                        table, pt_net, link_id=values['-LINKID-']
                        )
                    window['-COL-'].unhide_row()
                    update_visibility(window, HIDDEN_BEFORE_PLOT, True)
                    update_visibility(window, HIDDEN_BEFORE_PLOT_LINK, True)
                    update_visibility(window, HIDDEN_BEFORE_PLOT_LINE, False)
                else:
                    table = pt_net_to_plot_gdf(pt_net, lsplit)
                    showtable = table[list(PT_STATS_DF_COLS)]
                    tablename, tabletype = '-LINETAB-', 'line'
                    fig = get_line_route_plot(table, lsplit)
                    window['-COL-'].unhide_row()
                    update_visibility(window, HIDDEN_BEFORE_PLOT, True)
                    update_visibility(window, HIDDEN_BEFORE_PLOT_LINE, True)
                    update_visibility(window, HIDDEN_BEFORE_PLOT_LINK, False)
                put_plot_to_image(window, '-IMAGE-', fig)
                window[tablename].update(
                    values=[
                        list(row) for row in showtable.values
                        ]
                    )
                window['-INFO-'].update(
                    'Got plot and table', text_color='black'
                    )
            except Exception as e:
                window['-INFO-'].update(f'Error: {e}', text_color='firebrick1')
                window['-COL-'].hide_row()
                import traceback
                print(traceback.format_exc())
                update_visibility(window, HIDDEN_BEFORE_PLOT_LINK, False)
                update_visibility(window, HIDDEN_BEFORE_PLOT_LINE, False)
                update_visibility(window, HIDDEN_BEFORE_PLOT, False)
        elif event == '-SAVEPLOT-':
            save_settings(window, APP_NAME)
            filename = sg.popup_get_file(
                message='Save plot', save_as=True,
                no_window=True,
                default_path=f'{tabletype}{values["-LINKID-"]}_{values["-LINES-"]}',
                keep_on_top=True,
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
        elif event in ['-SAVELINKTAB-', '-SAVELINETAB-']:
            save_settings(window, APP_NAME)
            filename = sg.popup_get_file(
                message='Save table', save_as=True,
                default_path=f'{tabletype}{values["-LINKID-"]}_{values["-LINES-"]}',
                keep_on_top=True,
                no_window=True,
                file_types=(("Comma separated values", "*.csv"),
                            ("Excel spreadsheet", "*.xlsx"))
                )
            if filename:
                try:
                    if filename.endswith('.xlsx'):
                        table.to_excel(filename, index=False)
                    else:
                        table.to_csv(
                            filename,
                            index=False,
                            **CSV_STYLE,
                            encoding='utf-8-sig'
                        )
                except Exception as e:
                    window['-INFO-'].update(
                        f'Error: {e}', text_color='firebrick1'
                        )
        elif event == '-SAVELINESHP-':
            save_settings(window, APP_NAME)
            filename = sg.popup_get_file(
                message='Save plot', save_as=True,
                no_window=True,
                default_path=f'{tabletype}{values["-LINKID-"]}_{values["-LINES-"]}',
                keep_on_top=True,
                file_types=(('ESRI shapefile', '*.shp'),)
                )
            if filename:
                try:
                    table.to_file(filename, encoding='utf-8')
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
        # counts_path=args.counts_path,
        # net_path=args.net_path
        )
