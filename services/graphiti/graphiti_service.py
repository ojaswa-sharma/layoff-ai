from services.graphiti.init_client import get_graphiti, get_driver
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
        self._driver = get_driver()

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
            name=f"commit_data__{user_id}__{datetime.now().timestamp()}",
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
                # search_filter=SearchFilters(node_labels=["Positives","Negatives"]),
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


    async def get_user_persona(self, user_id: str):
        try:
            _id = self._encode(f"user_{user_id}")
            graph = self._driver._get_graph(_id)

            query = """
                MATCH (n:Positives)
                WHERE n.group_id = $group_id
                WITH n ORDER BY n.created_at DESC LIMIT 5
                RETURN n

                UNION ALL

                MATCH (n:Negatives)
                WHERE n.group_id = $group_id
                WITH n ORDER BY n.created_at DESC LIMIT 5
                RETURN n

                UNION ALL

                MATCH (n:Feature)
                WHERE n.group_id = $group_id
                WITH n ORDER BY n.created_at DESC LIMIT 5
                RETURN n

                UNION ALL

                MATCH (n:Developer)
                WHERE n.group_id = $group_id
                WITH n ORDER BY n.created_at DESC LIMIT 1
                RETURN n
            """

            result = await graph.query(query, params={"group_id": _id})

            nodes = []
            for row in result.result_set:
                node = row[0]
                labels = node.labels
                props = node.properties
                props.pop("name_embedding", None)

                labels = [l for l in labels if l != "Entity"]
                label_name = labels[0] if labels else "Unknown"

                properties = {
                    "name": props.get("name"),
                    # "summary": props.get("summary"),
                    "created_at": props.get("created_at"),
                }

                if label_name == "Positives":
                    properties["positve_work_summary"] = props.get("positve_work_summary")
                elif label_name == "Feature":
                    properties["feature_name"] = props.get("feature_name")
                    properties["feature_description"] = props.get("feature_description")
                elif label_name == "Developer":
                    properties["summary"] = props.get("summary"),
                    properties["developer_work"] = props.get("developer_work")

                nodes.append({
                    "label": label_name,
                    "properties": properties,
                })

            return nodes
        except Exception as e:
            print(f"[ERROR] Couldnt pull from graphiti : {e}")
            return []