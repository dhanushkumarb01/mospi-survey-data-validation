"""Fixed, conservative V1 configuration for contextual evidence."""

from __future__ import annotations


CONTEXTUAL_METHOD_VERSION = "plfs-contextual-v1.0"
CONTEXTUAL_TARGET = "principal_occupation_code"

# This is an existing peer-group target, not a new contextual grouping scheme.
# Its first-visit profile conditions on state, sector, CWS status and, where
# support permits, the supplied industry division.  It intentionally does not
# contain occupation, avoiding target leakage for the target below.
REFERENCE_ASSIGNMENT_TARGET = "day7_total_hours"

METHOD_IDENTIFIER = "empirical_conditional_occupation_frequency_existing_day7_peer_groups"
METHOD_VERSION = CONTEXTUAL_METHOD_VERSION
VALID_OCCUPATION_PATTERN = r"\d{3}"
