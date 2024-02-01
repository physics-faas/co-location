import os
import logging
import base64
import time
import threading
from kubernetes import client, config
from prometheus_api_client import PrometheusConnect
from prometheus_client import start_http_server, Gauge
import requests
import json
from datetime import datetime

def collector(self):
    while True:
        logging.info('Functions metrics collector') 
        self._checkFunctionsInterferences()        
        self._exportMetrics()
        logging.info(self.getFunctionsMetrics())                                            
        time.sleep(int(self.cfg['INTERVALS']['functions_metrics']))

def interferences(self, node: str, activations: dict):
    logging.info('thread for node: '+node)
    logging.info(self.co_located_metrics)
    standalone={}
    coLocated={}
    for podActivations1 in activations:
        logging.info("+++++++++"+podActivations1+"+++++++++")
        for activation1Id in range(0,len(activations[podActivations1]['activations'])):
            aloneExecution=0
            coLocatedExecution=0
            numCompared=0
            logging.debug("Activation to compare: "+str(activations[podActivations1]['activations'][activation1Id]))
            for podActivations2 in activations:
                if podActivations1 not in podActivations2:
                    for activation2Id in range(0,len(activations[podActivations2]['activations'])):
                        logging.debug(str(activations[podActivations2]['activations'][activation2Id]))
                        if activations[podActivations1]['activations'][activation1Id]['end']<=activations[podActivations2]['activations'][activation2Id]['start'] or activations[podActivations2]['activations'][activation2Id]['end']<=activations[podActivations1]['activations'][activation1Id]['start']:
                            aloneExecution+=1
                        else:
                            coLocatedExecution+=1
                        numCompared+=1
                        logging.info("--------")

            logging.info('Action '+activations[podActivations1]['activations'][activation1Id]['activationId']+' num compared: '+str(numCompared)+' alone: '+str(aloneExecution)+' co-located: '+str(coLocatedExecution))
            if numCompared==0 or coLocatedExecution==0 and aloneExecution>0:
                if activations[podActivations1]['activations'][activation1Id]['action'] not in standalone:
                    standalone[activations[podActivations1]['activations'][activation1Id]['action']]=[]
                standalone[activations[podActivations1]['activations'][activation1Id]['action']].append(activations[podActivations1]['activations'][activation1Id])
            elif podActivations1 not in podActivations2:
                id1=activations[podActivations1]['activations'][activation1Id]['action']+'+'+activations[podActivations2]['activations'][activation2Id]['action']
                id2=activations[podActivations2]['activations'][activation2Id]['action']+'+'+activations[podActivations1]['activations'][activation1Id]['action']

                if id1 not in coLocated and id2 not in coLocated:
                    coLocated[id1]=[]
                coLocated[id1].append({activations[podActivations1]['activations'][activation1Id]['action']:activations[podActivations1]['activations'][activation1Id],
                                        activations[podActivations2]['activations'][activation2Id]['action']: activations[podActivations2]['activations'][activation2Id]})
    
    for action in standalone:
        self.standalone_metrics[action]=self._calculateAvg(standalone[action])
        
    for actions in coLocated:   
        actionsSplit=actions.split('+')
        metrics1=[]
        metrics2=[]
        for executionMetrics in coLocated[actions]:
            metrics1.append(executionMetrics[actionsSplit[0]])
            metrics2.append(executionMetrics[actionsSplit[1]])
        avgAction1=self._calculateAvg(metrics1)
        avgAction1['increment%']=0
        if actionsSplit[0] in self.standalone_metrics:
            avgAction1['increment%']=((avgAction1['latency']-self.standalone_metrics[actionsSplit[0]]['latency'])/avgAction1['latency'])*100
        avgAction2=self._calculateAvg(metrics2)
        avgAction2['increment%']=0
        if actionsSplit[1] in self.standalone_metrics:
            avgAction2['increment%']=((avgAction2['latency']-self.standalone_metrics[actionsSplit[1]]['latency'])/avgAction2['latency'])*100
        
        self.co_located_metrics[actions]={actionsSplit[0]:avgAction1, 
                                            actionsSplit[1]:avgAction2}
    logging.info(self.co_located_metrics)
    logging.info(self.interferences)
    self.interferences+=1
    logging.info(self.interferences)
    logging.info('Interferences finished for node '+node)
    
