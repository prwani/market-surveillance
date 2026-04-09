"""
Market Surveillance Agents
===========================
Multi-agent system for real-time market manipulation detection and intervention.

Agents:
    PatternDetectionAgent     - Spoofing, layering, wash trading detection
    AnomalyDetectionAgent     - Price and volume anomaly detection
    CrossMarketAgent          - Cross-exchange correlation and lead-lag analysis
    InterventionAgent         - Trade halt requests and regulator notifications
    EvidenceCollectionAgent   - Audit trail compilation and case report generation

Ontology:
    BeneficialOwnershipGraph  - Entity graph for UBO resolution, instrument
                                relationships, and jurisdiction-aware regulations
    EntityType                - Enumeration of graph entity types
    RelationshipType          - Enumeration of graph relationship types
"""

from .anomaly_detection_agent import AnomalyDetectionAgent
from .base_agent import Alert, AlertSeverity, BaseAgent
from .cross_market_agent import CrossMarketAgent
from .evidence_collection_agent import EvidenceCollectionAgent
from .intervention_agent import CaseStatus, InterventionAgent, InterventionCase
from .ontology_graph import BeneficialOwnershipGraph, EntityType, RelationshipType
from .pattern_detection_agent import PatternDetectionAgent

__all__ = [
    "BaseAgent",
    "Alert",
    "AlertSeverity",
    "PatternDetectionAgent",
    "AnomalyDetectionAgent",
    "CrossMarketAgent",
    "InterventionAgent",
    "InterventionCase",
    "CaseStatus",
    "EvidenceCollectionAgent",
    "BeneficialOwnershipGraph",
    "EntityType",
    "RelationshipType",
]
