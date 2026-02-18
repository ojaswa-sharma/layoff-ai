from graphiti_core import Graphiti
from graphiti_core.driver.falkordb_driver import FalkorDriver
from graphiti_core.llm_client import LLMConfig, OpenAIClient
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
import os

graphiti_client = None
_driver = None

def init_graphiti():
    global graphiti_client, _driver
    if graphiti_client:
        return

    api_key = os.getenv("OPENAI_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_KEY is not set")

    _client = OpenAIClient(
        config=LLMConfig(
            api_key=api_key,
            model="gpt-5-nano",
            temperature=1.0,
        )
    )

    _embedder = OpenAIEmbedder(
        config=OpenAIEmbedderConfig(
            api_key=api_key,
            embedding_model="text-embedding-3-small",
        )
    )

    _reranker = OpenAIRerankerClient(
        config=LLMConfig(
            api_key=api_key,
            model="gpt-5-nano",
            temperature=1.0,
        )
    )

    _driver = FalkorDriver(
        host=os.getenv("FALKOR_HOST", "localhost"),
        port=6379,
    )

    graphiti_client = Graphiti(
        graph_driver=_driver,
        llm_client=_client,
        embedder=_embedder,
        cross_encoder=_reranker,
    )

def get_graphiti():
    if not graphiti_client:
        init_graphiti()
    return graphiti_client

def get_driver():
    if not _driver:
        init_graphiti()
    return _driver