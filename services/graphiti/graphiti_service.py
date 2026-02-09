from services.graphiti.init_client import get_graphiti
# from models.zep_ontology import *
from models.graphiti_ontology import *
from graphiti_core.nodes import EpisodeType
import hashlib
from datetime import datetime
from datetime import timezone

ENTITIES={
    "Repository": Repository,
    "Bug": Bug,
    "Feature": Feature,
    "Commit": Commit,
    "Changes" : Changes,
    "Positives" : Positives,
    "Negatives" : Negatives,
}

EDGES = {
    "REPOSITORY_CONTAINS_BUG": RepositoryContainsBug,
    "REPOSITORY_CONTAINS_FEATURE": RepositoryContainsFeature,
    "BUG_ADDRESSED_BY_COMMIT": BugAddressedByCommit,
    "FEATURE_REALIZED_BY_COMMIT": FeatureRealizedByCommit
}

EDGE_MAP = {
    ("Repository", "Bug") : ["REPOSITORY_CONTAINS_BUG"],
    ("Repository", "Feature") : ["REPOSITORY_CONTAINS_FEATURE"],
    ("Bug", "Commit") : ["BUG_ADDRESSED_BY_COMMIT"],
    ("Feature", "Commit") : ["FEATURE_REALIZED_BY_COMMIT"]
}

class Personalizer:
    def __init__(self):
        self._client = get_graphiti()

    def _encode(self, group_id : str):
        raw = group_id.lower().strip()
        return hashlib.sha1(raw.encode()).hexdigest()

    async def add_to_graph(
        self,
        message, 
        graph_id : str = None,
        commit_hash : str = "",
        commit_date = None
    ):
        try:
            _ = await self._client.add_episode(
                name = f"commit_data_{commit_hash}",
                episode_body=message,
                source=EpisodeType.text,
                source_description=f"github commit",
                group_id=self._encode(f"{graph_id}"),
                reference_time=commit_date or datetime.now(timezone.utc),
                entity_types=ENTITIES,
                edge_types=EDGES,
                edge_type_map=EDGE_MAP
            )
        except Exception as e:
            print(f"[ERROR] Error while adding to graphiti: {e}")
            raise e