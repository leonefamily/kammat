# -*- coding: utf-8 -*-
"""
Created on Thu Feb  9 12:02:03 2023

@author: dgrishchuk
"""

import gzip
import json
import logging
import sqlite3
import warnings
import traceback
import pandas as pd
import geopandas as gpd
from pathlib import Path
from datetime import timedelta as td
from collections import defaultdict, Counter
from typing import Union, List, Dict, Literal, Any, Union, Optional, Tuple

UNITS_IN_SECONDS = {
    's': 1,
    'm': 60,
    'h': 3600
}

EVENTS_MODES = ('car', 'truck')
LINK_STATS_FIGURE_SIZE = (12, 6)
LINK_STATS_DF_COLS = ('timestep', *EVENTS_MODES, 'total')
RIBBON_DIAGRAMS_DF_COLS = ('from_link', 'to_link', 'from_group', 'to_group', 'count')
RIBBON_DIAGRAMS_GROUP_DF_COLS = ('group', 'left', 'entered', 'total')
PT_STATS_DF_COLS = ('link_id', 'from_stop', 'to_stop', 'count')
PT_LINK_STATS_DF_COLS = ('timestep', 'line', 'passengers')
PT_STOPS_STATS_DF_COLS = ('',)

MODES_COLORS = {
    'pt': 'C0',
    'car': 'C3',
    'truck': 'C5',
    'citylog': 'C6',
    'total': 'C7'
}


