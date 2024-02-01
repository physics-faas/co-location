logginig={
    'format': "%(asctime)s [%(filename)s:%(lineno)s - %(funcName)20s()]: %(message)s"
}

intervals={
    'cluster_info': 3600, 
    'functions_metrics':3600
}

interferences={
    'increment_threshold': 10
}

prometheus={
    'namespace': 'default',
    'token_name': 'prometheus-server-token',
    'svc_name': 'prometheus-server'
}