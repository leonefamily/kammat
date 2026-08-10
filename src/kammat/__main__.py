import logging

from kammat.defaults.constants import CACHE_SETTINGS_PATH, LOGGER_FORMAT
from kammat.main.run import main as run_main, create_directory, parse_args


def main():
    create_directory(CACHE_SETTINGS_PATH)
    logging.basicConfig(
        format=LOGGER_FORMAT,
        level=logging.INFO,
        filename=CACHE_SETTINGS_PATH + '/log_main.txt',
        filemode='w'
    )
    args = parse_args()
    run_main(
        config_path=args.config_path
    )