class DbHandler:

    MODES_MAP = {
        'car': 0,
        'pt': 1,
        'truck': 2
    }

    def __init__(
            self,
            db_path: Union[str, Path],
            flush_interval: int = 10_000_000
    ):
        self._db_path: Path = Path()
        self._conn: sqlite3.Connection = None
        self._zstd_ok = False

        self._vehicle_trip_nums: Dict[str, int] = defaultdict(int)
        self._vehicle_modes: Dict[str, int] = {}
        self._vehicle_ids: Dict[str, int] = {}
        self._next_vehicle_id: int = 0
        self._vehicle_trip_ids: Dict[Tuple[int, int], int] = {}
        self._next_vehicle_trip_id: int = 0
        self._link_ids: Dict[str, int] = {}
        self._next_link_id: int = 0
        self._vehicle_data_buffer: List[Tuple[int]] = []

        self._flush_interval: Optional[int] = None
        self._last_flushed_link_id: int = -1
        self._last_flushed_vehicle_id: int = -1
        self._last_flushed_vehicle_trip_id: int = -1
        self._modes_written: bool = False

        self.set_db_path(db_path=db_path)
        self.set_flush_interval(every=flush_interval)

    def create(self):
        if self.db_path.exists():
            self.db_path.unlink()

        self.connect()
        try:
            import sqlite_zstd
            self._conn.enable_load_extension(True)
            sqlite_zstd.load(self._conn)
            self._zstd_ok = True
        except Exception as e:
            warnings.warn(
                f'sqlite_zstd was not found, using normal sqlite3, {e}'
            )
            self._zstd_ok = False

        self._conn.execute('''
            CREATE TABLE links (
                orig_link_id TEXT(256) UNIQUE NOT NULL,
                link_id INTEGER PRIMARY KEY
            );
        ''')
        self._conn.execute('''
            CREATE TABLE modes (
                mode_name TEXT(64) UNIQUE NOT NULL,
                mode_id INTEGER PRIMARY KEY
            );
        ''')
        self._conn.execute('''
            CREATE TABLE vehicles (
                orig_vehicle_id TEXT(256) UNIQUE NOT NULL,
                vehicle_id INTEGER PRIMARY KEY,
                mode_id INTEGER,
                FOREIGN KEY (mode_id) REFERENCES modes(mode_id)
            );
        ''')
        self._conn.execute('''
            CREATE TABLE trips (
                vehicle_id INTEGER,
                trip_num INTEGER NOT NULL,
                trip_id INTEGER PRIMARY KEY,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles(vehicle_id)
            );
        ''')
        self._conn.execute('''
            CREATE TABLE events (
                trip_id INTEGER,
                link_id INTEGER,
                prev_link_id INTEGER,
                time INTEGER NOT NULL,
                FOREIGN KEY (trip_id) REFERENCES trips(trip_id),
                FOREIGN KEY (prev_link_id) REFERENCES links(link_id)
                FOREIGN KEY (link_id) REFERENCES links(link_id)
            );
        ''')
        self._conn.commit()
        self.close()

    def connect(self):
        self._conn = sqlite3.connect(self.db_path)

    def reset(self):
        """Clear all values except for the DB path and flush interval."""
        self._vehicle_trip_nums = defaultdict(int)
        self._vehicle_data_buffer = []
        self._vehicle_modes = {}
        self._vehicle_ids = {}
        self._next_vehicle_id = 0
        self._vehicle_trip_ids = {}
        self._next_vehicle_trip_id = 0
        self._link_ids = {}
        self._next_link_id = 0

        # self._flush_interval = None
        self._last_flushed_link_id = -1
        self._last_flushed_vehicle_id = -1
        self._last_flushed_vehicle_trip_id = -1
        self._modes_written = False

    @property
    def db_path(self) -> Path:
        return self._db_path

    def set_db_path(
            self,
            db_path: Union[str, Path]
    ):
        pre_db_path = Path(db_path).resolve()
        if not pre_db_path.parent.exists():
            raise ValueError(
                f'{pre_db_path} parent directory does not exist'
            )
        if self.db_path != pre_db_path:
            self.reset()
        self._db_path = pre_db_path

    @property
    def flush_interval(self) -> Optional[int]:
        return self._flush_interval

    def set_flush_interval(
            self,
            every: Optional[int]
    ) -> Optional[int]:
        if isinstance(every, int):
            if every < 0:
                raise ValueError(
                    'Flush interval may only be 0 or a positive integer'
                )
            elif every == 0:
                self._flush_interval = None
            else:
                self._flush_interval = every
        elif every is None:
            self._flush_interval = None
        else:
            raise ValueError(
                'Flush interval may only be a None, 0 or a positive integer'
            )

    def enable_compression(self):
        """Don't use yet, unprepared."""
        raise NotImplementedError(
            'This method is a work in progress'
        )
        self.connect()
        self._conn.execute(
            """SELECT
            zstd_enable_transparent(
                '{"table": "links",
                "column": "orig_link_id",
                "compression_level": 19,
                "dict_chooser": "''a''"}'
            );
            """
        )
        self._conn.execute(
            """SELECT
            zstd_enable_transparent(
                '{"table": "vehicles",
                "column": "orig_vehicle_id",
                "compression_level": 19,
                "dict_chooser": "''a''"}'
            );
            """
        )
        self._conn.execute(
            """
            SELECT VACUUM;
            """
        )
        self.close()

    def connect(self):
        self._conn = sqlite3.connect(self.db_path)

    def close(self):
        self._conn.close()

    def flush(self):
        if not self.db_path.exists():
            self.create()
        self.connect()
        if not self._modes_written:
            self._conn.executemany(
                "INSERT INTO modes(mode_name, mode_id) VALUES (?,?)",
                list(self.MODES_MAP.items())
            )
            self._conn.commit()
            self._modes_written = True
        self._conn.executemany(
            "INSERT INTO links(orig_link_id, link_id) VALUES (?,?)",
            [(k, v) for k, v in self._link_ids.items()
             if v > self._last_flushed_link_id]
        )
        self._conn.executemany(
            "INSERT INTO vehicles(orig_vehicle_id, vehicle_id, mode_id) "
            "VALUES (?,?,?)",
            [(k, v, self._vehicle_modes[k])
             for k, v in self._vehicle_ids.items()
             if v > self._last_flushed_vehicle_id]
        )
        self._conn.executemany(
            "INSERT INTO trips(vehicle_id, trip_num, trip_id) VALUES (?,?,?)",
            [(k[0], k[1], v) for k, v in self._vehicle_trip_ids.items()
             if v > self._last_flushed_vehicle_trip_id]
        )
        self._conn.executemany(
            "INSERT INTO events(trip_id, link_id, prev_link_id, time) "
            "VALUES (?,?,?,?)",
            self._vehicle_data_buffer
        )
        self._conn.commit()
        self.close()

        self._vehicle_data_buffer.clear()
        self._last_flushed_link_id = next(
            reversed(
                self._link_ids.values()
            )
        )
        self._last_flushed_vehicle_id = next(
            reversed(
                self._vehicle_ids.values()
            )
        )
        self._last_flushed_vehicle_trip_id = next(
            reversed(
                self._vehicle_trip_ids.values()
            )
        )

    def process_entered(
            self,
            event: Dict[str, Union[str, int, float]],
            mode: str,
            last_visited_link: Optional[str] = None,
            report: bool = True
    ):
        veh = event['vehicle']
        link = event['link']
        if veh not in self._vehicle_ids:
            self._vehicle_modes[veh] = self.MODES_MAP[mode]
            self._vehicle_ids[veh] = self._next_vehicle_id
            self._next_vehicle_id += 1
        vid = self._vehicle_ids[veh]

        if last_visited_link is not None:
            if last_visited_link not in self._link_ids:
                self._link_ids[last_visited_link] = self._next_link_id
                self._next_link_id += 1
        if link not in self._link_ids:
            self._link_ids[link] = self._next_link_id
            self._next_link_id += 1
        lid = self._link_ids[link]

        trip_num = self._vehicle_trip_nums[veh]
        vid_trip_num = vid, trip_num
        if vid_trip_num not in self._vehicle_trip_ids:
            self._vehicle_trip_ids[vid_trip_num] = self._next_vehicle_trip_id
            self._next_vehicle_trip_id += 1
        veh_trip_id = self._vehicle_trip_ids[vid_trip_num]

        if isinstance(last_visited_link, str):
            lastlink = self._link_ids[last_visited_link]
        else:
            lastlink = last_visited_link

        self._vehicle_data_buffer.append((
            veh_trip_id,
            lid,
            lastlink,
            int(event['time'])
        ))

        if self.flush_interval is None:
            return

        if len(self._vehicle_data_buffer) % self.flush_interval == 0:
            curlen = len(self._vehicle_data_buffer)
            self.flush()
            if report:
                logging.info(
                    f"Wrote {curlen} "
                    f"to DB {self.db_path}, "
                    f"trip {self._last_flushed_vehicle_trip_id}, "
                    f"link {self._last_flushed_link_id}"
                )

    def get_mode_trip_ids(
            self,
            mode: str
    ) -> List[int]:
        req_mode_trip_ids_col = self._conn.execute(
            f"""WITH found_mode AS (
                SELECT mode_id
                FROM modes
                WHERE mode_name = '{mode}'
            ), mode_vehicles AS (
                SELECT vehicle_id
                FROM vehicles
                WHERE mode_id IN (SELECT mode_id FROM found_mode)
            ), mode_trips AS (
                SELECT trip_id
                FROM trips
                WHERE vehicle_id IN (SELECT vehicle_id FROM mode_vehicles)
            )
            SELECT * FROM mode_trips;
            """
        ).fetchall()

        if not req_mode_trip_ids_col:
            raise ValueError(f'Probably wrong mode {mode}')
        req_mode_trip_ids = [v[0] for v in req_mode_trip_ids_col]
        return req_mode_trip_ids

    def get_decay_diagram(
            self,
            net: gpd.GeoDataFrame,
            link_id: Union[str, List[str]],
            start_time: int = 25200,
            end_time: int = 28800,
            mode: str = 'car'
    ):
        link_id_repr = (
            'IN (' + ','.join(f"'{lid}'" for lid in link_id) + ')'
            if isinstance(link_id, list)
            else f"= '{link_id}'"
        )
        limit_str = 'LIMIT 1' if isinstance(link_id, str) else ''
        self.connect()

        data_start_time = self._conn.execute(
            "SELECT * FROM events ORDER BY ROWID ASC LIMIT 1"
        ).fetchone()[-1]

        data_end_time = self._conn.execute(
            "SELECT * FROM events ORDER BY ROWID DESC LIMIT 1"
        ).fetchone()[-1]

        if start_time <= data_start_time and end_time >= data_end_time:
            time_constr = ''
        else:
            time_constr = (
                f'"time" BETWEEN {int(start_time)} AND {int(end_time)} AND'
            )

        req_mode_trip_ids = self.get_mode_trip_ids(mode=mode)

        link_trip_ids_col = self._conn.execute(
            f"""WITH found_links AS (
                SELECT link_id
                FROM links
                WHERE orig_link_id {link_id_repr}
                {limit_str}
            ), affected_trips AS (
                SELECT trip_id,"time"
                FROM events
                WHERE {time_constr}
                trip_id IN ({','.join(str(v) for v in req_mode_trip_ids)})
                AND link_id IN (SELECT link_id FROM found_links)
            )
            SELECT * FROM affected_trips;
            """
        ).fetchall()

        if isinstance(link_id, list):
            keep_trip_ids = [
                k for k, v in Counter(
                    [row[0] for row in link_trip_ids_col]
                ).items() if v == len(link_id)
            ]
            link_trip_ids_col = [
                row for row in link_trip_ids_col if row[0] in keep_trip_ids
            ]

        link_interaction_times = defaultdict(list)
        for trip_id, timestep in link_trip_ids_col:
            link_interaction_times[trip_id].append(timestep)
        link_interaction_times = dict(link_interaction_times)

        # not needed anymore
        del req_mode_trip_ids, link_trip_ids_col

        links_of_trips_col = self._conn.execute(
            f"""
            SELECT link_id,trip_id,"time" FROM events WHERE trip_id IN (
                {','.join(str(v) for v in link_interaction_times.keys())}
            );
            """
        ).fetchall()
        # we don't need time specifically, just whether before or after link_id
        unique_ids = set(v[0] for v in links_of_trips_col)

        orig_links_ids_map = dict(self._conn.execute(
            f"""
            SELECT link_id, orig_link_id FROM links WHERE link_id IN (
                {','.join(str(v) for v in unique_ids)}
            );
            """
        ).fetchall())
        self.close()

        links_of_trips_new_col = [
            (
                orig_links_ids_map[link],
                ('before' if time <= min(link_interaction_times[trip])
                 else (
                     'after' if time > max(link_interaction_times[trip])
                     else 'selected')
                 )
            )
            for link, trip, time in links_of_trips_col
        ]
        links_counts = Counter(links_of_trips_new_col)
        link_counts_df = pd.DataFrame(links_counts, index=[mode]).transpose()
        link_counts_df.index.rename(['link_id', 'when'], inplace=True)
        link_counts_df = link_counts_df.reset_index()
        link_counts_df.loc[link_counts_df['when'].isna(), 'when'] = 'selected'
        net_counts = net.merge(link_counts_df, on='link_id', how='right')
        return net_counts

    def get_ribbon_diagram_data(
            self,
            net: gpd.GeoDataFrame,
            link_id: Union[str, List[str]],
            start_time: int = 25200,
            end_time: int = 28800,
            mode: str = 'car'
    ):
        pass


