import asyncio
import os
import json

from dotenv import load_dotenv
from collections import deque
from dataclasses import dataclass

from zep_cloud.client import AsyncZep
from zep_cloud.types import Message, UserInstruction, FactRatingInstruction
from zep_cloud import EntityEdgeSourceTarget
from models.zep_ontology import Repository, RepositoryContainsBug, RepositoryContainsFeature, Feature, FeatureRealizedByCommit, Bug, BugAddressedByCommit, Commit, Positives, Negatives, Changes, Developer

@dataclass(frozen=True)
class botMessage:
    content : list
    role : str

@dataclass(frozen=True)
class botFact:
    fact : str
    fact_type : str

@dataclass(frozen=True)
class ZepData:
    user_id : str
    message : botMessage|botFact
    first_name : str = ""
    last_name : str = ""
    data_type : str = 'message'
    thread_id : str|None = None


    def decompose(self):
        return self.user_id, self.thread_id, self.message, self.first_name, self.last_name

load_dotenv()

def json_to_md(data, level=1):
    md = ""
    if isinstance(data, dict):
        for key, value in data.items():
            md += f"{'#' * level} {key}\n"
            md += json_to_md(value, level + 1)
        md += "\n"
    elif isinstance(data, list):
        for i, item in enumerate(data, 1):
            md += json_to_md(item, level + 1)
    else:
        md += f"{' ' * (level * 2)}- {data}\n"
    return md


