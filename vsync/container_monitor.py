from datetime import datetime, timedelta
import docker
import logging
import os
import signal
import subprocess
import time

HOST_PORT = '5000/tcp'

class ContainerMonitor(object):
    """
    Monitors volume mount/unmount events and creates notifiers for mounts matching patterns (vsync.enable=true).
    """

    def __init__(self):

        self.client = docker.from_env()
        self.notifiers = {}

    def __mount_event(self, event):
        container_manager = self.client.containers
        volume_manager = self.client.volumes

        volume_id = event['Actor']['ID']

        # Source folder which will be syncing
        volume_labels = volume_manager.get(volume_id).attrs['Labels']
        source_folder = volume_labels.get(
            'vsync.source')

        # Container other than vsync container and vsync container not existing ?
        vsync_container_id = volume_id + '-vsync'
        try:
            vsync_container = container_manager.get(vsync_container_id)
        except docker.errors.NotFound:
            vsync_container = None

        if vsync_container is None:
            data_mount = docker.types.Mount('/data', volume_id)
            container_manager.run('onnimonni/unison',
                                  name=vsync_container_id,
                                  environment={
                                      'UNISON_DIR': '/data'
                                  },
                                  remove=True,
                                  detach=True,
                                  ports={HOST_PORT: None},
                                  labels={
                                      'vsync.container': "true"
                                  },
                                  mounts=[data_mount])

            vsync_container = container_manager.get(vsync_container_id)
            host_port = vsync_container.attrs['NetworkSettings']['Ports'][HOST_PORT][0]['HostPort']

            unison_started = False
            while not unison_started:
                result = vsync_container.exec_run('pgrep -f unison');
                unison_started = True if result.exit_code == 0 else False

            home = os.path.expanduser("~")
            log_dir = home + '/.vsync/' + vsync_container_id

            if not os.path.exists(log_dir):
                os.makedirs(log_dir)

            unison_pid = subprocess.Popen([
                'unison',
                source_folder,
                'socket://localhost:' + host_port + '/',
                '-auto',
                '-repeat', 'watch',
                '-log',
                '-silent',
                '-logfile', log_dir + '/unison.log'   
            ], stdout=subprocess.DEVNULL).pid

            self.notifiers[vsync_container_id] = unison_pid

            logging.info(
                'Starting unison daemon (PID=%s)', unison_pid)
            logging.info(
                'Starting syncing of volume %s', volume_id)

    def __unmount_event(self, event):
        container_manager = self.client.containers

        volume_id = event['Actor']['ID']
        vsync_container_id = volume_id + '-vsync'

        # Terminate the process
        if vsync_container_id in self.notifiers:
            unison_pid = self.notifiers[vsync_container_id]
            logging.info(
                'Stopping unison daemon (PID=%s)', unison_pid)

            os.kill(unison_pid, signal.SIGINT)
            del self.notifiers[vsync_container_id]

        # Terminate vsync container
        try:
            vsync_container = container_manager.get(vsync_container_id)
        except docker.errors.NotFound:
            vsync_container = None
        
        if vsync_container is not None:
            vsync_container.stop()
            logging.info(
                'Stopping syncing of volume %s', volume_id)

    def __handle_event(self, event):
        volume_manager = self.client.volumes
        container_manager = self.client.containers

        switcher_volume_events = {
            'mount': lambda id: self.__mount_event(event),
            'unmount': lambda id: self.__unmount_event(event)
        }

        volume_id = event['Actor']['ID']

        try:
            volume_labels = volume_manager.get(volume_id).attrs['Labels']
        except docker.errors.NotFound:
            volume_labels = None

        vsync_enable = bool(volume_labels.get(
            'vsync.enable', False)) if volume_labels is not None else False

        # Filter mount/unmount from vsync container
        try:
            container_id = event['Actor']['Attributes']['container']
            container_labels = container_manager.get(
                container_id).attrs['Config']['Labels']
            is_vsync_container = bool(
                container_labels.get('vsync.container', False))
        except docker.errors.NotFound:
            is_vsync_container = False

        # Volume to synchronize?
        if vsync_enable and not is_vsync_container:
            event_volume_handler = switcher_volume_events.get(
                event['Action'], lambda id: None)
            event_volume_handler(event)

    def monitor(self):
        """
        Start listening and handling of volume mount/unmount events.
        """

        delta = timedelta(seconds=2)
        since = datetime.utcnow()
        until = datetime.utcnow() + delta
        filters = {'event': ['mount', 'unmount'],
                   'type': 'volume', 'scope': 'local'}
        while True:
            for event in self.client.events(since=since, until=until, decode=True, filters=filters):
                self.__handle_event(event)
            since = until
            until = datetime.utcnow() + delta
