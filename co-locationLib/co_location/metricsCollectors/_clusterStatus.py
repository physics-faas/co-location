import os
import logging
import base64
import json
import re
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException
from kubernetes.client.api_client import ApiClient
from prometheus_api_client import PrometheusConnect

class ClusterStatus:
    def __init__(self, cfg, inClusterExecution=True):
        if inClusterExecution:
            config.load_incluster_config()
        else:
            config.load_kube_config()
        self.v1=client.CoreV1Api()
        self.api_client = ApiClient()
    
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

        headers = {"Authorization": "bearer "+token}
        self.prometheus_connection = PrometheusConnect(url = prometheus_svc, headers=headers, disable_ssl=True)

    def _getMetric(self, query):
        result=self.prometheus_connection.custom_query(query=query)
        metrics={}
        for metric in result:
            if 'device' in metric['metric']:
                metrics[metric['metric']['device']]=float(metric['value'][1])
            else:
                return float(metric['value'][1])
        return metrics
            

    def _cpu(self, value):
        """
        Return CPU in milicores if it is configured with value
        """
        if re.match(r"[0-9]{1,9}m", str(value)):
            cpu = re.sub("[^0-9]", "", value)
        elif re.match(r"[0-9]{1,4}$", str(value)):
            cpu = int(value) * 1000
        elif re.match(r"[0-9]{1,15}n", str(value)):
            cpu = int(re.sub("[^0-9]", "", value)) // 1000000
        elif re.match(r"[0-9]{1,15}u", str(value)):
            cpu = int(re.sub("[^0-9]", "", value)) // 1000
        return int(cpu)

    def _memory(self, value):
        """
        Return Memory in MB
        """
        if re.match(r"[0-9]{1,9}Mi?", str(value)):
            mem = re.sub("[^0-9]", "", value)
        elif re.match(r"[0-9]{1,9}Ki?", str(value)):
            mem = re.sub("[^0-9]", "", value)
            mem = int(mem) // 1024
        elif re.match(r"[0-9]{1,9}Gi?", str(value)):
            mem = re.sub("[^0-9]", "", value)
            mem = int(mem) * 1024
        return int(mem)

    def nodeStatus(self):   
        logging.info('Start collecting node status metrics')
        nodesMetrics = {}
        nodes=self.v1.list_node(label_selector= 'node-role.kubernetes.io/worker')
        #nodes=v1.list_cluster_custom_object('metrics.k8s.io', 'v1beta1', 'nodes')

        for node in nodes.items:
            for status in node.status.conditions:
                if status.status == 'True' and status.type == 'Ready':
                    #Nodes cpu and memory usage
                    node_metrics = "/apis/metrics.k8s.io/v1beta1/nodes/" + node.metadata.name
                    response = self.api_client.call_api(node_metrics,
                                                'GET', auth_settings=['BearerToken'],
                                                response_type='json', _preload_content=False)
                    response = json.loads(response[0].data.decode('utf-8'))
                    used = response.get("usage")
                    values = {}
                    values["memory"] = self._memory(used.get("memory"))
                    values["cpu"] = self._cpu(used.get("cpu"))
                    usage = values

                    #Nodes available cpu and memory
                    allocation = node.status.allocatable
                    values = {}
                    values["memory"] = self._memory(allocation.get("memory"))
                    values["cpu"] = self._cpu(allocation.get("cpu"))
                    allocatable = values

                    metrics={}
                    #CPU metric
                    #metrics['CPU']=self._getMetric("sum (rate (container_cpu_usage_seconds_total{id='/',kubernetes_io_hostname='"+node.metadata.name+"'}[5m])) / sum (machine_cpu_cores{kubernetes_io_hostname='"+node.metadata.name+"'}) * 100")
                    metrics['CPU%']=(usage['cpu']/allocatable['cpu']) * 100
                    metrics['CPUm']=usage['cpu']
                    #Mem metric
                    #metrics['Memory']=self._getMetric("sum (container_memory_working_set_bytes{id='/',kubernetes_io_hostname='"+node.metadata.name+"'}) / sum (machine_memory_bytes{kubernetes_io_hostname='"+node.metadata.name+"'}) * 100")
                    metrics['Memory%']=(usage['memory']/allocatable['memory']) * 100
                    metrics['MemoryMB']=usage['memory']
                    #Network metrics
                    network={}
                    network['receive']=self._getMetric("rate(node_network_receive_bytes_total{node='"+node.metadata.name+"'}[5m])*8/1048576")
                    network['transmited']=self._getMetric("rate(node_network_transmit_bytes_total{node='"+node.metadata.name+"'}[60s])*8/1048576")
                    metrics['network']=network
                    #Disk metrics
                    diskIO={}
                    diskIO['read']=self._getMetric("rate(node_disk_read_bytes_total{node='"+node.metadata.name+"'}[5m])")
                    diskIO['write']=self._getMetric("rate(node_disk_written_bytes_total{node='"+node.metadata.name+"'}[5m])")
                    metrics['diskIO']=diskIO
                    nodesMetrics[node.metadata.name]=metrics
        return nodesMetrics
        
     