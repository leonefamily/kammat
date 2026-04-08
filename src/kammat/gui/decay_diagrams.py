# -*- coding: utf-8 -*-
"""
Created on Thu Jul 25 10:23:53 2024

@author: dgrishchuk
"""

import sys
import shlex
import argparse
import pandas as pd
from typing import List, Union, Optional

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import traceback

from datetime import timedelta as td
from kammat.output.road import load_network
from kammat.output.utils import DbHandler, LINK_STATS_FIGURE_SIZE
from kammat.output.pt import (
    load_pt_schedule, get_transit_stops, warn_multiple_vehs,
    get_pt_decay_diagram
)

from kammat.gui.utils import (
    save_settings, restore_settings, update_visibility, put_plot_to_image,
    handle_time_change
)

from kammat.defaults.constants import CSV_STYLE

import PySimpleGUI as sg
sg.theme('default1')

APP_NAME = 'decay_diagrams'
HIDDEN_BEFORE_LOAD = ['-LINKIDTEXT-', '-LINKID-',
                      '-MODETEXT-', '-MODECAR-', '-MODETRUCK-', '-MODEPT-',
                      '-FILLER-', '-FIND-',
                      '-TMHINT-', '-D1-', '-START-', '-STARTHMS-', '-D2-',
                      '-END-', '-ENDHMS-']
HIDDEN_BEFORE_PLOT = ['-COL-', '-IMAGE-', '-SAVEPLOT-',
                      '-LINKTAB-', '-SAVELINKTAB-', '-SAVELINKSHP-']


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
    parser.add_argument('-d', '--db-path')
    parser.add_argument('-n', '--net-path')
    args = parser.parse_args()
    return args


def get_decay_plot(
        count_gdf: gpd.GeoDataFrame,
        link_id: Optional[str] = None,
        mode: Optional[Union[str, List[str]]] = None,
        start_time: Optional[Union[int, float]] = None,
        end_time: Optional[Union[int, float]] = None
) -> matplotlib.figure.Figure:
    """
    Get plot of links with widths corresponding to counts.

    Parameters
    ----------
    count_gdf : gpd.GeoDataFrame
        DESCRIPTION.
    link_id : Optional[str], optional
        DESCRIPTION. The default is None.
    mode : Optional[Union[str, List[str]]], optional
        DESCRIPTION. The default is None.
    start_time : Optional[Union[int, float]], optional
        DESCRIPTION. The default is None.
    end_time : Optional[Union[int, float]], optional
        DESCRIPTION. The default is None.

    Returns
    -------
    matplotlib.figure.Figure

    """
    bins = np.linspace(count_gdf[mode].min(), count_gdf[mode].max(), 100)
    width = pd.cut(
        count_gdf[mode],
        bins=bins
    ).cat.codes / 100 * 15

    ax = count_gdf.plot(
        linewidth=width,
        column='when',
        # for now False, till we get before/after link
        legend=True,
        figsize=LINK_STATS_FIGURE_SIZE
    )
    fig = ax.get_figure()

    ax.tick_params(
        axis='both', which='both', labelbottom=False, bottom=False,
        right=False, left=False, top=False
    )
    plt.axis('off')
    ax.spines['top'].set_visible(False)

    title = 'Decay diagram'
    if isinstance(link_id, str):
        title += f' of link {link_id}'
    elif isinstance(link_id, list):
        title += f' of links {link_id[0]} - {link_id[-1]}'
    ax.set_title(title)

    subtitle = ' — '.join(
        str(td(seconds=t)) for t in [start_time, end_time] if t is not None
    )
    fig.supxlabel(subtitle)
    return fig