class ZepPersonalizer():
    def __init__(self, api_key = None, instruction = None, examples = None):
        self.zep_conn = AsyncZep(
            api_key = os.getenv("ZEP_API_KEY") if not api_key else api_key
        )

        self.custom_ontology = """
        Entities to extract:
        - Developer identity and recurring contributors
        - Commit summaries and recurring work themes
        - Work categories (real vs fake work patterns)
        - Work departments (ui, frontend, backend, devops)
        - Work types (major_features, minor_features, ui_bugs, functional_bugs, tech_debt, other)
        - Performance signals (high impact, low impact, cosmetic, critical fixes)
        - Frequency of commits per work type
        - Repeated low-value or high-value contribution patterns

        Relations to capture:
        - Developer PRODUCES commit
        - Commit BELONGS_TO department
        - Commit HAS_TYPE work_type
        - Commit HAS_CATEGORY work_category
        - Developer CONSISTENTLY_WORKS_ON department
        - Developer FREQUENTLY_PRODUCES work_type
        - Developer EXHIBITS performance_pattern

        Prioritize:
        1. High importance:
        - Repeated real vs fake work patterns
        - Consistent department ownership
        - Major feature delivery
        - Recurrent tech debt or bug fixing behavior
        2. Medium importance:
        - Minor features and UI-related work
        - Commit quality and clarity trends
        - Mixed-value contributions
        3. Low importance:
        - One-off commits
        - Isolated cosmetic changes
        - Single vague or low-context commits
        """


        self.user_summary_instruction = instruction or """
            Create a concise summary of the developer's recurring work patterns and contribution quality based on commit history.

            Focus on:
            - Primary departments the developer works in (ui, frontend, backend, devops)
            - Predominant work types (features, bug fixes, tech debt)
            - Ratio of real vs fake work over time
            - Consistency and impact of contributions
            - Repeated high-value or low-value behavior patterns
            - Strengths and potential risk signals (e.g., frequent cosmetic commits, strong ownership of critical systems)

            Give priority to recurring behaviors over isolated commits.
            Summarize trends, not individual commits.
            DO NOT CAPTURE ANY PERSONAL INFORMATION OR DATA OUTSIDE ENGINEERING WORK.
            DO NOT INFER MOTIVATION, INTENT, OR CONTEXT NOT PRESENT IN THE DATA.
        """


        self.examples = examples
        self.tasks = deque()
        self.lock = asyncio.Lock()

        self.loop_running = False

    async def upsert_user(self, user_id=None, first_name = None, last_name = None, email = None, graph_id = None):
        try:
            if user_id:
                existing = await self.zep_conn.user.get(user_id = user_id)
            if graph_id:
                existing = await self.zep_conn.graph.get(graph_id=graph_id)
        except Exception as e:
            if user_id:
                data = {"user_id" : user_id}
            if first_name:
                data['first_name'] = first_name.split()[0] if first_name.split() else first_name
            if last_name:
                data['last_name'] = last_name.split()[0] if last_name.split() else last_name
            if email:
                data['email'] = email

            if user_id:
                # await self.zep_conn.user.add(**data)
                await self.zep_conn.user.add(user_id=user_id, fact_rating_instruction=FactRatingInstruction(instruction=self.user_summary_instruction))

                await self.zep_conn.graph.set_ontology(
                entities={
                    "Repository": Repository,
                    "Bug": Bug,
                    "Feature": Feature,
                    "Commit": Commit,
                    "Changes" : Changes,
                    "Positives" : Positives,
                    "Negatives" : Negatives,
                },
                edges={
                    "REPOSITORY_CONTAINS_BUG": (
                        RepositoryContainsBug,
                        [EntityEdgeSourceTarget(source="Repository", target="Bug")],
                    ),
                    "REPOSITORY_CONTAINS_FEATURE": (
                        RepositoryContainsFeature,
                        [EntityEdgeSourceTarget(source="Repository", target="Feature")],
                    ),
                    "BUG_ADDRESSED_BY_COMMIT": (
                        BugAddressedByCommit,
                        [EntityEdgeSourceTarget(source="Bug", target="Commit")],
                    ),
                    "FEATURE_REALIZED_BY_COMMIT": (
                        FeatureRealizedByCommit,
                        [EntityEdgeSourceTarget(source="Feature", target="Commit")],
                    ),
                },
                user_ids=[user_id]
            )

            if graph_id:
            #     await self.zep_conn.graph.create(graph_id, fact_rating_instruction=[
            #     FactRatingInstruction(
            #         instruction=(
            #             "Extract information about the developer's primary engineering focus, "
            #             "including dominant departments (ui, frontend, backend, devops), "
            #             "types of work they most frequently perform, and areas of technical strength."
            #         )
            #     ),
            #     FactRatingInstruction(
            #         instruction=(
            #             "Capture patterns related to the quality and impact of the developer's contributions, "
            #             "including frequency of real vs fake work, delivery of major features, "
            #             "handling of critical bugs, and tendency toward low-impact or cosmetic changes."
            #         )
            #     ),
            #     FactRatingInstruction(
            #         instruction=(
            #             "Capture the developer's work style and delivery behavior, such as consistency of output, "
            #             "preference for features vs bug fixes vs tech debt, clarity of commits, "
            #             "and recurring contribution patterns over time."
            #         )
            #     )
            # ])
                await self.zep_conn.graph.create(graph_id=graph_id, fact_rating_instruction=FactRatingInstruction(instruction=self.user_summary_instruction))

                await self.zep_conn.graph.set_ontology(
                entities={
                    "Repository": Repository,
                    "Bug": Bug,
                    "Feature": Feature,
                    "Commit": Commit,
                    "Changes" : Changes,
                    "Positives" : Positives,
                    "Negatives" : Negatives
                },
                edges={
                    "REPOSITORY_CONTAINS_BUG": (
                        RepositoryContainsBug,
                        [EntityEdgeSourceTarget(source="Repository", target="Bug")],
                    ),
                    "REPOSITORY_CONTAINS_FEATURE": (
                        RepositoryContainsFeature,
                        [EntityEdgeSourceTarget(source="Repository", target="Feature")],
                    ),
                    "BUG_ADDRESSED_BY_COMMIT": (
                        BugAddressedByCommit,
                        [EntityEdgeSourceTarget(source="Bug", target="Commit")],
                    ),
                    "FEATURE_REALIZED_BY_COMMIT": (
                        FeatureRealizedByCommit,
                        [EntityEdgeSourceTarget(source="Feature", target="Commit")],
                    ),
                },
                graph_ids=[graph_id]
            )

    async def add_message(self, user_id, message, thread_id, first_name = "", last_name = "", repo_name = None, email = None):
        await self.upsert_user(user_id, first_name, last_name, email)

        thread_id = str(thread_id)
        text = message.content
        await self.zep_conn.graph.add(user_id=user_id, data = text[:min(len(text), 9999)], type="text", source_description="Data from github summarized by ai")

        return {"status" : "success"} 

    async def add_to_graph(self, graph_id, message):
        await self.upsert_user(graph_id=graph_id)
        await self.zep_conn.graph.add(
            data = message[:min(len(message), 9999)],
            graph_id=graph_id,
            source_description="Data from github summarized by ai",
            type="text",
        )

    async def add_fact(self, user_id, message, first_name = "", last_name = ""):
        await self.upsert_user(user_id, first_name, last_name)

        try:
            fact_text, fact_type = message.fact, message.fact_type
            print('[DEBUGGGG] STARTED')
            
            await self.zep_conn.graph.add(
                data = fact_text[:min(len(fact_text), 9999)],
                type= fact_type,
                user_id = user_id
            )

            return {"status" : "success"}

        except Exception as e:
            print(f"[ERROR] Error adding fact: {e}")


    async def get_context(self, user_id, query = None, top_n = 3):
        if not query:
            query = "tell me about my preferences"
        try:
            fact_objs = await self.zep_conn.graph.search(
                query = query, 
                user_id = user_id, 
                scope="nodes"
            )
            facts = []
            
            for edge in fact_objs.nodes:
                facts.append((edge.score, edge.summary))      
                print(f"{edge.score} : {edge.summary}")      
            
            facts.sort(key=lambda x: x[0], reverse=True)
            top_facts = [fact[1] for fact in facts[:top_n]]
            
            return '\n'.join(top_facts)
        except Exception as e:
            print(f"[ERROR] Error getting context: {e}")
            return ""
    
    async def get_project_data(self, graph_id, query = None):
        if not query:
            query = "What work was done by the developer, the bugs created, and the changes, as well as the positives and negatives"
        try:
            data = await self.zep_conn.graph.search(
                query=query,
                graph_id=graph_id,
                scope="nodes",
                search_filters={
                    "node_labels": [
                        "Bug",
                        "Positives",
                        "Negatives",
                        "Changes",
                        "Commit",
                    ]
                },
                limit=20
            )

            nodes = []
            for edge in data.nodes:
                print(edge.labels)
                # print(edge.summary)
                # print(edge.attributes)
                if "Positives" in edge.labels:
                    nodes.append({
                        "type" : "POSITVE",
                        "summary" : edge.summary,
                        "attributes" : edge.attributes
                    })
                elif "Commit" in edge.labels:
                    nodes.append({
                        "type" : "COMMIT",
                        "summary" : edge.summary,
                        "attributes" : edge.attributes
                    })
                elif "Bug" in edge.labels:
                    nodes.append({
                        "type" : "BUG",
                        "summary" : edge.summary,
                        "attributes" : edge.attributes
                    })
                elif "Changes" in edge.labels:
                    nodes.append({
                        "type" : "CHANGES",
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
            print(f"[ERROR] Error while getting nodes : {e}")


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