class FunctionsMetricsInterferences:
    def __init__(self, cfg, inClusterExecution:bool=True):
        self.cfg = cfg
        if inClusterExecution:
            config.load_incluster_config()
        else:
            config.load_kube_config()
        self.v1=client.CoreV1Api()

        secrets=self.v1.list_namespaced_secret(namespace=cfg['PROMETHEUS']['namespace'])
        for secret in secrets.items:
            if cfg['PROMETHEUS']['token_name'] in secret.metadata.name:
                token=base64.b64decode(secret.data["token"]).decode("ascii")

        svc=self.v1.read_namespaced_service(namespace=cfg['PROMETHEUS']['namespace'],name=cfg['PROMETHEUS']['svc_name'])
        ip=svc.spec.cluster_ip
        ports=svc.spec.ports
        for port in ports:
            if port.name.__eq__(cfg['PROMETHEUS']['svc_port_name']):
                portn=port.port
        prometheus_svc=cfg['PROMETHEUS']['connection_type']+"://"+ip+":"+str(portn)
        logging.info(prometheus_svc)

        headers = {"Authorization": "bearer "+token}
        self.prometheus_connection = PrometheusConnect(url = prometheus_svc, headers=headers, disable_ssl=True)

        svc=self.v1.read_namespaced_service(namespace=cfg['OW']['namespace'],name=cfg['OW']['svc_name'])
        ip=svc.spec.cluster_ip
        ports=svc.spec.ports
        for port in ports:
            if port.name =="https-api":
                portn=port.port
        self.ow_activations_url = cfg['OW']['connection_type']+"://"+ip+":"+str(portn)+cfg['OW']['activations_path']

        if 'token' in cfg['OW']['auth_form']:
            secrets=self.v1.list_namespaced_secret(namespace=cfg['OW']['namespace'])
            for secret in secrets.items:
                if cfg['OW']['token_name'] in secret.metadata.name:
                    self.ow_token=secret.data["system"]
        elif 'user_password' in cfg['OW']['auth_form']:
            self.ow_activations_url = cfg['OW']['connection_type']+"://"+cfg['OW']['user_password']+"@"+ip+":"+str(portn)+cfg['OW']['activations_path']
            self.ow_token=None

        start_http_server(int(self.cfg['PROMETHEUS']['port_metrics_exporter']))
        self.gStandaloneVCores = Gauge('co_location_function_vcores', 'standalone function vCores', ['name'])
        self.gStandaloneLatency = Gauge('co_location_function_latency', 'standalone function latency', ['name'])
        self.gStandaloneMem = Gauge('co_location_function_mem_mib', 'standalone function memory usage in MiB', ['name'])
        self.gStandaloneNetworkR =Gauge('co_location_function_network_received_bytes', 'standalone function network received in Bytes', ['name'])
        self.gStandaloneNetworkS =Gauge('co_location_function_network_transmited_bytes', 'standalone function network transmited in Bytes', ['name'])
        
        self.gCoLocationIncrement = Gauge('co_location_function_co_located_increment_percentage', 'co_located function latency increment percentage', ['functions_co_located', 'name'])
        self.gCoLocationVCores = Gauge('co_location_function_co_located_vcores', 'co_located  function vCores', ['functions_co_located', 'name'])
        self.gCoLocationLatency = Gauge('co_location_function_co_located_latency', 'co_located  function latency', ['functions_co_located', 'name'])
        self.gCoLocationMem = Gauge('co_location_function_co_located_mem_mib', 'co_located  function memory usage in MiB', ['functions_co_located', 'name'])
        self.gCoLocationNetworkR =Gauge('co_location_function_co_located_network_received_bytes', 'co_located  function network received in Bytes', ['functions_co_located', 'name'])
        self.gCoLocationNetworkS =Gauge('co_location_function_co_located_network_transmited_bytes', 'co_located  function network transmited in Bytes', ['functions_co_located', 'name'])


        self.thread = None
        self.standalone_metrics = {}
        self.co_located_metrics = {}
        self.interferencesPerNode={}

    def start(self):
        if self.thread:
            raise Exception('Collector already running')
        
        try:
            self.thread = threading.Thread(target=collector, args=(self, ))
            self.thread.start()
        except:
            raise Exception('Error starting function metrics and interferences thread.')
    

    def _getPodLogInformation(self, since: int, upto: int) -> dict:
        startTime=time.time()
        activationIdPod={}
        owInvokerPods = self.v1.list_namespaced_pod(namespace=self.cfg['OW']['namespace'], label_selector='name=owdev-invoker')
        for podInfo in owInvokerPods.items:
            pod = podInfo.metadata.name
            logging.info(pod)
            api_response = self.v1.read_namespaced_pod_log(name=pod, namespace=self.cfg['OW']['namespace'])
            logs=[]
            for line in api_response.splitlines():
                if '[KubernetesClient] launching pod' in line or '[ContainerPool] containerStart' in line:
                    ts = datetime.strptime(line.split(' ')[0][1:-1],"%Y-%m-%dT%H:%M:%S.%fZ").timestamp()
                    if since <= ts <= upto:
                        logs.append(line)

            
            lineId=0
            for line in logs:
                logging.debug(line)
                if 'cold' in line:
                    logging.debug("cold")
                    nextLine=logs[lineId+1]
                    if 'launching pod ' in nextLine:
                        activationIdPod[line.split('activationId: ')[1].split(' [')[0]]={'action':line.split('action: ')[1].split(' namespace:')[0], 'pod': nextLine.split('launching pod ')[1].split(' (')[0], 'state': 'cold'}
                elif 'warmingCold' in line:
                    logging.warning('warmingCold function status. This type has to be studied and processed')
                elif 'warm' in line:
                    logging.debug("warm")
                    activationIdPod[line.split('activationId: ')[1].split(' [')[0]]={'action':line.split('action: ')[1].split(' namespace:')[0], 'pod': line.split('ContainerId(')[1].split(')')[0], 'state': 'warm'}
                lineId+=1
            logging.info(activationIdPod)
            logging.info('Execution time: '+str(round(time.time()-startTime,3))+' seconds')
        return activationIdPod
        
    def _getActivationList(self, since:int, activationIdPod:str) -> dict:
        startTime=time.time()
        activations={}
        if len(activationIdPod)>0:
            ow_act_url = self.ow_activations_url + str(since*1000)
            logging.info(ow_act_url)

            payload = {}
            if self.ow_token is None:
                headers = {}
            else:
                headers = {
                'Authorization': 'Basic '+self.ow_token
                }
                logging.debug("OW token: "+self.ow_token)
            response = requests.request("GET", ow_act_url, headers=headers, data=payload, verify=False)
            response = requests.request("GET", ow_act_url, headers=headers, data=payload, verify=False)
            if response.status_code != 200:
                logging.error('Error getting activation list: '+str(response.status_code))
                return activations
            jsonresponse=json.loads(response.text)
            for activation in jsonresponse:
                if activation['activationId'] in activationIdPod:
                    if activationIdPod[activation['activationId']]['pod'] not in activations:
                        activations[activationIdPod[activation['activationId']]['pod']]=[]
                    activations[activationIdPod[activation['activationId']]['pod']].append({'activationId':activation['activationId'], 'action':activation['name'], 'start': activation['start']/1000, 'end': activation['end']/1000,'latency': activation['duration'], 'state': activationIdPod[activation['activationId']]['state']})
        logging.info(activations)
        logging.info('Execution time: '+str(round(time.time()-startTime,3))+' seconds')
        return activations
    
    def _getNodesWhereFunctionsRun(self, activations: dict) -> dict:
        startTime=time.time()
        pods=self.v1.list_namespaced_pod(namespace=self.cfg['OW']['namespace'], label_selector='release=owdev')
        activationsPerNode={}
        for pod in pods.items:
            if 'invoker' in pod.metadata.labels and 'openwhisk/action' in pod.metadata.labels and pod.metadata.name in activations:
                if pod.spec.node_name not in activationsPerNode:
                    activationsPerNode[pod.spec.node_name]={}
                activationsPerNode[pod.spec.node_name][pod.metadata.name]={'action': pod.metadata.labels['openwhisk/action'], 'creation_ts': pod.metadata.creation_timestamp.timestamp(), 'activations': activations[pod.metadata.name]}
        logging.info('Execution time: '+str(round(time.time()-startTime,3))+' seconds')
        return activationsPerNode
    
    def _getActivationMetrics(self, functionsPodsInfo: dict):
        startTime=time.time()
        self._getMetric(functionsPodsInfo, "rate(container_cpu_usage_seconds_total{container=\"user-action\", pod=~\"wskowdev-invoker-.*guest.*\"}[5m])", 'numVCores')
        self._getMetric(functionsPodsInfo, "container_memory_working_set_bytes{pod=~\"wskowdev-invoker-.*guest.*\", container_name!=\"POD\", container=\"user-action\"}[5m]", 'mem(MiB)')
        self._getMetric(functionsPodsInfo, "container_network_receive_bytes_total{pod=~\"wskowdev-invoker-.*guest.*\"}[5m]", 'received (B)')
        self._getMetric(functionsPodsInfo, "container_network_transmit_bytes_total{pod=~\"wskowdev-invoker-.*guest.*\"}[5m]", 'transmited (B)')
        logging.info(functionsPodsInfo)
        logging.info('Execution time: '+str(round(time.time()-startTime,3))+' seconds')
    
    def _getMetric(self, activations:dict, query:str, metricName:str):
        result=self.prometheus_connection.custom_query(query=query)
        for node in activations:
            for pod in activations[node]:
                for metric in result:
                    label='node'
                    if 'upm' in self.cfg['DEPLOYMENT']['location']:
                        label = 'instance'
                    if node == metric['metric'][label] and pod == metric['metric']['pod']:
                        activationId=0
                        for activation in activations[node][pod]['activations']:
                            metricId=0
                            metricStored=False
                            logging.info(metricName)
                            logging.info(metric)

                            if 'values' in metric:
                                while not metricStored and metricId<len(metric['values']):
                                    if metric['values'][metricId][0] >= activation['start']:
                                        value=float(metric['values'][metricId][1])
                                        logging.info(value)
                                        if metricName == 'mem(MiB)':
                                            value=float(value)/1024/1024
                                        elif 'transmited' in metricName or 'received' in metricName:
                                            value=float(value)*8/1024
                                        if value > 0:
                                            activations[node][pod]['activations'][activationId][metricName]=value
                                        metricStored=True
                                    metricId+=1
                            else:
                                value=float(metric['value'][1])
                                logging.info(value)
                                if metricName == 'mem(MiB)':
                                    value=float(value)/1024/1024
                                elif 'transmited' in metricName or 'received' in metricName:
                                    value=float(value)*8/1024
                                if value > 0:
                                    activations[node][pod]['activations'][activationId][metricName]=value
                            
                            activationId+=1

    def _checkFunctionsInterferences(self):
        now=datetime.now()
        since=int(now.timestamp())-300
        upto=int(now.timestamp())
        
        activations=self._getActivationList(since, self._getPodLogInformation(since, upto))
        functionsPodsInfo = self._getNodesWhereFunctionsRun(activations)
        self._getActivationMetrics(functionsPodsInfo)

        self.interferences=0
        for node in functionsPodsInfo:
            try:
                threading.Thread(target=interferences, args=(self, node, functionsPodsInfo[node])).start()
            except:
                raise Exception('Error starting interferences thread.')

        logging.info('Ha llegado aquí 1')
        logging.info(self.interferences)
        logging.info(len(functionsPodsInfo))
        while self.interferences<len(functionsPodsInfo):
            logging.info(self.interferences)
            logging.info(len(functionsPodsInfo))
            logging.info("Waiting to check interferences")
            time.sleep(30)
        logging.info('Ha llegado aquí 2')

    def _calculateAvg(self, actionMetrics:dict) -> dict:
        latency=0
        numVCores=0
        mem=0
        received=0
        transmited=0
        for activationId in range (0,len(actionMetrics)):
            try:
                latency+=actionMetrics[activationId]['latency']
                numVCores+=actionMetrics[activationId]['numVCores']
                mem+=actionMetrics[activationId]['mem(MiB)']
                received+=actionMetrics[activationId]['received (B)']
                transmited+=actionMetrics[activationId]['transmited (B)']
            except:
                logging.info('Some metrics are not yet available')

        return {'latency': round((latency/len(actionMetrics))/1000,2), 'numVCores': round(numVCores/len(actionMetrics),2), 'mem(MiB)':round(mem/len(actionMetrics),2), 'network(B)':{'received': round(received/len(actionMetrics),2), 'transmited': round(transmited/len(actionMetrics),2)}}

    def _exportMetrics(self):
        logging.info('Exporting metrics')
        for function in self.standalone_metrics:
            self.gStandaloneVCores.labels(function).set(float(self.standalone_metrics[function]['numVCores']))
            self.gStandaloneLatency.labels(function).set(float(self.standalone_metrics[function]['latency']))
            self.gStandaloneMem.labels(function).set(float(self.standalone_metrics[function]['mem(MiB)']))
            self.gStandaloneNetworkR.labels(function).set(float(self.standalone_metrics[function]['network(B)']['received']))
            self.gStandaloneNetworkS.labels(function).set(float(self.standalone_metrics[function]['network(B)']['received']))

        for functionPair in self.co_located_metrics:
            for function in self.co_located_metrics[functionPair]:
                self.gCoLocationIncrement.labels(functionPair ,function).set(float(self.co_located_metrics[functionPair][function]['increment%']))
                self.gCoLocationVCores.labels(functionPair ,function).set(float(self.co_located_metrics[functionPair][function]['numVCores']))
                self.gCoLocationLatency.labels(functionPair ,function).set(float(self.co_located_metrics[functionPair][function]['latency']))
                self.gCoLocationMem.labels(functionPair ,function).set(float(self.co_located_metrics[functionPair][function]['mem(MiB)']))
                self.gCoLocationNetworkR.labels(functionPair ,function).set(float(self.co_located_metrics[functionPair][function]['network(B)']['received']))
                self.gCoLocationNetworkS.labels(functionPair ,function).set(float(self.co_located_metrics[functionPair][function]['network(B)']['transmited']))

    def getFunctionMetrics(self, actionName):
        if 'aws' in self.cfg['DEPLOYMENT']['location']:
            actionName=self._findFunctionName(actionName)
        if actionName not in self.standalone_metrics:
            return None
        return actionName, self.standalone_metrics[actionName]
    
    def getFunctionInterferences(self, actionName):
        if 'aws' in self.cfg['DEPLOYMENT']['location']:
            actionName=self._findFunctionName(actionName)
        interferences={}
        for functions in self.co_located_metrics:
            if actionName in functions:
                interferences[functions]=self.co_located_metrics[functions]
        return interferences
    
    def _findFunctionName(self, actionName:str):
        for action in self.standalone_metrics:
            if actionName.replace('-','') in action.lower().replace('-','').replace('_',''):
                return action
        return actionName
    
    def getFunctionsMetrics(self):
        return self.standalone_metrics
    
    def getFunctionsInterferences(self):
        return self.co_located_metrics
    
    def setFunctionsMetricsAndInterferences(self, metrics: json):
        logging.info('Loading metrics in main memory...')
        self.standalone_metrics=metrics['functions_metrics']
        self.co_located_metrics=metrics['functions_interferences']
        logging.info('Metrics loaded')

    def cleanFunctionsMetricsAndInterferences(self):
        logging.info('Cleaning metrics stored in main memory...')
        self.standalone_metrics={}
        self.co_located_metrics={}
        logging.info('Metrics removed')