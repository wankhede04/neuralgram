"""Typed exception hierarchy (standards §7). All Neuralgram errors derive from NeuralgramError."""


class NeuralgramError(Exception):
    """Base class for all Neuralgram-specific errors."""


class MissingTenantScopeError(NeuralgramError):
    """A tenant-scoped repository was used without a valid tenant_id."""


class UnsupportedSourceError(NeuralgramError):
    """An ingest payload arrived for a source_type with no registered normalizer."""