def get_timeline(
        start: int = 0,
        stop: int = 86400,  # 24 hours
        aggregate_by: int = 3600,  # 1 hour
        aggregate_unit: Literal['s', 'm', 'h'] = 'h'
        ) -> List[Union[int, float]]:
    """
    Prepare timeline.

    Parameters
    ----------
    start : int, optional
        Period start time IN SECONDS. The default is 0.
    stop : int, optional
        Period end time IN SECONDS. The default is 86400.
    aggregate_by : int, optional
        Split timeline by this value IN SECONDS. The default is 3600.
    aggregate_unit : Literal['s', 'm', 'h'], optional
        By values of what unit should be list populated. The default is 'h'.

    Returns
    -------
    List[Union[int, float]]

    """
    timeline = set()
    current = start
    while current < stop:
        timeline.add(
            round_timestep(current, aggregate_by, aggregate_unit)
            )
        current += aggregate_by
    return sorted(timeline)


def round_timestep(
        current: int,
        aggregate_by: int = 3600,
        aggregate_unit: Literal['s', 'm', 'h'] = 'h'
        ) -> int:
    raw = int(current / aggregate_by) * aggregate_by
    return raw / UNITS_IN_SECONDS[aggregate_unit]


def get_timestep_precision(
        link_stats: Dict[str, List[float]],
        timesteps_are_keys: bool = False
        ) -> float:
    gaps = []
    timesteps = list(link_stats.keys()) if timesteps_are_keys else link_stats['timestep'] 
    for i, timestep in enumerate(timesteps):
        if i != 0:
            gaps.append(timestep - timesteps[i - 1])
    maxgap = Counter(gaps).most_common()[0][0]
    return maxgap


