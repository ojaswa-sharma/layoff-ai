from services.graphiti.init_client import get_graphiti
# from models.zep_ontology import *
from models.graphiti_ontology import *
from graphiti_core.nodes import EpisodeType
from graphiti_core.search.search_filters import SearchFilters

import hashlib
from datetime import datetime
from datetime import timezone
import asyncio
import re

REDISEARCH_SPECIAL = r'([,.<>{}\[\]"\'\:;!@#$%^&*()\-\+=~\/\\])'


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
        # print(f"[DEBUG] BEFORE ENCODING : {group_id}")
        raw = group_id.lower().strip()
        _id = hashlib.sha1(raw.encode()).hexdigest()
        # print(f"[DEBUG] ENCODED ID : {_id}")
        return _id
    def sanitize_redisearch(self, text: str) -> str:
        return re.sub(REDISEARCH_SPECIAL, r'\\\1', text)

    async def add_to_graph(
        self,
        message, 
        graph_id : str = None,
        commit_hash : str = "",
        commit_date = None
    ):
        try:
            message = self.sanitize_redisearch(message)
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

        text = self.sanitize_redisearch(message.content)
        # print(f"[DEBUG] ADDING TEXT : {text[:100]}...")
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

    async def get_project_data(self, graph_id, query = None):
        try:
            query = query or "What work was done by the developer, the bugs created, and the changes, as well as the positives and negatives"
            data = await self._client.search(
                query=query,
                group_ids=[self._encode(f"{graph_id}")],
            )
            nodes = []
            for edge in data:
                if "Positives" in edge.labels:
                    nodes.append({
                        "type" : "POSITVE",
                        "summary" : edge.summary,
                        "attributes" : edge.attributes
                    })
                elif "Negatives" in edge.labels:
                    nodes.append({
                        "type" : "NEGATIVES",
                        "summary" : edge.summary,
                        "attributes" : edge.attributes
                    })
            return nodes
        except Exception as e:
            print(f'[ERROR] Soemthing went wrong while getting project data from graphiti : {e}')
            return []

    async def get_user_persona(self, user_id):
        try:
            print(f"[DEBUG] Getting persona for user_id: {user_id}")
            user_node = await self.zep_conn.user.get_node(user_id=user_id)
            print(f"[DEBUG] User node response: {user_node}")
            print(f"[DEBUG] User node type: {type(user_node)}")
            
            if user_node and hasattr(user_node, 'node') and user_node.node:
                print(f"[DEBUG] User node.node: {user_node.node}")
                print(f"[DEBUG] User node.node.summary: {user_node.node.summary}")
                return user_node.node.summary or ""
            else:
                print(f"[DEBUG] No valid node found in response")
                return ""
        except Exception as e:
            print(f"[ERROR] Error getting user persona: {e}")
            import traceback
            traceback.print_exc()
            return ""