"""Reweave — self-healing web data pipelines.

The runtime keeps three loops honest:

* the **Sentinel** watches every extraction for structural drift,
* the **Surgeon** synthesizes a repaired extraction spec from golden records,
* the **Gate** refuses to deploy any repair a human has not approved.
"""

__version__ = "0.3.0"
