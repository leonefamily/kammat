# -*- coding: utf-8 -*-
"""
Created on Wed Jul 27 15:19:26 2022

!!! Update

@author: dgrishchuk
"""
import pandas as pd
import geopandas as gpd
from typing import Dict, Optional
from shapely.geometry import Point, LineString


def create_links(
        gtfs: Dict[str, pd.DataFrame],
        target_crs: Optional[str] = 'epsg:4326'
) -> gpd.GeoDataFrame:
    predfs = []
    trips = gtfs['stop_times'].trip_id.unique()
    for trip in trips:
        trip_df = gtfs['stop_times'][gtfs['stop_times']['trip_id'] == trip].sort_values('stop_sequence')
        st = trip_df.iloc[:-1].reset_index(drop=True)
        en = trip_df.iloc[1:].reset_index(drop=True)
        mrg = st.join(en, lsuffix='1', rsuffix='2')
        predfs.append(mrg)
    dfs = pd.concat(predfs)

    dfs['stops_comb'] = dfs['stop_id1'] + '|' + dfs['stop_id2']

    ndfs = dfs.groupby('stops_comb').size().to_frame().reset_index().rename({0: 'count'}, axis=1)
    ndfs[['stop_id1', 'stop_id2']] = ndfs['stops_comb'].str.split('|', expand=True)
    ndfs.drop('stops_comb', axis=1, inplace=True)

    gtfs['stops']['geometry'] = gtfs['stops'].apply(
        lambda r: Point([r.stop_lon, r.stop_lat]), axis=1
    )

    ren1 = {orig: f'{orig}1' for orig in gtfs['stops'].columns}
    ren2 = {orig: f'{orig}2' for orig in gtfs['stops'].columns}
    ndfs = ndfs.merge(gtfs['stops'].rename(ren1, axis=1))
    ndfs = ndfs.merge(gtfs['stops'].rename(ren2, axis=1))
    ndfs['geometry'] = ndfs[['geometry1', 'geometry2']].apply(lambda r: LineString(r.tolist()), axis=1)
    gdfs = gpd.GeoDataFrame(ndfs).set_crs(target_crs)
    gdfs.drop(['geometry1', 'geometry2'], axis=1, inplace=True)
    return gdfs


if __name__ == '__main__':
    pass
