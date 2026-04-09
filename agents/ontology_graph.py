"""
FabricIQ Ontology Graph — Beneficial Ownership & Entity Resolution
==================================================================
Models the ownership structure between trading entities as a directed
graph, enabling multi-level UBO (Ultimate Beneficial Owner) resolution,
cross-listed instrument discovery, and jurisdiction-aware regulatory
lookups.

Entity types
------------
    Broker      — trading firm
    Account     — trading account
    Fund        — investment fund
    Holding     — holding company
    Person      — ultimate beneficial owner (UBO)
    Symbol      — tradable instrument
    Exchange    — marketplace
    Regulation  — regulatory rule

Relationships
-------------
    Broker     --owns_account-->    Account
    Broker     --parent_entity-->   Fund | Holding
    Fund       --parent_entity-->   Holding
    Holding    --beneficial_owner-> Person
    Symbol     --listed_on-->       Exchange
    Symbol     --correlated_with--> Symbol
    Symbol     --has_derivative-->  Symbol
    Regulation --applies_to-->      Exchange
    Regulation --governs-->         manipulation_type (attribute)
    Broker     --linked_to-->       Broker   (shared officer / office)

Graph traversal
---------------
The graph is implemented as a simple in-memory adjacency list.  For the
realistic scale of a regulatory ontology (thousands of entities) this is
sufficient.  Replace with a FabricIQ / graph-database backend for
production deployments.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entity & relationship type enumerations
# ---------------------------------------------------------------------------

class EntityType(str, Enum):
    BROKER     = "Broker"
    ACCOUNT    = "Account"
    FUND       = "Fund"
    HOLDING    = "Holding"
    PERSON     = "Person"
    SYMBOL     = "Symbol"
    EXCHANGE   = "Exchange"
    REGULATION = "Regulation"


class RelationshipType(str, Enum):
    OWNS_ACCOUNT      = "owns_account"
    PARENT_ENTITY     = "parent_entity"
    BENEFICIAL_OWNER  = "beneficial_owner"
    LISTED_ON         = "listed_on"
    CORRELATED_WITH   = "correlated_with"
    HAS_DERIVATIVE    = "has_derivative"
    APPLIES_TO        = "applies_to"
    GOVERNS           = "governs"
    LINKED_TO         = "linked_to"


# ---------------------------------------------------------------------------
# Internal data structures
# ---------------------------------------------------------------------------

@dataclass
class _Node:
    entity_id: str
    entity_type: EntityType
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class _Edge:
    source_id: str
    target_id: str
    rel_type: RelationshipType
    attributes: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Ontology Graph
# ---------------------------------------------------------------------------

class BeneficialOwnershipGraph:
    """
    In-memory ontology graph for beneficial ownership and entity resolution.

    Usage
    -----
    >>> graph = BeneficialOwnershipGraph()
    >>> graph.add_entity("BROKER_A", EntityType.BROKER)
    >>> graph.add_entity("FUND_X",   EntityType.FUND)
    >>> graph.add_entity("UBO_JOHN", EntityType.PERSON)
    >>> graph.add_relationship("BROKER_A", "FUND_X",   RelationshipType.PARENT_ENTITY)
    >>> graph.add_relationship("FUND_X",   "UBO_JOHN", RelationshipType.BENEFICIAL_OWNER)
    >>> graph.is_same_ubo("BROKER_A", "BROKER_B")  # False (BROKER_B not added)
    False
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, _Node] = {}
        # Forward adjacency list: source_id → list of _Edge
        self._out_edges: Dict[str, List[_Edge]] = defaultdict(list)
        # Reverse adjacency list: target_id → list of _Edge (for upward traversal)
        self._in_edges:  Dict[str, List[_Edge]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Mutation API
    # ------------------------------------------------------------------

    def add_entity(
        self,
        entity_id: str,
        entity_type: EntityType,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register an entity node in the graph."""
        self._nodes[entity_id] = _Node(
            entity_id=entity_id,
            entity_type=entity_type,
            attributes=attributes or {},
        )

    def add_relationship(
        self,
        source_id: str,
        target_id: str,
        rel_type: RelationshipType,
        attributes: Optional[Dict[str, Any]] = None,
        bidirectional: bool = False,
    ) -> None:
        """
        Add a directed relationship from *source_id* to *target_id*.

        Parameters
        ----------
        bidirectional : bool
            When ``True`` also adds the reverse edge (useful for
            ``correlated_with`` relationships that are symmetric).
        """
        edge = _Edge(
            source_id=source_id,
            target_id=target_id,
            rel_type=rel_type,
            attributes=attributes or {},
        )
        self._out_edges[source_id].append(edge)
        self._in_edges[target_id].append(edge)

        if bidirectional:
            rev = _Edge(
                source_id=target_id,
                target_id=source_id,
                rel_type=rel_type,
                attributes=attributes or {},
            )
            self._out_edges[target_id].append(rev)
            self._in_edges[source_id].append(rev)

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def get_entity(self, entity_id: str) -> Optional[_Node]:
        return self._nodes.get(entity_id)

    def get_ubos(self, entity_id: str, max_hops: int = 10) -> Set[str]:
        """
        Return the set of UBO (Person) entity IDs reachable from *entity_id*
        by traversing ownership-chain relationships upward.

        Traversal follows these relationship types in the outgoing direction:
            owns_account  (reversed: Account → Broker)
            parent_entity (Broker / Fund → Fund / Holding)
            beneficial_owner (Holding → Person)
            linked_to (Broker ↔ Broker, shared control)

        Parameters
        ----------
        max_hops : int
            Maximum graph depth to traverse (prevents infinite loops in
            cyclic structures).
        """
        _OWNERSHIP_RELS = {
            RelationshipType.PARENT_ENTITY,
            RelationshipType.BENEFICIAL_OWNER,
            RelationshipType.LINKED_TO,
        }
        ubos: Set[str] = set()
        visited: Set[str] = set()
        queue: deque[Tuple[str, int]] = deque([(entity_id, 0)])

        while queue:
            current_id, hops = queue.popleft()
            if current_id in visited or hops > max_hops:
                continue
            visited.add(current_id)

            node = self._nodes.get(current_id)
            if node and node.entity_type == EntityType.PERSON:
                ubos.add(current_id)

            # Traverse outgoing ownership edges
            for edge in self._out_edges.get(current_id, []):
                if edge.rel_type in _OWNERSHIP_RELS and edge.target_id not in visited:
                    queue.append((edge.target_id, hops + 1))

            # Also traverse incoming ``owns_account`` edges upward
            # (Account was created by Broker → Broker is "above" Account)
            for edge in self._in_edges.get(current_id, []):
                if (
                    edge.rel_type == RelationshipType.OWNS_ACCOUNT
                    and edge.source_id not in visited
                ):
                    queue.append((edge.source_id, hops + 1))

        return ubos

    def is_same_ubo(
        self,
        entity_a: str,
        entity_b: str,
        max_hops: int = 4,
    ) -> bool:
        """
        Return ``True`` if *entity_a* and *entity_b* share at least one
        Ultimate Beneficial Owner within *max_hops* graph hops.

        This replaces the naive ``"_WASH_" in broker_id`` string check with
        a proper graph traversal through multi-level ownership chains.

        Parameters
        ----------
        max_hops : int
            Maximum hops per entity when searching for UBOs.  4 is suitable
            for chains of depth: Account → Broker → Fund → Holding → Person.
        """
        ubos_a = self.get_ubos(entity_a, max_hops=max_hops)
        if not ubos_a:
            return False
        ubos_b = self.get_ubos(entity_b, max_hops=max_hops)
        return bool(ubos_a & ubos_b)

    def get_shared_ubos(
        self,
        entity_a: str,
        entity_b: str,
        max_hops: int = 4,
    ) -> Set[str]:
        """Return the set of UBO IDs shared between *entity_a* and *entity_b*."""
        return self.get_ubos(entity_a, max_hops) & self.get_ubos(entity_b, max_hops)

    def get_related_instruments(
        self,
        symbol: str,
        exchange: str,
        rel_types: Optional[Iterable[RelationshipType]] = None,
    ) -> List[Tuple[str, str, RelationshipType]]:
        """
        Return instruments related to *symbol* on *exchange* via ontology
        relationships.

        Traverses ``listed_on``, ``correlated_with``, and ``has_derivative``
        edges from the symbol node.

        Returns
        -------
        List of (symbol_id, exchange_id, relationship_type) tuples.
        """
        _DEFAULT_RELS = {
            RelationshipType.LISTED_ON,
            RelationshipType.CORRELATED_WITH,
            RelationshipType.HAS_DERIVATIVE,
        }
        target_rels = set(rel_types) if rel_types else _DEFAULT_RELS

        results: List[Tuple[str, str, RelationshipType]] = []
        # Prefer a canonical key like "SYMBOL:EXCHANGE"
        canonical_key = f"{symbol}:{exchange}"
        search_ids = [canonical_key, symbol]

        visited: Set[str] = set()
        queue: deque[str] = deque(search_ids)

        while queue:
            current_id = queue.popleft()
            if current_id in visited:
                continue
            visited.add(current_id)

            for edge in self._out_edges.get(current_id, []):
                if edge.rel_type not in target_rels:
                    continue
                target_node = self._nodes.get(edge.target_id)
                if target_node is None:
                    continue

                if target_node.entity_type == EntityType.SYMBOL:
                    # Resolve to (symbol, exchange) pair
                    sym_id = edge.target_id
                    exch_id = edge.attributes.get("exchange", "")
                    results.append((sym_id, exch_id, edge.rel_type))
                    if sym_id not in visited:
                        queue.append(sym_id)
                elif target_node.entity_type == EntityType.EXCHANGE:
                    # listed_on: the symbol is cross-listed on this exchange
                    exch_id = edge.target_id
                    results.append((symbol, exch_id, edge.rel_type))

        return results

    def get_applicable_regulations(
        self,
        exchange: str,
        manipulation_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return regulations that apply to *exchange*, optionally filtered by
        manipulation type.

        Traverses ``applies_to`` edges from Regulation nodes to the Exchange
        node and returns regulation metadata (name, jurisdiction, body).

        Parameters
        ----------
        exchange : str
            Exchange entity ID (e.g. ``"SGX"``, ``"HKEX"``).
        manipulation_type : str, optional
            If provided, only return regulations whose ``governs`` attribute
            includes this manipulation type (e.g. ``"SPOOFING"``).
        """
        regulations: List[Dict[str, Any]] = []

        # Collect all Regulation nodes that have an applies_to edge to this exchange
        for reg_id, node in self._nodes.items():
            if node.entity_type != EntityType.REGULATION:
                continue
            for edge in self._out_edges.get(reg_id, []):
                if edge.rel_type == RelationshipType.APPLIES_TO and edge.target_id == exchange:
                    reg_info = {
                        "regulation_id": reg_id,
                        "name": node.attributes.get("name", reg_id),
                        "jurisdiction": node.attributes.get("jurisdiction", ""),
                        "regulatory_body": node.attributes.get("regulatory_body", ""),
                        "governs": node.attributes.get("governs", []),
                        "exchange": exchange,
                    }
                    if manipulation_type is None or manipulation_type in reg_info["governs"]:
                        regulations.append(reg_info)

        return regulations

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def build_default(cls) -> "BeneficialOwnershipGraph":
        """
        Construct the default ontology graph populated with:
        - SGX, HKEX, NSE exchanges
        - MAS, SFC, SEBI regulations for all manipulation types
        - Sample broker ownership chains (≥3 levels deep) for demonstration

        This replaces the hard-coded ``REGULATOR_MAP`` dict with a graph
        that supports richer regulatory lookups and ownership traversal.
        """
        g = cls()

        # ── Exchanges ──────────────────────────────────────────────────
        for exch in ("SGX", "HKEX", "NSE"):
            g.add_entity(exch, EntityType.EXCHANGE, {"name": exch})

        # ── Regulations → Exchange relationships ───────────────────────
        _MANIPULATION_TYPES = [
            "SPOOFING", "LAYERING", "WASH_TRADING",
            "PRICE_ANOMALY", "VOLUME_SPIKE", "COORDINATED_MANIPULATION",
        ]

        reg_defs = [
            ("REG_MAS_SFA",    "Securities and Futures Act (SFA)",        "Singapore", "MAS",  "SGX"),
            ("REG_MAS_MAR",    "Market Abuse Regulations (MAS Notice)",   "Singapore", "MAS",  "SGX"),
            ("REG_SFC_ORD",    "Securities and Futures Ordinance (SFO)",  "Hong Kong", "SFC",  "HKEX"),
            ("REG_SFC_COP",    "Code of Conduct — Market Integrity",       "Hong Kong", "SFC",  "HKEX"),
            ("REG_SEBI_PFUTP", "PFUTP Regulations 2003",                   "India",     "SEBI", "NSE"),
            ("REG_SEBI_SAST",  "SAST Regulations — Disclosure Rules",     "India",     "SEBI", "NSE"),
        ]

        for reg_id, name, jurisdiction, body, exchange in reg_defs:
            g.add_entity(reg_id, EntityType.REGULATION, {
                "name": name,
                "jurisdiction": jurisdiction,
                "regulatory_body": body,
                "governs": _MANIPULATION_TYPES,
            })
            g.add_relationship(reg_id, exchange, RelationshipType.APPLIES_TO)

        # ── Sample broker ownership chains (≥3 levels) ─────────────────
        # Chain 1: BROKER_WASH_SGX_003 and BROKER_WASH_SGX_004_ALT share a UBO
        #   BROKER_WASH_SGX_003 → FUND_ALPHA → HOLDING_GLOBAL → PERSON_UBO_SMITH
        #   BROKER_WASH_SGX_004_ALT → FUND_ALPHA → ... (same chain)
        for entity_id, etype, attrs in [
            ("FUND_ALPHA",       EntityType.FUND,    {"name": "Alpha Capital Fund"}),
            ("HOLDING_GLOBAL",   EntityType.HOLDING, {"name": "Global Holdings Inc"}),
            ("PERSON_UBO_SMITH", EntityType.PERSON,  {"name": "J. Smith", "nationality": "SG"}),
            ("BROKER_WASH_SGX_003",     EntityType.BROKER,  {"exchange": "SGX"}),
            ("BROKER_WASH_SGX_004_ALT", EntityType.BROKER,  {"exchange": "SGX"}),
        ]:
            g.add_entity(entity_id, etype, attrs)

        g.add_relationship("BROKER_WASH_SGX_003",     "FUND_ALPHA",       RelationshipType.PARENT_ENTITY)
        g.add_relationship("BROKER_WASH_SGX_004_ALT", "FUND_ALPHA",       RelationshipType.PARENT_ENTITY)
        g.add_relationship("FUND_ALPHA",               "HOLDING_GLOBAL",   RelationshipType.PARENT_ENTITY)
        g.add_relationship("HOLDING_GLOBAL",           "PERSON_UBO_SMITH", RelationshipType.BENEFICIAL_OWNER)

        # Chain 2: linked_to relationship (shared compliance officer)
        for entity_id, etype, attrs in [
            ("BROKER_LINKED_A", EntityType.BROKER, {"exchange": "SGX"}),
            ("BROKER_LINKED_B", EntityType.BROKER, {"exchange": "SGX"}),
        ]:
            g.add_entity(entity_id, etype, attrs)
        g.add_relationship(
            "BROKER_LINKED_A", "BROKER_LINKED_B",
            RelationshipType.LINKED_TO,
            attributes={"reason": "shared_compliance_officer"},
            bidirectional=True,
        )

        # ── Symbol listings & correlations ─────────────────────────────
        for sym in ("OCBC", "DBS", "UOB", "TENCENT", "RELIANCE", "SENSEX_FUT"):
            g.add_entity(sym, EntityType.SYMBOL, {"ticker": sym})

        # OCBC listed on SGX
        g.add_relationship("OCBC", "SGX", RelationshipType.LISTED_ON)
        # TENCENT listed on HKEX; cross-listed equivalent on SGX
        g.add_relationship("TENCENT", "HKEX", RelationshipType.LISTED_ON)
        g.add_relationship("TENCENT", "SGX",  RelationshipType.LISTED_ON,
                           attributes={"ticker_on_exchange": "TCEHY"})
        # RELIANCE listed on NSE
        g.add_relationship("RELIANCE", "NSE", RelationshipType.LISTED_ON)
        # SENSEX_FUT is a derivative of RELIANCE (basket component)
        g.add_relationship("SENSEX_FUT", "RELIANCE", RelationshipType.HAS_DERIVATIVE)
        # Correlation between OCBC and DBS (same sector)
        g.add_relationship("OCBC", "DBS", RelationshipType.CORRELATED_WITH, bidirectional=True)

        logger.info("BeneficialOwnershipGraph: default ontology populated (%d entities).", len(g._nodes))
        return g

    # ------------------------------------------------------------------
    # Persistence helpers (for FabricIQ / OneLake integration)
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the graph to a JSON-compatible dictionary."""
        return {
            "nodes": [
                {
                    "entity_id": n.entity_id,
                    "entity_type": n.entity_type.value,
                    "attributes": n.attributes,
                }
                for n in self._nodes.values()
            ],
            "edges": [
                {
                    "source_id": e.source_id,
                    "target_id": e.target_id,
                    "rel_type": e.rel_type.value,
                    "attributes": e.attributes,
                }
                for edges in self._out_edges.values()
                for e in edges
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BeneficialOwnershipGraph":
        """Reconstruct a graph from the ``to_dict`` representation."""
        g = cls()
        for n in data.get("nodes", []):
            g.add_entity(n["entity_id"], EntityType(n["entity_type"]), n.get("attributes", {}))
        for e in data.get("edges", []):
            g.add_relationship(
                e["source_id"], e["target_id"],
                RelationshipType(e["rel_type"]), e.get("attributes", {}),
            )
        return g

    def __len__(self) -> int:
        return len(self._nodes)

    def __repr__(self) -> str:
        edge_count = sum(len(v) for v in self._out_edges.values())
        return f"BeneficialOwnershipGraph(nodes={len(self._nodes)}, edges={edge_count})"
