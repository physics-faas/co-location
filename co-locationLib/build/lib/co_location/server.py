import logging
from .metricsCollectors._clusterInformation import ClusterInformation
from .metricsCollectors._clusterStatus import ClusterStatus
from .metricsCollectors._functionsMetricsInterferences import FunctionsMetricsInterferences
from .kubernetes._workflow import Workflow
from .internals._functions import CollocationFunctions
import configparser
import yaml
import time
import json

class Server:
    def __init__(self, inClusterExecution:bool=True):
        self.cfg = configparser.ConfigParser()
        self.cfg.read('cfg.ini')
        logging.basicConfig(format=self.cfg['LOGGING']['format'], level=logging.INFO, datefmt="%H:%M:%S")
        self.clusterInformation = ClusterInformation(self.cfg, inClusterExecution)
        self.clusterInformation.start()
        self.clusterStatus =  ClusterStatus(self.cfg, inClusterExecution)
        self.functionsMetricsInterferences= FunctionsMetricsInterferences(self.cfg, inClusterExecution)
        self.functionsMetricsInterferences.start()
        self.functions = CollocationFunctions(self.cfg, inClusterExecution)
        self.inClusterExecution = inClusterExecution

    def getRules(self, podYml: yaml, workflowName: str) -> yaml:
        startTime=time.time()
        actionName = self.functions.getActionName(podYml)
       
        logging.info('Action name: '+actionName+' workflow name: '+workflowName)
        workflow = Workflow(group=self.cfg['WORKFLOW']['group'], namespace=self.cfg['WORKFLOW']['namespace'], workflowName=workflowName, actionName=actionName, inClusterExecution=self.inClusterExecution) #Remove hello and set function name
        if not workflow.existsWorkflow():
            logging.warning('No workflow available, nothing to do')
            return podYml

        extraResources =  workflow.getExtraResources()
        podLimitsAndRequests =  workflow.getPodLimitsAndRequests()
        profiling = workflow.getPerformanceProfile()

        nodeAffinityRules={}
        podAntiAffinityRules={}

        clusterNodes = self.clusterInformation.getClusterNodes()
        candidateNodes = self.functions.filterCandidateNodesInvokers(clusterNodes)
        candidateNodes = self.functions.filterCandidateNodesExtraResources(candidateNodes, extraResources)
        candidateNodes =  self.functions.filterNodesWithEnoughResources(podLimitsAndRequests, candidateNodes, self.clusterStatus.nodeStatus())
        nodeAffinityRules = self.functions.generateNodeAffinityRules(candidateNodes)
        logging.info('Node affinity rules: '+str(nodeAffinityRules))

        actionName, functionMetrics = self.functionsMetricsInterferences.getFunctionMetrics(actionName)
        logging.info(actionName)
        functionInterferences = self.functionsMetricsInterferences.getFunctionInterferences(actionName)
        functionsRunning = self.functions.getFunctionsRunningInCandidateNodes(candidateNodes)

        #nodeAffinityRules={}
        affinityAntiAffinityRulesBasedOnInterferences={}

        if functionMetrics is not None:
            podResourcesUsage = self.functions.getPodResourcesUsage(podLimitsAndRequests, functionMetrics) 
            #self.functions.updatePodLimitsAndRequests(podYml, podResourcesUsage)
            if functionsRunning is None:
                logging.info('No functions running on candidate nodes')
                candidateNodes = self.functions.filterNodesWithEnoughResources(podResourcesUsage, candidateNodes, self.clusterStatus.nodeStatus())
                nodeAffinityRules = self.functions.generateNodeAffinityRules(candidateNodes)
                logging.info(nodeAffinityRules)
            else:
                logging.info('There are functions running on candidate nodes')
                affinityAntiAffinityRulesBasedOnInterferences = self.functions.generateRulesBasedOnInterferences(actionName, functionInterferences, functionsRunning)
                logging.info('Function interferences: '+str(affinityAntiAffinityRulesBasedOnInterferences))
                #podAntiAffinityRules = self.functions.generatePodAntiAffinityRules(functionsInterferenceName)
                #logging.info('Pod anti-affinity rules: '+str(podAntiAffinityRules))
        else:
            logging.info('No function metrics')
            logging.info(candidateNodes)
            candidateNodes = self.functions.filterNodesWithEnoughResourcesProfiling(profiling, candidateNodes, self.clusterStatus.nodeStatus())
            nodeAffinityRules = self.functions.generateNodeAffinityRules(candidateNodes)
        
        self.functions.addAffinityAndAntiAffinityRules(podYml, nodeAffinityRules, affinityAntiAffinityRulesBasedOnInterferences)
        logging.info('Execution time: '+str(round(time.time()-startTime,3))+' seconds')
        #logging.info(podYml)
        return podYml   
    
    def getMetrics(self):
        return {'cluster_node': self.clusterInformation.getClusterNodes(),
              'cluster_status': self.clusterStatus.nodeStatus(),
              'functions_metrics': self.functionsMetricsInterferences.getFunctionsMetrics(),
              'functions_interferences': self.functionsMetricsInterferences.getFunctionsInterferences()}
    
    def setInitialMetrics(self, metrics: json):
        self.functionsMetricsInterferences.setFunctionsMetricsAndInterferences(metrics)

    def cleanMetrics(self):
        self.functionsMetricsInterferences.cleanFunctionsMetricsAndInterferences()

        