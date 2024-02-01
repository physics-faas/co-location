from kubernetes import client, config
 
class Workflow:
    def __init__(self, group:str, namespace:str, workflowName:str, actionName:str, inClusterExecution:bool=True):
        if inClusterExecution:
            config.load_incluster_config()
        else:
            config.load_kube_config()
        v1=client.CustomObjectsApi()

        self._workflowName = workflowName
        self._actionName = actionName
        try:
            self._workflow = v1.get_namespaced_custom_object(group=group,version="v1alpha1",namespace=namespace,plural="workflows",name=workflowName)
        except:
            self._workflow=None

    def existsWorkflow(self) -> str:
        return self._workflow is not None
    
    def getExtraResources(self) -> dict:
        for action in self._workflow['spec']['actions']:
            if action['name']==self._actionName:
                if 'extraResources' in action:
                    return action['extraResources']
        return None
    
    def getPodLimitsAndRequests(self) -> dict:
        for action in self._workflow['spec']['actions']:
            if action['name']==self._actionName:
                if 'resources' in action:
                    dict2Send={}
                    for type in action['resources']:
                        dictAux={}
                        for resource in action['resources'][type]:
                            dictAux[resource]=int(action['resources'][type][resource])
                        dict2Send[type]=dictAux
                    return dict2Send
        return None
    
    def getPerformanceProfile(self) -> dict:
        for action in self._workflow['spec']['actions']:
            if action['name']==self._actionName:
                if 'performanceProfile' in action:
                    return action['performanceProfile']
        return None
