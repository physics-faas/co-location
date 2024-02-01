import logging
import threading
import time
from kubernetes import client, config

clusterNodes={}

def startCollector(self):   
    while True:
        logging.info('Cluster Information collector') 
        nodeDict={}
        nodes=self.v1.list_node(label_selector= 'node-role.kubernetes.io/worker')
        for node in nodes.items:
            for status in node.status.conditions:
                if status.status == 'True' and status.type == 'Ready':
                    specs={"CPU":node.status.allocatable['cpu'], "Mem":float(node.status.allocatable['memory'].split('K')[0])*0.000976562}
                    if 'network' in node.metadata.labels:
                        specs["Network"]=node.metadata.labels['network']
                    if 'diskType' in node.metadata.labels:
                        specs["diskType"]=node.metadata.labels['diskType']
                    if 'gpu'  in node.metadata.labels:
                        specs["gpu"]=node.metadata.labels['gpu']
                    if "m" in specs['CPU']: #mCores
                        specs['CPU']=float(specs['CPU'].split('m')[0])
                    else:  #Cores to mCores
                        specs['CPU']=float(specs['CPU'])*1000            
                    nodeDict[node.metadata.name]=specs
                    if ('openwhisk-role', 'invoker') in node.metadata.labels.items():
                        nodeDict[node.metadata.name].update({"openwhisk-role" : "invoker"}) 
            
        self._clusterNodes=nodeDict
        time.sleep(int(self.cfg['INTERVALS']['cluster_info']))

class ClusterInformation:
    def __init__(self, cfg, inClusterExecution=True):
        self.cfg=cfg
        self.thread = None
        self._clusterNodes = {}
        if inClusterExecution:
            config.load_incluster_config()
        else:
            config.load_kube_config()
        self.v1=client.CoreV1Api()

    def start(self):
        if self.thread:
            raise Exception('Collection already running')
        
        try:
            self.thread = threading.Thread(target=startCollector, args=(self, ))
            self.thread.start()
        except:
            raise Exception('Error starting cluster information thread.')
    
    def getClusterNodes(self) -> dict:
        return self._clusterNodes
    