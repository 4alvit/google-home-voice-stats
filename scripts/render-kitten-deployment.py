#!/usr/bin/env python3
"""Render two private, node-pinned Nano services without embedding credentials."""
import argparse
import ipaddress
import json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--namespace', default='igw-speech')
for role in ('primary', 'secondary'):
    parser.add_argument('--' + role + '-node', required=True)
    parser.add_argument('--' + role + '-address', required=True)
    parser.add_argument('--' + role + '-image', required=True)
args = parser.parse_args()
items = [{'apiVersion':'v1','kind':'Namespace','metadata':{'name':args.namespace}}]
probe = ['python','-c',"import os,urllib.request; urllib.request.urlopen('http://'+os.environ['KITTEN_BIND_HOST']+':8092/healthz',timeout=2).close()"]
for role in ('primary','secondary'):
    address = getattr(args, role + '_address')
    ip = ipaddress.ip_address(address)
    if not ip.is_private or ip.is_loopback or ip.is_unspecified or ip.version != 4:
        parser.error('Use a private IPv4 address assigned to each node')
    image = getattr(args, role + '_image')
    if '@sha256:' not in image:
        parser.error('Images must be pinned by digest')
    name = 'kitten-' + role
    labels = {'app.kubernetes.io/name':'igw-kitten','app.kubernetes.io/instance':name}
    container = {
        'name':'speech','image':image,'imagePullPolicy':'IfNotPresent',
        'env':[{'name':'KITTEN_BIND_HOST','value':address},
               {'name':'KITTEN_TOKEN_FILE','value':'/run/speech/token'}],
        'resources':{'requests':{'cpu':'100m','memory':'256Mi'},'limits':{'cpu':'1','memory':'768Mi'}},
        'securityContext':{'allowPrivilegeEscalation':False,'readOnlyRootFilesystem':True,'capabilities':{'drop':['ALL']}},
        'volumeMounts':[{'name':'token','mountPath':'/run/speech','readOnly':True}, {'name':'tmp','mountPath':'/tmp'}],
        'startupProbe':{'exec':{'command':probe},'periodSeconds':5,'failureThreshold':30,'timeoutSeconds':3},
        'readinessProbe':{'exec':{'command':probe},'periodSeconds':10,'timeoutSeconds':3},
        'livenessProbe':{'exec':{'command':probe},'periodSeconds':30,'failureThreshold':3,'timeoutSeconds':3},
    }
    items.append({'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':name,'namespace':args.namespace},
      'spec':{'replicas':1,'strategy':{'type':'Recreate'},'selector':{'matchLabels':labels},
        'template':{'metadata':{'labels':labels},'spec':{
          'nodeSelector':{'kubernetes.io/hostname':getattr(args,role+'_node')},
          'hostNetwork':True,'dnsPolicy':'ClusterFirstWithHostNet','automountServiceAccountToken':False,
          'securityContext':{'runAsNonRoot':True,'runAsUser':10001,'runAsGroup':10001,'fsGroup':10001,'seccompProfile':{'type':'RuntimeDefault'}},
          'containers':[container],
          'volumes':[{'name':'token','secret':{'secretName':'igw-kitten-token','defaultMode':288}},
                     {'name':'tmp','emptyDir':{'medium':'Memory','sizeLimit':'64Mi'}}]}}}})
print(json.dumps({'apiVersion':'v1','kind':'List','items':items}, indent=2))
