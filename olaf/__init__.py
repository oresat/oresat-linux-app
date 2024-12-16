"""OLAF (OreSat Linux App Framework)"""

import sys
from argparse import ArgumentParser, Namespace
from logging.handlers import SysLogHandler
from typing import Optional

from loguru import logger
from oresat_configs import Mission, OreSatConfig

from ._internals.app import App, app
from ._internals.rest_api import RestAPI, render_olaf_template, rest_api
from ._internals.services.logs import LogServiceHandler
from ._internals.updater import Updater, UpdaterState
from .board.adc import Adc
from .board.cpufreq import A8_CPUFREQS, get_cpufreq, get_cpufreq_gov, set_cpufreq, set_cpufreq_gov
from .board.eeprom import Eeprom
from .board.gpio import GPIO_HIGH, GPIO_IN, GPIO_LOW, GPIO_OUT, Gpio, GpioError
from .board.pru import Pru, PruError, PruState
from .canopen.ecss import scet_int_from_time, scet_int_to_time, utc_int_from_time, utc_int_to_time
from .canopen.master_node import MasterNode
from .canopen.network import CanNetwork, CanNetworkError, CanNetworkState, NetworkError
from .canopen.node import Node, NodeStop
from .common.daemon import Daemon, DaemonState
from .common.oresat_file import OreSatFile, new_oresat_file
from .common.oresat_file_cache import OreSatFileCache
from .common.resource import Resource
from .common.service import Service, ServiceState

try:
    from ._version import version as __version__  # type: ignore
except ImportError:
    __version__ = "0.0.0"  # package is not installed

olaf_parser = ArgumentParser(prog="OLAF", add_help=False)
olaf_parser.add_argument("-b", "--bus", default="vcan0", help="CAN bus to use, defaults to vcan0")
olaf_parser.add_argument("-v", "--verbose", action="store_true", help="enable verbose logging")
olaf_parser.add_argument("-l", "--log", action="store_true", help="log to only journald")
olaf_parser.add_argument(
    "-m",
    "--mock-hw",
    nargs="*",
    metavar="HW",
    default=[],
    help='list the hardware to mock or just "all" to mock all hardware',
)
olaf_parser.add_argument(
    "-a", "--address", default="localhost", help="rest api address, defaults to localhost"
)
olaf_parser.add_argument(
    "-p", "--port", type=int, default=8000, help="rest api port number, defaults to 8000"
)
olaf_parser.add_argument(
    "-d",
    "--disable-flight-mode",
    action="store_true",
    help="disable flight mode on start, defaults to flight mode enabled",
)
olaf_parser.add_argument(
    "-o", "--oresat", default="oresat0.5", help="oresat mission; oresat0, oresat0.5, etc"
)
olaf_parser.add_argument(
    "-w", "--hardware-version", default="0.0", help="override the hardware version"
)
olaf_parser.add_argument("-n", "--number", type=int, default=1, help="card number")
olaf_parser.add_argument(
    "-t",
    "--bus-type",
    default="socketcan",
    help=(
        "can bus type; socketcan (default), socketcand, virtual, slcan, etc;"
        "see https://python-can.readthedocs.io/en/stable/configuration.html#interface-names"
    ),
)
olaf_parser.add_argument(
    "-H",
    "--socketcand-host",
    default="localhost",
    help='host for socketcand bus (only used if bus_type is "socketcand")',
)


def olaf_setup(name: str, args: Optional[Namespace] = None) -> tuple[Namespace, dict]:
    """
    Parse runtime args and setup the app and REST API.

    Parameters
    ----------
    name: str
        The card's node name.
    args: Namespace
        Optional runtime args. If not set, the default from `olaf_parser` will be used.

    Returns
    -------
    Namespace
        The runtime args.
    dict
        The OreSat configs.
    """

    if args is None:
        parser = ArgumentParser(parents=[olaf_parser])
        args = parser.parse_args()

    if args.verbose:
        level = "DEBUG"
    else:
        level = "INFO"

    logger.remove()  # remove default logger
    if args.log:
        logger.add(SysLogHandler(address="/dev/log"), level=level, backtrace=True)
    else:
        logger.add(sys.stdout, level=level, backtrace=True)
    logger.add(LogServiceHandler(), level=level, backtrace=True)

    config = OreSatConfig(Mission.from_string(args.oresat))

    if name not in config.cards:
        name += f"_{args.number}"
    if name not in config.cards:
        raise ValueError(f"invalid card {name} for {args.oresat}")

    od = config.od_db[name]

    if args.disable_flight_mode:
        od["flight_mode"].value = False

    version = "0.0"
    try:
        eeprom = Eeprom()
        version = f"{eeprom.major}.{eeprom.minor}"
        logger.info(f"detected v{version} card")
    except (PermissionError, FileNotFoundError):
        logger.warning("could not read hardware info from eeprom")
    if args.hardware_version != "0.0":
        version = args.hardware_version
    od["versions"]["hw_version"].value = version

    is_octavo = config.cards[name].processor == "octavo"
    if is_octavo:
        od["versions"]["olaf_version"].value = __version__

    network = CanNetwork(args.bus_type, args.bus, args.socketcand_host)
    od_db = config.od_db if name == "c3" else None

    app.setup(network, od, od_db, is_octavo)
    rest_api.setup(address=args.address, port=args.port)

    return args, config


def olaf_run():
    """Start the app and REST API."""

    rest_api.start()
    app.run()
    rest_api.stop()
