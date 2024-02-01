import os
import logging
from .metricsCollectors._clusterInformation import ClusterInformation

class Server:
    def __init__(self):
        format = "%(asctime)s: %(message)s"
        logging.basicConfig(format=format, level=logging.INFO, datefmt="%H:%M:%S")
        clusterInformation = ClusterInformation()
        clusterInformation.start()

    def getRules(podReq):
        logging.info('Llega pod')