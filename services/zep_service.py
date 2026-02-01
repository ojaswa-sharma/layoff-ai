import asyncio
import os
import json

from dotenv import load_dotenv
from collections import deque
from dataclasses import dataclass

from zep_cloud.client import AsyncZep
from zep_cloud.types import Message
from zep_cloud.external_clients.ontology import EntityModel, EntityText, EdgeModel, EntityBoolean, EntityInt
from zep_cloud import EntityEdgeSourceTarget
from pydantic import Field

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


# ============================================================================
# CUSTOM ENTITY TYPES FOR DEVELOPER ANALYSIS
# ============================================================================

class DeveloperStrength(EntityModel):
    """
    Represents a strength or positive skill exhibited by a developer.
    """
    strength_category: EntityText = Field(
        description="Category of the strength: technical_skill, leadership, collaboration, problem_solving, etc.",
        default=None
    )
    evidence: EntityText = Field(
        description="Specific evidence or examples demonstrating this strength",
        default=None
    )
    impact_level: EntityText = Field(
        description="Impact level of this strength: high, medium, low",
        default=None
    )

class DeveloperWeakness(EntityModel):
    """
    Represents a weakness or area for improvement for a developer.
    """
    weakness_category: EntityText = Field(
        description="Category of the weakness: code_quality, communication, time_management, technical_gaps, etc.",
        default=None
    )
    evidence: EntityText = Field(
        description="Specific evidence or examples demonstrating this weakness",
        default=None
    )
    severity: EntityText = Field(
        description="Severity of this weakness: critical, moderate, minor",
        default=None
    )

class WorkSummary(EntityModel):
    """
    Represents a summary of work done by a developer in a specific area or timeframe.
    """
    work_type: EntityText = Field(
        description="Type of work: major_features, minor_features, ui_bugs, functional_bugs, tech_debt, other",
        default=None
    )
    department: EntityText = Field(
        description="Department or area: ui, frontend, backend, devops, infrastructure, etc.",
        default=None
    )
    commit_count: EntityInt = Field(
        description="Number of commits in this category",
        default=None
    )
    quality_assessment: EntityText = Field(
        description="Overall quality assessment: excellent, good, fair, poor",
        default=None
    )

class Recommendation(EntityModel):
    """
    Represents a recommendation for developer improvement or recognition.
    """
    recommendation_type: EntityText = Field(
        description="Type of recommendation: training, role_change, recognition, process_improvement, etc.",
        default=None
    )
    priority: EntityText = Field(
        description="Priority level: high, medium, low",
        default=None
    )
    rationale: EntityText = Field(
        description="Detailed rationale for this recommendation",
        default=None
    )

class Repository(EntityModel):
    """
    Represents a code repository or project.
    """
    repo_name: EntityText = Field(
        description="Name of the repository",
        default=None
    )
    tech_stack: EntityText = Field(
        description="Primary technologies used in this repository",
        default=None
    )
    project_type: EntityText = Field(
        description="Type of project: web_app, mobile_app, library, service, etc.",
        default=None
    )

class CommitPattern(EntityModel):
    """
    Represents a pattern observed in developer commits.
    """
    pattern_type: EntityText = Field(
        description="Type of pattern: real_work, fake_work, high_quality, low_quality, etc.",
        default=None
    )
    frequency: EntityText = Field(
        description="How often this pattern occurs: consistent, frequent, occasional, rare",
        default=None
    )
    description: EntityText = Field(
        description="Detailed description of the pattern",
        default=None
    )

# ============================================================================
# CUSTOM EDGE TYPES FOR DEVELOPER ANALYSIS
# ============================================================================

class HasStrength(EdgeModel):
    """
    Represents that a developer has a particular strength.
    """
    observed_since: EntityText = Field(
        description="When this strength was first observed",
        default=None
    )
    consistency: EntityText = Field(
        description="How consistently this strength is demonstrated: always, usually, sometimes",
        default=None
    )

class HasWeakness(EdgeModel):
    """
    Represents that a developer has a particular weakness.
    """
    observed_since: EntityText = Field(
        description="When this weakness was first observed",
        default=None
    )
    trend: EntityText = Field(
        description="Whether this weakness is improving, stable, or worsening",
        default=None
    )

