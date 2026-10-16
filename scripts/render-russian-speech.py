#!/usr/bin/env python3
"""Render a local Russian HTTPS/HA Wyoming deployment without credentials."""
import argparse
import json
import re

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--namespace', default='igw-speech')
parser.add_argument('--name', default='russian-speech')
parser.add_argument('--node', required=True)
parser.add_argument('--image', required=True)
parser.add_argument('--voice', choices=('piper-ru-denis', 'piper-ru-irina', 'silero-ru-baya'), default='piper-ru-denis')
args = parser.parse_args()
for value in (args.namespace, args.name, args.node):
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,61}[a-z0-9])?', value):
        parser.error('Use Kubernetes DNS names')
if not re.fullmatch(r'[a-z0-9][a-z0-9._:/-]*[a-z0-9]@sha256:[0-9a-f]{64}', args.image):
    parser.error('Use an immutable image digest')
labels = {'app.kubernetes.io/name': args.name}
security = {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True, 'capabilities': {'drop': ['ALL']}}
token = {'name': 'token', 'mountPath': '/run/speech', 'readOnly': True}
env = [{'name': 'KITTEN_TOKEN_FILE', 'value': '/run/speech/token'},
       {'name': 'RUSSIAN_TTS_BACKEND', 'value': 'silero' if args.voice == 'silero-ru-baya' else 'piper'},
       {'name': 'RUSSIAN_SPEECH_VOICE', 'value': args.voice}]
tts = {'name': 'tts', 'image': args.image, 'securityContext': security,
       'env': env + [{'name': 'KITTEN_BIND_HOST', 'value': '0.0.0.0'},
                     {'name': 'KITTEN_PORT', 'value': '8093'},
                     {'name': 'KITTEN_TLS_CERT_FILE', 'value': '/run/tls/tls.crt'},
                     {'name': 'KITTEN_TLS_KEY_FILE', 'value': '/run/tls/tls.key'},
                     {'name': 'KITTEN_THREADS', 'value': '2'}],
       'resources': {'requests': {'cpu': '250m', 'memory': '256Mi'}, 'limits': {'cpu': '2', 'memory': '1Gi'}},
       'volumeMounts': [token, {'name': 'tls', 'mountPath': '/run/tls', 'readOnly': True},
                       {'name': 'tmp', 'mountPath': '/tmp'}],
       'startupProbe': {'httpGet': {'scheme': 'HTTPS', 'port': 8093, 'path': '/healthz'}, 'periodSeconds': 5, 'failureThreshold': 40},
       'readinessProbe': {'httpGet': {'scheme': 'HTTPS', 'port': 8093, 'path': '/healthz'}, 'periodSeconds': 10}}
wyoming = {'name': 'wyoming', 'image': args.image, 'command': ['python', '-m', 'igw_google_voice.wyoming_speech'],
           'securityContext': security,
           'env': env + [{'name': 'RUSSIAN_SPEECH_ENDPOINT', 'value': 'https://127.0.0.1:8093/v1/speech'},
                         {'name': 'KITTEN_CA_FILE', 'value': '/run/ca/ca.crt'},
                         {'name': 'WYOMING_HOST', 'value': '0.0.0.0'}],
           'resources': {'requests': {'cpu': '25m', 'memory': '32Mi'}, 'limits': {'cpu': '250m', 'memory': '128Mi'}},
           'volumeMounts': [token, {'name': 'ca', 'mountPath': '/run/ca', 'readOnly': True}],
           'readinessProbe': {'tcpSocket': {'port': 10601}, 'periodSeconds': 10}}
metadata = {'name': args.name, 'namespace': args.namespace}
deployment = {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': metadata,
              'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'}, 'selector': {'matchLabels': labels},
                       'template': {'metadata': {'labels': labels}, 'spec': {
                           'nodeSelector': {'kubernetes.io/hostname': args.node}, 'automountServiceAccountToken': False,
                           'securityContext': {'runAsNonRoot': True, 'runAsUser': 10001, 'runAsGroup': 10001,
                                               'fsGroup': 10001, 'seccompProfile': {'type': 'RuntimeDefault'}},
                           'containers': [tts, wyoming],
                           'volumes': [{'name': 'token', 'secret': {'secretName': args.name + '-token', 'defaultMode': 288}},
                                       {'name': 'tls', 'secret': {'secretName': args.name + '-tls', 'defaultMode': 288}},
                                       {'name': 'ca', 'configMap': {'name': args.name + '-ca'}},
                                       {'name': 'tmp', 'emptyDir': {'medium': 'Memory', 'sizeLimit': '64Mi'}}]}}}}
service = {'apiVersion': 'v1', 'kind': 'Service', 'metadata': metadata,
           'spec': {'type': 'ClusterIP', 'selector': labels,
                    'ports': [{'name': 'wyoming', 'port': 10601, 'targetPort': 10601},
                              {'name': 'https', 'port': 8093, 'targetPort': 8093}]}}
print(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': [deployment, service]}, indent=2))
