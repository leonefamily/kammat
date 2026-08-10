"""Lightweight read-only MATSim executable metadata helpers."""

from pathlib import Path
import re
from typing import Union


def get_matsim_version(
    matsim_executable: Union[str, Path],
    using_java: bool = False,
    java_bin: Union[str, Path] = "java",
) -> float:
    """Extract the current decimal MATSim version from a JAR filename."""

    del java_bin
    try:
        if using_java:
            UserWarning(
                "Extracting MATSim version using Java is not supported yet; "
                "falling back to the filename"
            )
        match = re.search(r"\d+\.\d+(?=\.jar$)", str(matsim_executable))
        if match is None:
            raise ValueError("MATSim version is absent")
        return float(match.group())
    except Exception as error:
        raise RuntimeError(
            "Unable to extract MATSim version from path: {0}. Should end with "
            "`x.x.jar`, where `x.x` is any decimal".format(matsim_executable)
        ) from error


def get_matsim_runnable_class(matsim_version: float) -> str:
    """Return the runnable class used by the given MATSim release."""

    if matsim_version <= 13.0:
        return "org.matsim.run.Controler"
    return "org.matsim.run.RunMatsim"


__all__ = ["get_matsim_runnable_class", "get_matsim_version"]