class ProducedWork(EdgeModel):
    """
    Represents that a developer produced work summarized by a WorkSummary entity.
    """
    time_period: EntityText = Field(
        description="Time period for this work: last_week, last_month, last_quarter, etc.",
        default=None
    )
    repo_context: EntityText = Field(
        description="Repository or project context for this work",
        default=None
    )

class NeedsImprovement(EdgeModel):
    """
    Represents that a developer needs improvement based on a recommendation.
    """
    urgency: EntityText = Field(
        description="How urgent this improvement is: immediate, soon, eventual",
        default=None
    )
    source: EntityText = Field(
        description="Source of this recommendation: commit_analysis, peer_review, manager_feedback, etc.",
        default=None
    )

class WorksOnRepository(EdgeModel):
    """
    Represents that a developer works on a specific repository.
    """
    role: EntityText = Field(
        description="Developer's role in this repository: owner, contributor, occasional, etc.",
        default=None
    )
    contribution_level: EntityText = Field(
        description="Level of contribution: primary, secondary, minor",
        default=None
    )

class ExhibitsPattern(EdgeModel):
    """
    Represents that a developer exhibits a particular commit pattern.
    """
    repo_specific: EntityBoolean = Field(
        description="Whether this pattern is specific to a repository or general",
        default=None
    )
    time_context: EntityText = Field(
        description="Time context for this pattern observation",
        default=None
    )


