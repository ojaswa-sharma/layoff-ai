from services.graphiti.init_client import get_graphiti
from models.zep_ontology import *
from graphiti_core.nodes import EpisodeType
import hashlib

ENTITIES={
    "Repository": Repository,
    "Bug": Bug,
    "Feature": Feature,
    "Commit": Commit,
    "Changes" : Changes,
    "Positives" : Positives,
    "Negatives" : Negatives,
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
                reference_time=commit_date
            )
        except Exception as e:
            print(f"[ERROR] Error while adding to graphiti: {e}")
            raise e