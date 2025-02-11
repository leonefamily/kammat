from datetime import datetime
from pathlib import Path
from typing import Union, Optional
import lxml
from lxml import etree
import pandas as pd


def write_element_tree(
        tree: lxml.etree.ElementTree,
        path: Union[str, Path],
        merge_if_exists: bool = False
):
    if merge_if_exists:
        path_obj = Path(path)
        if path_obj.exists():
            parser = etree.XMLParser(remove_blank_text=True)
            old_tree = etree.parse(path, parser=parser)
            old_root = old_tree.getroot()
            root = tree.getroot()
            if old_root.tag != root.tag:
                raise AttributeError(
                    "Existing document's root tag is not the same as the "
                    f"one being merged with it. {old_root.tag} != {root.tag} "
                    f"at {path_obj.resolve()}"
                )
            for child in root:
                old_root.append(child)
            tree = old_root.getroottree()
    with open(path, 'wb') as xml_file:
        tree.write(
            xml_file,
            pretty_print=True,
            xml_declaration=True,
            encoding='UTF-8'
        )


def int2time(
        itime: int
) -> datetime.time:
    return pd.to_datetime(itime, unit='s').time()


def str2sec(
        td_str: str
) -> float:
    return pd.to_timedelta(td_str).total_seconds()
