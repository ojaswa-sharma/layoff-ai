import asyncio
import os
import json

from dotenv import load_dotenv
from collections import deque
from dataclasses import dataclass

from zep_cloud.client import AsyncZep
from zep_cloud.types import Message, UserInstruction

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


    async def check_bg(self):
        if not self.loop_running:
            self.loop_running = True
            asyncio.create_task(self.background_task())
            try:
                await self.zep_conn.user.add_user_summary_instructions(
                    instructions=[
                        UserInstruction(
                            name="engineering_focus_and_strengths",
                            text=(
                                "Extract information about the developer's primary engineering focus, "
                                "including dominant departments (ui, frontend, backend, devops), "
                                "types of work they most frequently perform, and areas of technical strength."
                            ),
                        ),
                        UserInstruction(
                            name="contribution_quality_and_impact",
                            text=(
                                "Capture patterns related to the quality and impact of the developer's contributions, "
                                "including frequency of real vs fake work, delivery of major features, "
                                "handling of critical bugs, and tendency toward low-impact or cosmetic changes."
                            ),
                        ),
                        UserInstruction(
                            name="work_style_and_delivery_patterns",
                            text=(
                                "Capture the developer's work style and delivery behavior, such as consistency of output, "
                                "preference for features vs bug fixes vs tech debt, clarity of commits, "
                                "and recurring contribution patterns over time."
                            )
                        )
                    ],
                    user_ids=[]
                )
            except Exception as e:
                print(f"[DEBUG] Error adding user instructions: {e}")
    


    async def background_task(self):
        while self.loop_running:
            curr = None
            async with self.lock:
                if self.tasks:
                    curr = self.tasks.popleft()
                    print(curr)
            if curr:
                if curr.data_type == 'message':
                    try:
                        user_id, thread_id, message, first_name, last_name = curr.decompose()
                        await self.add_message(user_id, message, thread_id, first_name, last_name)
                    except Exception as e:
                        print(f'[DEBUG] Error while processing task: {e}')
                    finally:
                        await asyncio.sleep(0.1)
                elif curr.data_type == 'fact':
                    try:
                        user_id, thread_id, message, first_name, last_name = curr.decompose()
                        await self.add_fact(user_id, message, first_name, last_name)
                    except Exception as e:
                        print(f'[DEBUG] Error while processing fact: {e}')
                    finally:
                        await asyncio.sleep(0.1)
            else:
                await asyncio.sleep(1)


    async def upsert_user(self, user_id, first_name = None, last_name = None, email = None):
        try:
            existing = await self.zep_conn.user.get(user_id = user_id)
        except:
            data = {"user_id" : user_id}
            if first_name:
                data['first_name'] = first_name.split()[0] if first_name.split() else first_name
            if last_name:
                data['last_name'] = last_name.split()[0] if last_name.split() else last_name
            if email:
                data['email'] = email


            await self.zep_conn.user.add(**data)

    async def add_messages(self, user_id, messages, thread_id, first_name = "", last_name = ""):
        await self.upsert_user(user_id, first_name, last_name)

        thread_id = str(thread_id)
        try:
            thread = await self.zep_conn.thread.get(thread_id)
        except:
            thread = None
            
        if not thread:
            await self.zep_conn.thread.create(thread_id=thread_id, user_id=user_id)

        message_list = []
        for message in messages:
            text = message.content[0].get('text') if not isinstance(message, str) else message
            curr = Message(role = str(message.role), content = str(text))
            if message.role == "user":
                message_list.append(curr)

        if message_list:
            await self.zep_conn.thread.add_messages(thread_id=thread_id, messages=message_list)

        return {"status" : "success"}    

    async def add_message(self, user_id, message, thread_id, first_name = "", last_name = "", repo_name = None, email = None):
        await self.upsert_user(user_id, first_name, last_name, email)

        thread_id = str(thread_id)
        try:
            thread = await self.zep_conn.thread.get(thread_id)
            print(f'[DEBUG] Thread : {thread}')
        except:
            thread = None

        if not thread:
            await self.zep_conn.thread.create(thread_id=thread_id, user_id=user_id)

        text = message.content
        curr = Message(role = str(message.role), content = str(text), metadata={
            "repo_name" : repo_name
        })

        # await self.zep_conn.thread.add_messages(thread_id=thread_id, messages=[curr])
        await self.zep_conn.graph.add(user_id=user_id, data = text, type="text", source_description="Data from github summarized by ai")

        return {"status" : "success"} 

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
        await self.check_bg()
        
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

    async def get_context_with_thread(self, user_id, thread_id, query = None):
        """
        V3 MIGRATION: New method using thread.get_user_context
        This is the recommended way to get context in V3 when you have a thread_id
        Returns structured context with user summary and relevant facts
        """
        await self.check_bg()
        
        try:
            # V3 MIGRATION: thread.get_user_context replaces memory.get and provides
            # structured context (no mode parameter needed)
            context = await self.zep_conn.thread.get_user_context(
                thread_id=thread_id,
                query=query  # Optional query to focus context retrieval
            )
            
            return context
        except Exception as e:
            print(f"[ERROR] Error getting thread context: {e}")
            return None


    async def add_task(self, task):
        await self.check_bg()
        async with self.lock:
            self.tasks.append(task)


    async def get_user_persona(self, user_id):
        """
        Get user persona summary from Zep user node.
        
        V3 MIGRATION: user.get_node still works the same way
        
        Args:
            user_id (str): The user ID to get persona for
            
        Returns:
            str: The summary field from the user node, or empty string if not found
        """
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

    async def get_user_threads(self, user_id):
        """
        V3 MIGRATION: New method to get all threads for a user
        Replaces user.get_sessions
        
        Args:
            user_id (str): The user ID to get threads for
            
        Returns:
            list: List of thread objects
        """
        try:
            threads = await self.zep_conn.user.get_threads(user_id=user_id)
            return threads
        except Exception as e:
            print(f"[ERROR] Error getting user threads: {e}")
            return []

    async def delete_thread(self, thread_id):
        """
        V3 MIGRATION: New method to delete a thread
        Replaces memory.delete
        
        Args:
            thread_id (str): The thread ID to delete
        """
        try:
            await self.zep_conn.thread.delete(thread_id=thread_id)
            return {"status": "success"}
        except Exception as e:
            print(f"[ERROR] Error deleting thread: {e}")
            return {"status": "error", "message": str(e)}