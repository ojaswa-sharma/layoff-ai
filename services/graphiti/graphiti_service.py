from services.graphiti.init_client import get_graphiti
# from models.zep_ontology import *
from models.graphiti_ontology import *
from graphiti_core.nodes import EpisodeType
import hashlib
from datetime import datetime
from datetime import timezone
import asyncio

ENTITIES={
    "Repository": Repository,
    "Bug": Bug,
    "Feature": Feature,
    "Commit": Commit,
    "Changes" : Changes,
    "Positives" : Positives,
    "Negatives" : Negatives,
}

DEV_ENTITES = {
    "Repository": Repository,
    "Bug": Bug,
    "Feature": Feature,
    "Commit": Commit,
    "Changes" : Changes,
    "Positives" : Positives,
    "Negatives" : Negatives,
    "Developer" : Developer
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
        print(f"[DEBUG] BEFORE ENCODING : {group_id}")
        raw = group_id.lower().strip()
        _id = hashlib.sha1(raw.encode()).hexdigest()
        print(f"[DEBUG] ENCODED ID : {_id}")
        return _id

    async def add_to_graph(
        self,
        message, 
        graph_id : str = None,
        commit_hash : str = "",
        commit_date = None
    ):
        try:
            _ = await self._client.add_episode(
                name = f"commit_data_{commit_hash}__{datetime.now().timestamp()}",
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

    async def add_message(self, user_id, message, thread_id, first_name = "", last_name = "", repo_name = None, email = None, date= None):

        text = message.content
        print(f"[DEBUG] ADDING TEXT : {text[:100]}...")
        # await self._client.add_episode(user_id=user_id, data = text[:min(len(text), 9999)], type="text", source_description="Data from github summarized by ai")
        await self._client.add_episode(
            name=f"commit_data__{datetime.now().timestamp()}",
            episode_body=text,
            source=EpisodeType.text,
            source_description=f"Commit tracked",
            group_id=self._encode(f"{user_id}"),
            reference_time=date or datetime.now(timezone.utc),
            entity_types=DEV_ENTITES,
            edge_types=EDGES,
            edge_type_map=EDGE_MAP
        )

        return {"status" : "success"} 