def main(
        db_path: str = None,
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
    linelinks_tab = [[sg.Column([
       [sg.Image(None, size=(800, 400), key='-IMAGE-', visible=False)],
       [sg.Button('Save plot...', key='-SAVEPLOT-',
                  visible=False, size=10,
                  file_types=(('PNG', '.png'), ('JPG', '.jpg')),)],
       [sg.Table(values=[], headings=['Statistics'], key='-LINKTAB-',
                 num_rows=5, expand_x=True, visible=False),],
       [sg.Button('Save table...', key='-SAVELINKTAB-',
                  visible=False, size=10,
                  file_types=(('Comma separated values', '*.csv'),
                              ('Excel binary file', '*.xlsx')),),
        sg.Button('Save shapefile...', key='-SAVELINKSHP-',
                   visible=False, file_types=(('ESRI shapefile', '*.shp'),))]
       ],
       visible=False, key='-COL-', expand_x=True, scrollable=True,
       vertical_scroll_only=True, expand_y=True, size=(820, 580))]
    ]

    layout = [
        [sg.Text('', key='-INFO-', size=60,
                 font=("Courier New", sg.DEFAULT_FONT[1]))],
        [sg.Text('Events DB', size=10),
         sg.Input(db_path if db_path else '',
                  key='-DBPATH-', size=50, expand_x=True),
         sg.FileBrowse(key='-DB-', size=6,
                       file_types=(("SQLite database", "*.db"),))],
        [sg.Text('Network file', size=10),
         sg.Input(net_path if net_path else '',
                  key='-NETPATH-', size=50, expand_x=True),
         sg.FileBrowse(key='-NET-', size=6,
                       file_types=(("MATSim network file", "*.xml.gz"),
                                   ("MATSim network file", "*.xml")))],
        [sg.Text('Legs file', size=10),
         sg.Input(db_path if db_path else '',
                  key='-LEGSPATH-', size=50, expand_x=True),
         sg.FileBrowse(key='-LEGS-', size=6,
                       file_types=(("Comma separated values", "*.csv"),
                                   ("GZ archive", "*.csv.gz")))],
        [sg.Text('PT schedule', size=10),
         sg.Input(db_path if db_path else '',
                  key='-SCHEDPATH-', size=50, expand_x=True),
         sg.FileBrowse(key='-SCHED-', size=6,
                       file_types=(("Comma separated values", "*.xml"),
                                   ("GZ archive", "*.xml.gz")))],
        [sg.Text('', expand_x=True), sg.Button('Load', key='-LOAD-', size=6)],
        [sg.Text('Link ID(s)', key='-LINKIDTEXT-', size=10, visible=False),
         sg.Input('', key='-LINKID-', visible=False, expand_x=True)],
        [sg.Text('Mode', key='-MODETEXT-', size=10, visible=False),
         sg.Checkbox('car', key='-MODECAR-', visible=False),
         sg.Checkbox('truck', key='-MODETRUCK-', visible=False),
         sg.Checkbox('pt', key='-MODEPT-', visible=False)],
         [sg.Text('Time start/end', size=10, visible=False, key='-TMHINT-'),
          sg.Slider(range=(0, 86400), default_value=0, resolution=60,
                    key='-START-', orientation='h', enable_events=True,
                    visible=False),
          sg.Slider(range=(0, 86400), default_value=86400, resolution=60,
                    key='-END-', orientation='h', enable_events=True,
                    visible=False)],
         [sg.Text('', key='-D1-', size=10, visible=False),
          sg.Text('00:00:00', key='-STARTHMS-', size=10, visible=False),
          sg.Text('', key='-D2-', size=10, visible=False),
          sg.Text('24:00:00', key='-ENDHMS-', size=10, visible=False)],
         [sg.Text('', expand_x=True, visible=False, key='-FILLER-'),
          sg.Button('Find', key='-FIND-', size=6, visible=False)],
         linelinks_tab
    ]

    window = sg.Window('Decay diagrams tool', layout, finalize=True)
    restore_settings(window, APP_NAME)
    handle_time_change(window=window)

    if db_path is not None:
        window['-DBPATH-'].update(db_path)
    if net_path is not None:
        window['-NETPATH-'].update(net_path)

    while True:
        event, values = window.read()
        if event == sg.WIN_CLOSED:
            break
        window['-INFO-'].update(value='', text_color='black')
        if event == '-LOAD-':
            update_visibility(window, HIDDEN_BEFORE_PLOT, False)
            update_visibility(window, HIDDEN_BEFORE_LOAD, False)
            save_settings(window, APP_NAME)
            # if not all([window['-NETPATH-'].get(),
            #             window['-DBPATH-'].get()]):
            #     window['-INFO-'].update(
            #         'Fill all fields', text_color='firebrick1'
            #     )
            # else:
            window['-INFO-'].update(
                'Loading files... Might take a while', text_color='black'
            )
            try:
                net = load_network(window['-NETPATH-'].get())
                if window['-DBPATH-'].get():
                    dbh = DbHandler(db_path=values['-DBPATH-'])
                else:
                    dbh = None
                if window['-SCHEDPATH-'].get():
                    pt_schedule = load_pt_schedule(
                        window['-SCHEDPATH-'].get()
                    )
                    warn_multiple_vehs(pt_schedule=pt_schedule)
                    pt_stops = get_transit_stops(
                        pt_schedule,
                        include_geometries=True
                    )
                else:
                    pt_schedule = None
                    pt_stops = None
                if window['-LEGSPATH-'].get():
                    legs = pd.read_table(
                        window['-LEGSPATH-'].get(),
                        sep=';',
                        decimal=',',
                        converters={'transit_route': str,
                                    'transit_line': str,
                                    'vehicle_id': str}
                    )
                    pt_legs = legs[
                        legs['trip_id'].isin(
                            legs.loc[legs['mode'] == 'pt', 'trip_id'].unique()
                        )
                    ].reset_index(drop=True)
                else:
                    pt_legs = None
                window['-INFO-'].update('Files loaded')
                update_visibility(window, HIDDEN_BEFORE_LOAD, True)
                save_settings(window, APP_NAME)
            except Exception as e:
                window['-INFO-'].update(
                    f'Error: {e}', text_color='firebrick1'
                )
                print(traceback.format_exc())
        elif event == '-FIND-':
            save_settings(window, APP_NAME)
            try:
                lsplit = shlex.split(window['-LINKID-'].get())
                if not lsplit:
                    window['-INFO-'].update(
                        'Error: Empty query', text_color='firebrick1'
                    )
                    continue

                if len(lsplit) == 1:
                    links_obj = lsplit[0]  # str
                else:
                    links_obj = lsplit

                mode = [
                    window[k].widget.cget("text") for k, v in values.items()
                    if isinstance(k, str) is not None and
                    k.startswith('-MODE') and v is True
                ].pop()
                link_id = links_obj
                start_time = int(values['-START-'])
                end_time = int(values['-END-'])

                if mode == 'pt':
                    count_gdf = get_pt_decay_diagram(
                        pt_net=net,
                        pt_legs=pt_legs,
                        pt_stops=pt_stops,
                        pt_schedule=pt_schedule,
                        link_stops_ids=shlex.split(link_id),
                        by='link_id',
                        start_time=start_time,
                        end_time=end_time
                    )
                else:
                    count_gdf = dbh.get_decay_diagram(
                        net=net,
                        link_id=link_id,
                        start_time=start_time,
                        end_time=end_time,
                        mode=mode
                    )
                count_df = pd.DataFrame(
                    count_gdf[['link_id', mode if mode != 'pt' else 'count']]
                )
                count_link = count_df.loc[
                    (count_df['link_id'] == links_obj)
                    if isinstance(links_obj, str) else
                    (count_df['link_id'].isin(links_obj)),
                    mode if mode != 'pt' else 'count'
                ].iloc[0]
                showtable = pd.DataFrame([
                    f'{"Vehicles" if mode != "pt" else "Passengers"} '
                    f"through link/profile by mode {mode}: {count_link}"
                ])
                fig = get_decay_plot(
                    count_gdf=count_gdf,
                    link_id=links_obj,
                    mode=mode if mode != 'pt' else 'count'
                )
                window['-COL-'].unhide_row()
                update_visibility(window, HIDDEN_BEFORE_PLOT, True)
                put_plot_to_image(window, '-IMAGE-', fig)
                window['-LINKTAB-'].update(
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
                print(traceback.format_exc())
                update_visibility(window, HIDDEN_BEFORE_PLOT, False)
        elif event == '-SAVEPLOT-':
            save_settings(window, APP_NAME)
            filename = sg.popup_get_file(
                message='Save plot', save_as=True,
                no_window=True,
                default_path=f'decay_{links_obj}_{start_time}-{end_time}',
                keep_on_top=True,
                file_types=(
                    ("JPEG file", "*.jpg"), ("PNG file", "*.png")
                )
            )
            if filename:
                try:
                    fig.savefig(filename, dpi=200,
                                transparent=filename.endswith('.png'))
                except Exception as e:
                    window['-INFO-'].update(
                        f'Error: {e}', text_color='firebrick1'
                        )
                    print(traceback.format_exc())
        elif event in ['-SAVELINKTAB-', '-SAVELINETAB-']:
            save_settings(window, APP_NAME)
            filename = sg.popup_get_file(
                message='Save table', save_as=True,
                default_path=f'decay_{links_obj}_{start_time}-{end_time}',
                keep_on_top=True,
                no_window=True,
                file_types=(
                    ("Comma separated values", "*.csv"),
                    ("Excel spreadsheet", "*.xlsx")
                )
            )
            if filename:
                try:
                    if filename.endswith('.xlsx'):
                        count_df.to_excel(filename, index=False)
                    else:
                        count_df.to_csv(
                            filename,
                            index=False,
                            **CSV_STYLE,
                            encoding='utf-8-sig'
                        )
                except Exception as e:
                    window['-INFO-'].update(
                        f'Error: {e}', text_color='firebrick1'
                    )
                    print(traceback.format_exc())
        elif event == '-SAVELINKSHP-':
            save_settings(window, APP_NAME)
            filename = sg.popup_get_file(
                message='Save plot', save_as=True,
                no_window=True,
                default_path=f'decay_{links_obj}_{start_time}-{end_time}',
                keep_on_top=True,
                file_types=(
                    ('ESRI shapefile', '*.shp'),
                )
            )
            if filename:
                try:
                    count_gdf.to_file(filename, encoding='utf-8')
                except Exception as e:
                    window['-INFO-'].update(
                        f'Error: {e}', text_color='firebrick1'
                    )
                    print(traceback.format_exc())
        elif event in ['-START-', '-END-']:
            handle_time_change(window=window, event=event, values=values)
    window.close()


if __name__ == '__main__':
    args = parse_args()
    main(
        # counts_path=args.counts_path,
        # net_path=args.net_path
        )
