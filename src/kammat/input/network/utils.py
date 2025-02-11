# -*- coding: utf-8 -*-
"""
Created on Tue Feb 11 15:03:01 2025.

@author: dgrishchuk
"""
import hashlib
import string
from typing import Tuple

ALPHABET = string.digits + string.ascii_letters


def int_to_base62(
        num: int,
        length: int = 8
) -> str:
    """
    Convert a non-negative int ``num`` to a Base62 string of fixed ``length``.

    Parameters
    ----------
    num : int
        Any non-negative integer.
    length : int, optional
        Desired length of the resulting string. The default is 8.

    Raises
    ------
    ValueError
        If ``num`` is negative.

    Returns
    -------
    str
        If the conversion results in a string shorter than 'length',
        resulting string is padded with '0's on the left.

    """
    if num < 0:
        raise ValueError("Number must be non-negative")

    digits = []
    while num:
        num, rem = divmod(num, 62)
        digits.append(ALPHABET[rem])
    if not digits:
        digits.append(ALPHABET[0])

    result = ''.join(reversed(digits))
    return result.rjust(length, ALPHABET[0])


def coordinate_to_string(
        coord: Tuple[float, float]
) -> str:
    """
    Convert a coordinate into a canonical string representation.

    Parameters
    ----------
    coord : Tuple[float, float]
        Tuple of latitude and longitude (or vice versa), 2D coordinate.

    Returns
    -------
    str
        Precision up to six decimals is supported, rest is truncated.

    """
    lat, lon = coord
    return f"{lat:.6f},{lon:.6f}"


def hash_coordinate(
        coord: Tuple[float, float],
        hash_len: int = 8
) -> str:
    """
    Compute an N-character hash for the given coordinate.

    1. Converting the coordinate to a canonical string.
    2. Hashing the string with SHA-256.
    3. Converting the binary hash to an integer.
    4. Reducing that integer modulo 62^6.
    5. Converting the reduced integer to a fixed-length Base62 string.

    Parameters
    ----------
    coord : Tuple[float, float]
        Tuple of x,y float coordinates. Decimal precision is limited
        to 6 decimal digits.
    hash_len : int, optional
        Desired length of the hash value string. The default is 8.

    Returns
    -------
    str
        Hash value of this coordinate.

    """
    coord_str = coordinate_to_string(coord)

    hash_obj = hashlib.sha256(coord_str.encode("utf-8"))
    digest = hash_obj.digest()

    hash_int = int.from_bytes(digest, byteorder="big")

    mod_space = 62 ** hash_len  # 62^n possibilities.
    reduced_int = hash_int % mod_space

    hash_value = int_to_base62(reduced_int, hash_len)
    return hash_value