class ZepPersonalizer():
    def __init__(self, api_key = None, instruction = None, examples = None):
        self.zep_conn = AsyncZep(
            api_key = os.getenv("ZEP_API_KEY") if not api_key else api_key
        )

        # Project-wide custom ontology for repo-specific analysis
        self.project_ontology = {
            "entities": {
                "DeveloperStrength": DeveloperStrength,
                "DeveloperWeakness": DeveloperWeakness,
                "WorkSummary": WorkSummary,
                "Recommendation": Recommendation,
                "Repository": Repository,
                "CommitPattern": CommitPattern,
            },
            "edges": {
                "HAS_STRENGTH": (
                    HasStrength,
                    [EntityEdgeSourceTarget(source="User", target="DeveloperStrength")]
                ),
                "HAS_WEAKNESS": (
                    HasWeakness,
                    [EntityEdgeSourceTarget(source="User", target="DeveloperWeakness")]
                ),
                "PRODUCED_WORK": (
                    ProducedWork,
                    [EntityEdgeSourceTarget(source="User", target="WorkSummary")]
                ),
                "NEEDS_IMPROVEMENT": (
                    NeedsImprovement,
                    [EntityEdgeSourceTarget(source="User", target="Recommendation")]
                ),
                "WORKS_ON_REPOSITORY": (
                    WorksOnRepository,
                    [EntityEdgeSourceTarget(source="User", target="Repository")]
                ),
                "EXHIBITS_PATTERN": (
                    ExhibitsPattern,
                    [EntityEdgeSourceTarget(source="User", target="CommitPattern")]
                ),
            }
        }

        # Instructions for user summary generation
        self.user_summary_instruction = instruction or """
            Create a comprehensive summary of the developer's profile across all projects.

            Focus on:
            1. **Overall Strengths**: Key technical and soft skills demonstrated consistently
            2. **Overall Weaknesses**: Areas needing improvement across projects
            3. **Work Patterns**: Recurring behaviors, quality trends, and contribution styles
            4. **Primary Expertise**: Main technical areas and departments where the developer excels
            5. **Career Trajectory**: Growth indicators, learning patterns, and potential

            Synthesize information from all repositories to create a holistic view.
            Prioritize patterns that appear across multiple projects over isolated incidents.
            DO NOT CAPTURE ANY PERSONAL INFORMATION OR DATA OUTSIDE ENGINEERING WORK.
        """

        # Instructions for repo-specific graph analysis
        self.repo_summary_instruction = """
            Analyze the developer's contributions to this specific repository.

            Extract and classify:
            - **Strengths**: Specific skills demonstrated in this repo (technical abilities, domain knowledge)
            - **Weaknesses**: Areas of struggle or low-quality work in this repo
            - **Work Summary**: Types of work done (features, bugs, tech debt), departments touched, quality metrics
            - **Recommendations**: Specific actions for improvement or recognition based on this repo's work
            - **Patterns**: Recurring behaviors specific to this repository

            Focus on:
            - Real vs fake work ratio in this repository
            - Department ownership and consistency
            - Commit quality and impact
            - Technical depth vs breadth
            - Collaboration patterns

            Prioritize recurring behaviors over one-off commits.
            DO NOT INFER MOTIVATION OR INTENT NOT PRESENT IN THE DATA.
        """

        self.examples = examples
        self.tasks = deque()
        self.lock = asyncio.Lock()
        self.loop_running = False
        self.ontology_initialized = False

    async def setup_ontology(self, user_ids=None):
        """
        Set up custom ontology for project analysis.
        
        IMPORTANT: In Zep's graph system:
        - You CAN'T set ontology for specific graph_ids that don't exist yet
        - You CAN set ontology project-wide OR for specific user_ids
        - When adding data with graph_id, Zep will use the ontology from:
          1. User-specific ontology (if set for that user_id)
          2. Project-wide ontology (if set)
          3. Default ontology (fallback)
        
        Best practice: Set ontology project-wide ONCE at startup
        """
        try:
            if self.ontology_initialized:
                print("[INFO] Ontology already initialized, skipping")
                return
                
            if user_ids:
                # Set ontology for specific users
                await self.zep_conn.graph.set_ontology(
                    user_ids=user_ids,
                    entities=self.project_ontology["entities"],
                    edges=self.project_ontology["edges"]
                )
                print(f"[INFO] Custom ontology set for users: {user_ids}")
            else:
                # Set ontology project-wide (RECOMMENDED)
                await self.zep_conn.graph.set_ontology(
                    entities=self.project_ontology["entities"],
                    edges=self.project_ontology["edges"]
                )
                print(f"[INFO] Custom ontology set project-wide")
                self.ontology_initialized = True
                
        except Exception as e:
            print(f"[ERROR] Error setting ontology: {e}")
            # Don't fail hard - Zep will use default ontology as fallback

    async def upsert_user(self, user_id, first_name = None, last_name = None, email = None, disable_default_ontology = False):
        """
        Create or update a user in Zep.
        For repo-specific analysis, we may want to disable default ontology.
        """
        try:
            existing = await self.zep_conn.user.get(user_id = user_id)
            print(f"[INFO] User {user_id} already exists")
        except:
            data = {"user_id" : user_id}
            if first_name:
                data['first_name'] = first_name.split()[0] if first_name.split() else first_name
            if last_name:
                data['last_name'] = last_name.split()[0] if last_name.split() else last_name
            if email:
                data['email'] = email
            
            # Option to disable default ontology for more precise control
            if disable_default_ontology:
                data['disable_default_ontology'] = True

            await self.zep_conn.user.add(**data)
            print(f"[INFO] User {user_id} created")

    async def add_message(self, user_id, message, thread_id, first_name = "", last_name = "", repo_name = None, email = None):
        """
        Add a general message to user's graph (not repo-specific).
        This contributes to the general user profile.
        """
        await self.upsert_user(user_id, first_name, last_name, email)

        thread_id = str(thread_id)
        text = message.content
        
        # Add to user's general graph
        # IMPORTANT: Only pass user_id, NOT graph_id
        await self.zep_conn.graph.add(
            user_id=user_id, 
            data=text[:min(len(text), 9999)], 
            type="text", 
            source_description="General developer activity data"
        )

        return {"status" : "success"} 

    async def add_project_message(self, user_id, repo_name, message, first_name = "", last_name = "", email = None):
        """
        Add a repo-specific message to a developer's project graph.
        
        CRITICAL FIX: In Zep, you can ONLY pass either user_id OR graph_id, not both.
        
        For repo-specific graphs:
        - Use graph_id = f"{user_id}_{repo_name}" to create a unique graph per user-repo combination
        - Do NOT pass user_id when using graph_id
        
        Structure:
        - Each user has ONE general graph (user_id only)
        - Each user-repo combination has ONE graph (graph_id = user_id_reponame)
        - The ontology is applied based on project-wide settings
        """
        await self.upsert_user(user_id, first_name, last_name, email)

        text = message.content if hasattr(message, 'content') else str(message)
        
        # Create a unique graph_id for this user-repo combination
        # CRITICAL: Pass ONLY graph_id, not user_id
        graph_id = f"{user_id}_{repo_name}"
        
        try:
            await self.zep_conn.graph.add(
                graph_id=graph_id,  # ✅ ONLY graph_id
                # user_id=user_id,  # ❌ Do NOT pass user_id with graph_id
                data=text[:min(len(text), 9999)],
                type="text",
                source_description=f"Commit data from repository: {repo_name}"
            )
            
            print(f"[INFO] Added project message for user {user_id} in repo {repo_name} (graph: {graph_id})")
            return {"status": "success"}
        except Exception as e:
            print(f"[ERROR] Failed to add project message: {e}")
            return {"status": "error", "message": str(e)}

    async def add_fact(self, user_id, message, first_name = "", last_name = ""):
        """
        Add a fact to the user's general graph.
        """
        await self.upsert_user(user_id, first_name, last_name)

        try:
            fact_text, fact_type = message.fact, message.fact_type
            print('[DEBUG] Adding fact to general graph')
            
            await self.zep_conn.graph.add(
                data = fact_text[:min(len(fact_text), 9999)],
                type= fact_type,
                user_id = user_id  # ✅ Only user_id for general graph
            )

            return {"status" : "success"}

        except Exception as e:
            print(f"[ERROR] Error adding fact: {e}")

    async def get_context(self, user_id, query = None, top_n = 3, repo_name = None):
        """
        Get context from either the general user graph or a repo-specific graph.
        
        Args:
            user_id: The user identifier
            query: Search query
            top_n: Number of results to return
            repo_name: If provided, search the repo-specific graph
        """
        if not query:
            query = "tell me about the developer's work patterns and contributions"
        
        try:
            search_params = {
                "query": query,
                "scope": "nodes"
            }
            
            # If repo_name is provided, search the repo-specific graph
            if repo_name:
                search_params["graph_id"] = f"{user_id}_{repo_name}"
            else:
                search_params["user_id"] = user_id
            
            fact_objs = await self.zep_conn.graph.search(**search_params)
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

    async def get_repo_analysis(self, user_id, repo_name):
        """
        Get comprehensive analysis of a developer's work in a specific repository.
        
        Returns structured data with:
        - Strengths specific to this repo
        - Weaknesses specific to this repo  
        - Work summary for this repo
        - Recommendations based on this repo's work
        """
        try:
            print(f"[DEBUG] Getting repo analysis for user {user_id} in repo {repo_name}")
            
            graph_id = f"{user_id}_{repo_name}"
            
            analysis = {
                "repo_name": repo_name,
                "strengths": [],
                "weaknesses": [],
                "work_summaries": [],
                "recommendations": [],
                "patterns": []
            }
            
            # Search for strengths
            try:
                strength_results = await self.zep_conn.graph.search(
                    graph_id=graph_id,
                    query="developer strengths and skills",
                    scope="nodes",
                    search_filters={"node_labels": ["DeveloperStrength"]},
                    limit=10
                )
                
                for node in strength_results.nodes:
                    analysis["strengths"].append({
                        "name": node.name,
                        "summary": node.summary,
                        "attributes": node.attributes
                    })
            except Exception as e:
                print(f"[DEBUG] No strengths found or error: {e}")
            
            # Search for weaknesses
            try:
                weakness_results = await self.zep_conn.graph.search(
                    graph_id=graph_id,
                    query="developer weaknesses and areas for improvement",
                    scope="nodes",
                    search_filters={"node_labels": ["DeveloperWeakness"]},
                    limit=10
                )
                
                for node in weakness_results.nodes:
                    analysis["weaknesses"].append({
                        "name": node.name,
                        "summary": node.summary,
                        "attributes": node.attributes
                    })
            except Exception as e:
                print(f"[DEBUG] No weaknesses found or error: {e}")
            
            # Search for work summaries
            try:
                work_results = await self.zep_conn.graph.search(
                    graph_id=graph_id,
                    query="work summary and contributions",
                    scope="nodes",
                    search_filters={"node_labels": ["WorkSummary"]},
                    limit=10
                )
                
                for node in work_results.nodes:
                    analysis["work_summaries"].append({
                        "name": node.name,
                        "summary": node.summary,
                        "attributes": node.attributes
                    })
            except Exception as e:
                print(f"[DEBUG] No work summaries found or error: {e}")
            
            # Search for recommendations
            try:
                rec_results = await self.zep_conn.graph.search(
                    graph_id=graph_id,
                    query="recommendations for developer",
                    scope="nodes",
                    search_filters={"node_labels": ["Recommendation"]},
                    limit=10
                )
                
                for node in rec_results.nodes:
                    analysis["recommendations"].append({
                        "name": node.name,
                        "summary": node.summary,
                        "attributes": node.attributes
                    })
            except Exception as e:
                print(f"[DEBUG] No recommendations found or error: {e}")
            
            # Search for patterns
            try:
                pattern_results = await self.zep_conn.graph.search(
                    graph_id=graph_id,
                    query="commit patterns and behaviors",
                    scope="nodes",
                    search_filters={"node_labels": ["CommitPattern"]},
                    limit=10
                )
                
                for node in pattern_results.nodes:
                    analysis["patterns"].append({
                        "name": node.name,
                        "summary": node.summary,
                        "attributes": node.attributes
                    })
            except Exception as e:
                print(f"[DEBUG] No patterns found or error: {e}")
            
            return analysis
            
        except Exception as e:
            print(f"[ERROR] Error getting repo analysis: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def get_user_persona(self, user_id, repo_name=None):
        """
        Get the user persona/summary.
        
        Args:
            user_id: The user identifier
            repo_name: If provided, get the repo-specific summary from that graph
                      If None, get the general user summary
        """
        try:
            print(f"[DEBUG] Getting persona for user_id: {user_id}, repo: {repo_name}")
            
            if repo_name:
                # Get repo-specific analysis instead of persona
                print(f"[INFO] For repo-specific analysis, use get_repo_analysis()")
                return await self.get_repo_analysis(user_id, repo_name)
            
            # Get general user persona
            user_node = await self.zep_conn.user.get_node(user_id=user_id)
            print(f"[DEBUG] User node response: {user_node}")
            
            if user_node and hasattr(user_node, 'node') and user_node.node:
                print(f"[DEBUG] User node summary: {user_node.node.summary}")
                return user_node.node.summary or ""
            else:
                print(f"[DEBUG] No valid node found in response")
                return ""
        except Exception as e:
            print(f"[ERROR] Error getting user persona: {e}")
            import traceback
            traceback.print_exc()
            return ""

    async def get_all_repos_for_user(self, user_id):
        """
        Get list of all repositories a user has worked on.
        This searches for Repository entities connected to the user.
        """
        try:
            repo_results = await self.zep_conn.graph.search(
                user_id=user_id,
                query="repositories the developer works on",
                scope="nodes",
                search_filters={"node_labels": ["Repository"]},
                limit=50
            )
            
            repos = []
            for node in repo_results.nodes:
                repos.append({
                    "name": node.name,
                    "summary": node.summary,
                    "attributes": node.attributes
                })
            
            return repos
        except Exception as e:
            print(f"[ERROR] Error getting repos for user: {e}")
            return []

    async def get_comprehensive_developer_profile(self, user_id):
        """
        Get a comprehensive profile combining:
        1. General user persona
        2. Analysis from all repos the developer has worked on
        """
        try:
            profile = {
                "user_id": user_id,
                "general_summary": await self.get_user_persona(user_id),
                "repositories": []
            }
            
            # Get all repos
            repos = await self.get_all_repos_for_user(user_id)
            
            # Get analysis for each repo
            for repo in repos:
                repo_name = repo["name"]
                repo_analysis = await self.get_repo_analysis(user_id, repo_name)
                if repo_analysis:
                    profile["repositories"].append(repo_analysis)
            
            return profile
        except Exception as e:
            print(f"[ERROR] Error getting comprehensive profile: {e}")
            import traceback
            traceback.print_exc()
            return None