def defaultdict2dict(d):
    for k, v in d.items():
        if isinstance(v, dict):
            d[k] = defaultdict2dict(v)
    return dict(d)


def read_json(
        p: Union[str, Path]
        ) -> Dict[Any, Any]:
    """
    Read any JSON.

    Parameters
    ----------
    p : Union[str, Path]
        Path

    Returns
    -------
    Dict[Any, Any]
        Any JSON.

    """
    with open(p, mode='r', encoding='utf-8') as f:
        return json.load(f)


def write_json(
        o: Any,
        p: Union[str, Path]
        ):
    """
    Write any JSON with 4 indent spaces.

    Parameters
    ----------
    p : Union[str, Path]
        Path

    """
    with open(p, mode='w', encoding='utf-8') as f:
        return json.dump(o, f, indent=4)


def write_json_gz(
        json_like: Any,
        path: Union[str, Path]
):
    """
    Write a gzipped JSON, which takes less space on disk.

    Parameters
    ----------
    json_like : Any
        Any object that can be converted to JSON.
    path : Union[str, Path]
        Path to dump object.

    """
    with gzip.open(path, 'wt', encoding="utf-8") as zipfile:
        json.dump(json_like, zipfile)


def read_json_gz(
        path: Union[str, Path]
) -> Any:
    """
    Read a gzipped JSON.

    Parameters
    ----------
    path : Union[str, Path]
        Path to json-like object.

    Returns
    -------
    Any
        Whatever was stored in the json.gz.

    """
    with gzip.open(path, 'r') as fin:
        json_like = json.loads(fin.read().decode('utf-8'))
    return json_like


def td2str(
        tdo: td
) -> str:
    """
    Convert timedelta object to a string in HH:MM:SS format.

    Parameters
    ----------
    tdo : td
        Timedelta object.

    Returns
    -------
    str

    """
    rmins, secs = divmod(tdo.total_seconds(), 60)
    hrs, mins = divmod(rmins, 60)
    h = f'{int(hrs)}'.zfill(2)
    m = f'{int(mins)}'.zfill(2)
    s = f'{round(secs)}'.zfill(2)
    return f'{h}:{m}:{s}'
