#!/usr/bin/env python3
"""Render a loopback-only native macOS Nano service for encrypted SSH forwarding."""
import argparse
import ipaddress
from pathlib import Path
import plistlib
import re
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--user', required=True)
parser.add_argument('--address', default='127.0.0.1',
                    help='IPv4 loopback only; NAS access requires an SSH tunnel')
parser.add_argument('--threads', type=int, choices=range(1, 5), default=4)
args = parser.parse_args()
address = ipaddress.ip_address(args.address)
if address.version != 4 or not address.is_loopback:
    parser.error('Use an IPv4 loopback address; NAS access requires an encrypted SSH tunnel')
if not args.root.is_absolute() or any(ord(c) < 32 for c in str(args.root)):
    parser.error('The runtime root must be an absolute path')
if args.user == 'root' or not re.fullmatch(r'[a-z_][a-z0-9_-]{0,63}', args.user):
    parser.error('Choose an existing unprivileged macOS user')
root = args.root
document = {
    'Label': 'org.igw.kitten-primary',
    'UserName': args.user,
    'ProgramArguments': [str(root / 'bin/python'), '-m', 'igw_google_voice.kitten_service'],
    'WorkingDirectory': str(root / 'app'),
    'EnvironmentVariables': {
        'PYTHONPATH': str(root / 'app'), 'PYTHONDONTWRITEBYTECODE': '1',
        'PYTHONUNBUFFERED': '1', 'HF_HUB_OFFLINE': '1', 'HF_HUB_DISABLE_TELEMETRY': '1',
        'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'VECLIB_MAXIMUM_THREADS': '1',
        'KITTEN_BIND_HOST': str(address), 'KITTEN_THREADS': str(args.threads),
        'KITTEN_MODEL_DIR': str(root / 'models/nano-fp32'),
        'KITTEN_TOKEN_FILE': str(root / 'speech-token'),
        'KITTEN_TLS_CERT_FILE': str(root / 'tls/server.crt'),
        'KITTEN_TLS_KEY_FILE': str(root / 'tls/server.key'),
    },
    'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 30,
    'ExitTimeOut': 10, 'Umask': 63,
    'StandardOutPath': str(root / 'service.log'),
    'StandardErrorPath': str(root / 'service.log'),
}
sys.stdout.buffer.write(plistlib.dumps(document))
