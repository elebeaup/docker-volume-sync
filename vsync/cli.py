"""Usage:
  vsync [options]
 
Options:
  -h, --help        Show this help message
  -v, --version     Print version information and quit 
"""

from docopt import docopt, DocoptExit
import logging
import sys

from vsync import __version__
from vsync.container_monitor import ContainerMonitor


def main():
    format = '%(asctime)-15s %(message)s'
    logging.basicConfig(level=logging.INFO, format=format)

    try:
        docopt(__doc__, version=__version__)
    except DocoptExit:
        print(__doc__)
    else:
        monitor = ContainerMonitor()

        try:
            monitor.monitor()
        except KeyboardInterrupt:
            sys.exit(0)
