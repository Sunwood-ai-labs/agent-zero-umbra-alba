#!/usr/bin/env python3
"""Manually run one randomized-social Hermes agent through the internal API."""

import argparse

from random_scheduler import AGENTS, run_agent


parser = argparse.ArgumentParser()
parser.add_argument("agent", choices=AGENTS)
args = parser.parse_args()
print(run_agent(args.agent))
