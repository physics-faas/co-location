# Co-location Demonstration - 8thGA - Florence

## Description
This demonstration is intended to show the performance benefit of using co-location versus not using it. It has been deployed on a K8S Openwhisk cluster with two invoker nodes. First we deployed the modeltraining and videoprocessing functions available in the FunctionBench benchmark and observed where the K8S scheduler decided to deploy the pods and the execution time of each of the functions. Next, the K8S cluster was configured to intercept the pods before they are deployed to generate affinity and anti-affinity rules to ensure that the pods are deployed with a configuration that improves the performance of the functions. It then checks on which nodes the pods have been deployed, which rules have been generated and how long the functions have been running.

## Default K8S deployment

1. Run modeltraining and video processing functions in parallel
```bash
#In one terminal
wsk -i action invoke modeltraining -p dataset_bucket input -p model_bucket output -p endpoint_url http://10.109.53.128:9000 -p aws_access_key_id root -p aws_secret_access_key rootpass -p dataset_object_key reviews50mb.csv -p model_object_key lr_model1.pk -p metadata prueba --result
#In other terminal
wsk -i action invoke videoprocessing -p input_bucket input -p output_bucket output -p endpoint_url http://10.109.53.128:9000 -p aws_access_key_id root -p aws_secret_access_key rootpass -p object_key big_buck_bunny_720p_30mb.mp4 -p metadata prueba --result
```

2. Check where functions pods have been deployed

```bash
$ kubectl get pods -o wide | grep wskowdev-invoker-00
wskowdev-invoker-00-19-guest-modeltraining           1/1     Running     0               86s     10.150.4.135    blade151   <none>           <none>
wskowdev-invoker-00-20-guest-videoprocessing         1/1     Running     0               66s     10.150.4.136    blade151   <none>           <none>
```
Both functions have been deployed in node blade151

3. Show pod affinity and antiaffinity rules:
```bash
$ kubectl get pod wskowdev-invoker-00-19-guest-modeltraining -o yaml
...
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: openwhisk-role
            operator: In
            values:
            - invoker
...
$ kubectl get pod wskowdev-invoker-00-20-guest-videoprocessing -o yaml
...
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: openwhisk-role
            operator: In
            values:
            - invoker
...
```

4. Get invokations duration - Function (latency)
```bash
$ wsk -i activation list
Datetime            Activation ID                    Kind     Start Duration   Status          Entity
2023-11-06 12:00:12 f613bf06d2324f3093bf06d2324f306e blackbox cold  2m7.366s   success         guest/videoprocessing:0.0.1
2023-11-06 11:59:52 cbf91db81b324feab91db81b32bfea79 blackbox cold  37.688s    success         guest/modeltraining:0.0.1
```

The modeltraining function has a latency of 37.688 seconds and the videoprocessing function has a latency of 127.366 seconds.

## Co-location 

1. Configure the namespace with the label expected by the webhook

```bash
$ kubectl label namespace default physics-webhook=enabled
namespace/default labeled
```

2. Run modeltraining and video processing functions in parallel
```bash
#In one terminal
wsk -i action invoke modeltraining -p dataset_bucket input -p model_bucket output -p endpoint_url http://10.109.53.128:9000 -p aws_access_key_id root -p aws_secret_access_key rootpass -p dataset_object_key reviews50mb.csv -p model_object_key lr_model1.pk -p metadata prueba --result
#In other terminal
wsk -i action invoke videoprocessing -p input_bucket input -p output_bucket output -p endpoint_url http://10.109.53.128:9000 -p aws_access_key_id root -p aws_secret_access_key rootpass -p object_key big_buck_bunny_720p_30mb.mp4 -p metadata prueba --result
```

3. Check where functions pods have been deployed

```bash
$ kubectl get pods -o wide | grep wskowdev-invoker-00
wskowdev-invoker-00-21-guest-modeltraining           1/1     Running     0               49s     10.150.4.137    blade151   <none>           <none>
wskowdev-invoker-00-22-guest-videoprocessing         1/1     Running     0               36s     10.150.5.65     blade152   <none>           <none>
```
One function has been deployed in blade151 and the other in blade152.

4. Show pod affinity and antiaffinity rules:
```bash
...
$ kubectl get pod wskowdev-invoker-00-21-guest-modeltraining -o yaml
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: openwhisk-role
            operator: In
            values:
            - invoker
          - key: kubernetes.io/hostname
            operator: In
            values:
            - blade151
            - blade152
...
$ kubectl get pod wskowdev-invoker-00-22-guest-videoprocessing -o yaml
...
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: openwhisk-role
            operator: In
            values:
            - invoker
          - key: kubernetes.io/hostname
            operator: In
            values:
            - blade151
            - blade152
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchExpressions:
          - key: openwhisk/action
            operator: In
            values:
            - modeltraining
        topologyKey: kubernetes.io/hostname
...

```

5. Obtaine invokations duration
```bash
$ wsk -i activation list
Datetime            Activation ID                    Kind     Start Duration   Status          Entity
2023-11-06 12:15:46 d54edc54e57d4a4f8edc54e57d9a4f69 blackbox cold  1m40.691s  success         guest/videoprocessing:0.0.2
2023-11-06 12:15:33 383430c145e949a0b430c145e9e9a0fd blackbox cold  37.292s    success         guest/modeltraining:0.0.2
```

The modeltraining function has a latency of 37.292 seconds and the videoprocessing function has a latency of 100.691 seconds.

6. co-location execution time for both function invocations:

```bash
$ kubectl logs physics-admission-controller-cvxx4 | grep 'getRules.*Execution time'
12:15:31 [server.py:71 -             getRules()]: Execution time: 0.344 seconds
12:15:44 [server.py:71 -             getRules()]: Execution time: 0.369 seconds
```

# Conclusion

The co-location component produces node affinity and pod anti-affinity rules to help the K8S scheduler find the best pod deployment location to ensure lower function latency. In this example, by invoking the FunctionBench Benchmark functions modeltraining and videoprocessing with co-location disabled, both functions have been deployed on the same machine blade151. The execution latency of these functions was 37.688 and 127.366 seconds respectively. With co-location enabled, the functions have been deployed on two different machines, blade151 and blade152. The execution latency of these functions was 37.292 and 100.691 seconds respectively, 1.05% and 20.94% lower respectively.  The co-location execution time was around 0.35 seconds for each function.