import logging
from kubernetes import client, config
import yaml
from datetime import datetime, timezone

class CollocationFunctions:

    def __init__(self, cfg, inClusterExecution:bool=True):
        if inClusterExecution:
            config.load_incluster_config()
        else:
            config.load_kube_config()
        self.v1=client.CoreV1Api()
        self.cfg=cfg

    def getActionName(self, podYml: yaml) -> str:
        if 'aws' in self.cfg['DEPLOYMENT']['location']:
            actionName=""
            i=0
            for substring in (podYml['metadata']['labels']['name']).split('-'):
                if i>4:
                    actionName+='-'+substring
                i+=1
            actionName=actionName[1:]
            return actionName
        return (podYml['metadata']['labels']['name']).split('-')[5]
        
    
    def filterCandidateNodesInvokers(self, nodes:dict) -> dict:
        candidateNodes={}
        for node in nodes:
            if 'openwhisk-role' in nodes[node]:
                candidateNodes[node]=nodes[node]
        return candidateNodes
    
    def filterCandidateNodesExtraResources(self, nodes:dict, extraResources:dict) -> dict:
        candidateNodes={}
        if extraResources is not None:
            for node in nodes:
                numExtraResources=0
                for resource in extraResources:
                    if resource in nodes[node]:
                        numExtraResources+=1
                if  len(extraResources) == numExtraResources:       
                    candidateNodes[node]=nodes[node]
        if len(candidateNodes)==0:
            return nodes
        return candidateNodes
    
    def filterNodesWithEnoughResources(self, podLimitsAndRequests:dict, nodes:dict, nodesStatus:dict) -> dict:
        candidateNodes={}
        numRequestsSatisfied = 0
        if podLimitsAndRequests is not None:
            for node in nodes:
                logging.info
                logging.info(nodes[node])
                logging.info(nodesStatus[node])
                logging.info(podLimitsAndRequests['requests'])
                if nodes[node]['CPU']-nodesStatus[node]['CPUm']>=podLimitsAndRequests['requests']['cpu']*1000:
                    numRequestsSatisfied+=1
                if nodes[node]['Mem']-nodesStatus[node]['MemoryMB']>=podLimitsAndRequests['requests']['memory']:
                    numRequestsSatisfied+=1
                if numRequestsSatisfied==len(podLimitsAndRequests['requests']):
                    candidateNodes[node]=nodes[node]
                    numRequestsSatisfied = 0

        if len(candidateNodes)==0:
            return None
        return candidateNodes
    
    def generateNodeAffinityRules(self, nodes: dict) -> dict:
        rules={'nodeSelectorTerms': [{'matchExpressions': [{'key': 'openwhisk-role', 'operator': 'In', 'values': ['invoker']}]}]}
        nodeAff=[]
        if nodes is not None:
            for node in nodes:
                if 'openwhisk-role' in nodes[node]:
                    nodeAff.append(node)
        if len(nodeAff)>0:
            rules['nodeSelectorTerms'][0]['matchExpressions'].append({'key':'kubernetes.io/hostname', 'operator': 'In', 'values':nodeAff })
        return rules
    
    def getFunctionsRunningInCandidateNodes(self, nodes: dict) -> dict:
        pods=self.v1.list_namespaced_pod(namespace=self.cfg['OW']['namespace'], label_selector='release=owdev')
        actionsPerNode={}
        if nodes is None:
            return actionsPerNode
        
        for node in nodes:
            actionsPerNode[node]={}

        for pod in pods.items:
            if 'invoker' in pod.metadata.labels and 'openwhisk/action' in pod.metadata.labels:
                #print(pod.metadata.creation_timestamp)
                time=datetime.now(timezone.utc)-pod.metadata.creation_timestamp
                #print(time.seconds)
                #print(pod.metadata.labels)
                #print(pod.spec.node_name)
                #print(nodes)
                if pod.spec.node_name in nodes.keys():
                    if pod.metadata.labels['openwhisk/action'] not in actionsPerNode[pod.spec.node_name]:
                        actionsPerNode[pod.spec.node_name][pod.metadata.labels['openwhisk/action']]={}
                    actionsPerNode[pod.spec.node_name][pod.metadata.labels['openwhisk/action']][pod.metadata.labels['name']]=time.seconds
        logging.info('Functions running in candidate nodes: '+str(actionsPerNode))
        return actionsPerNode
    
    def getPodResourcesUsage(self, podLimitsAndRequests: dict, functionMetrics:dict) -> dict:
        logging.info(functionMetrics)
        cpu=functionMetrics['numVCores']
        if functionMetrics['numVCores']<podLimitsAndRequests['requests']['cpu']:
            cpu=podLimitsAndRequests['requests']['cpu']
        mem = podLimitsAndRequests['requests']['memory']
        if functionMetrics['mem(MiB)']>podLimitsAndRequests['requests']['memory']:
            if 128<functionMetrics['mem(MiB)']<512:
                mem = 512
            elif 512<functionMetrics['mem(MiB)']<1024:
                mem = 1024
            elif 1024<functionMetrics['mem(MiB)']<1536:
                mem = 1536
            else:
                mem = 2048
        
        limitmemory=podLimitsAndRequests['limits']['memory']
        if podLimitsAndRequests['limits']['memory']<mem:
            limitmemory = mem
        return {'limits':{'memory': limitmemory}, 'requests': {'cpu': cpu, 'memory': mem}}
    
    def updatePodLimitsAndRequests(self, podYml:yaml, podResourcesUsage:dict):
        for type in podResourcesUsage:
            if 'memory' in podResourcesUsage[type]:
                podResourcesUsage[type]['memory']=str(podResourcesUsage[type]['memory'])+'Mi'
            if 'cpu' in podResourcesUsage[type]:
                podResourcesUsage[type]['cpu']=str(podResourcesUsage[type]['cpu']*1000)+'m'
        podYml['spec']['containers'][0]['resources'].update(podResourcesUsage)

    
    
    #functionsRunning tiene el pod y el tiempo que lleva corriendo? comprobar
    def generateRulesBasedOnInterferences(self, functionName:str, functionsInterferences:list, functionsRunning:dict):
        interferencesPerNode=self.getInterferencePodsPerCandidateNode(functionName, functionsInterferences, functionsRunning)
        if not self.interferencesInAllCandidateNodes(interferencesPerNode):
            return self.generatePodAntiAffinityRules(self.getInterferenceActionNames(interferencesPerNode), True)
        return self.generatePodAntiAffinityRules(self.getInterferencePods(interferencesPerNode), False)

    #functionsRunning si el nodo no tiene funciones sale en el dictionario? Comprobar
    def getInterferencePodsPerCandidateNode(self, functionName:str, functionsInterferences:list, functionsRunning:dict) -> dict:
        interferences={}
        for node in functionsRunning:
            interferences[node]={}
            for function in functionsRunning[node]:
                for functionsPair in functionsInterferences:
                    if function in functionsPair and functionName in functionsPair:
                        if functionsInterferences[functionsPair][functionName]['increment%']>=float(self.cfg['INTERFERENCES']['increment_threshold']):
                            interferences[node][function]=[functionsInterferences[functionsPair][functionName]['increment%'], functionsRunning[node][function]]
                        elif functionsInterferences[functionsPair][function]['increment%']>=float(self.cfg['INTERFERENCES']['increment_threshold']):
                            interferences[node][function]=[functionsInterferences[functionsPair][function]['increment%'], functionsRunning[node][function]]
        logging.info(interferences)
        return interferences

    def interferencesInAllCandidateNodes(self, interferences: dict) -> bool:
        numNodesInterferences=0
        for node in interferences:
            if interferences[node]:
                numNodesInterferences+=1
        if numNodesInterferences==len(interferences):
            return True
        return False
    
    def getInterferenceActionNames(self, interferencesPerNode: dict) -> list:
        interferences=[]
        for node in interferencesPerNode:
            for function in interferencesPerNode[node]:
                interferences.append(function)
        return interferences
    
    def generatePodAntiAffinityRules(self, functionsInterferenceName:list, actionNames: bool) -> dict:
        rules={}
        if len(functionsInterferenceName)>0:
            if actionNames:
                rules=  {'requiredDuringSchedulingIgnoredDuringExecution':[{ 'labelSelector': {'matchExpressions': [{'key':'openwhisk/action', 'operator': 'In', 'values': functionsInterferenceName}]},'topologyKey': 'kubernetes.io/hostname'}]}
            else:
                rules=  {'requiredDuringSchedulingIgnoredDuringExecution':[{ 'labelSelector': {'matchExpressions': [{'key':'name', 'operator': 'In', 'values': functionsInterferenceName}]},'topologyKey': 'kubernetes.io/hostname'}]}
        return rules
    
    def getInterferencePods(self, interferencesPerNode: dict):
        functions={}
        for node in interferencesPerNode:
            for function in interferencesPerNode[node]:
                if function not in functions:
                    functions[function]=[interferencesPerNode[node][function][0], [node]]
                else:
                    functions[function][1].append(node)

        logging.info(functions)
        functionsInAllNodes=[]
        for function in functions:
            if len(functions[function][1])==len(interferencesPerNode):
                functionsInAllNodes.append(function)
        logging.info(functionsInAllNodes)

        mostImpactFunction=[]
        for function in functions:
            if len(mostImpactFunction)==0:
                mostImpactFunction=[function, functions[function][0]]
            elif mostImpactFunction[1]<functions[function][0]:
                mostImpactFunction=[function, functions[function][0]]
        logging.info(mostImpactFunction)

        if len(functionsInAllNodes) == len(functions):
            pod=""
            podsLifetime={}
            for node in interferencesPerNode:
                for function in interferencesPerNode[node]:
                    if function == mostImpactFunction[0]:
                        for pod in interferencesPerNode[node][function][1]:
                            if function not in podsLifetime:
                                podsLifetime=[pod, interferencesPerNode[node][function][1][pod], node]
                            elif podsLifetime[function][1] < interferencesPerNode[node][function][1][pod]:
                                podsLifetime=[pod, interferencesPerNode[node][function][1][pod], node]
            pod=podsLifetime[0]
            logging.info(podsLifetime)
            logging.info(mostImpactFunction)

        else:
            logging.info(functions[mostImpactFunction[0]])
            node=functions[mostImpactFunction[0]][1][0]
            podsLifetime={}
            logging.info(interferencesPerNode[node])
            logging.info(interferencesPerNode[node][mostImpactFunction[0]])
            for pod in interferencesPerNode[node][mostImpactFunction[0]][1]:
                if function not in podsLifetime:
                    podsLifetime=[pod, interferencesPerNode[node][mostImpactFunction[0]][1][pod]]
                elif podsLifetime[function][1] < interferencesPerNode[node][mostImpactFunction[0]][1][pod]:
                    podsLifetime=[pod, interferencesPerNode[node][mostImpactFunction[0]][1][pod]]
            pod=podsLifetime[0]

        logging.info(pod)
        return [pod]
        
    def filterNodesWithEnoughResourcesProfiling(self, profiling: dict, nodes: dict, nodesStatus: dict) -> dict:
        candidateNodes={}
        if profiling is not None:
            logging.info(profiling)
            for node in nodes:
                numFilters=0
                for resource in profiling:
                    if 'cpu' in resource:
                        if self._checkResourceProfile(nodesStatus[node], 'CPU%', profiling[resource]):
                            numFilters+=1
                    if 'memory' in resource:
                        if self._checkResourceProfile(nodesStatus[node], 'Memory%', profiling[resource]):
                            numFilters+=1
                if len(profiling)==numFilters:
                    candidateNodes[node]=nodes[node]
        else:
            return nodes
        if len(candidateNodes)==0:
            return None
        return candidateNodes

    def _checkResourceProfile(self, node:dict, resource:str, resourceProfiling:str) -> bool:
        if (resourceProfiling == 'high' and node[resource]<=(100-float(self.cfg['PROFILING']['highResourceAvblPct']))):
            return True
        elif (resourceProfiling == 'medium' and node[resource]<=(100-float(self.cfg['PROFILING']['mediumResourceAvblPct']))):
            return True
        elif (resourceProfiling == 'low'  and node[resource]<=(100-float(self.cfg['PROFILING']['lowResourceAvblPct']))):
            return True
        return False

    def addAffinityAndAntiAffinityRules(self, podYml:yaml, nodeAffinityRules:dict, podAntiAffinityRules:dict):
        if len(nodeAffinityRules)>0:
            podYml['spec']['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution'].update(nodeAffinityRules)     
            logging.info('Adding node affinity')
        if len(podAntiAffinityRules)>0:
            logging.info('Adding pod anti affinity')
            podYml['spec']['affinity']['podAntiAffinity'] = podAntiAffinityRules