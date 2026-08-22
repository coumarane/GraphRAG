"""Plugin discovery and capability registries.

Core adapters are registered in-process. Third-party plugins load from
``importlib.metadata`` entry points under ``graph_rag.*`` groups.
"""

from graph_rag.application.plugins.descriptors import PluginDescriptor, TrustTier
from graph_rag.application.plugins.discovery import PLUGIN_ENTRY_POINT_GROUPS, load_entry_points
from graph_rag.application.plugins.registry import PluginRegistry

__all__ = [
    "PLUGIN_ENTRY_POINT_GROUPS",
    "PluginDescriptor",
    "PluginRegistry",
    "TrustTier",
    "load_entry_points",
]
