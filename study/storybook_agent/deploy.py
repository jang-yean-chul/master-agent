import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dotenv

dotenv.load_dotenv()

import vertexai
import vertexai.agent_engines
from vertexai.preview import reasoning_engines
from storybook_agent.agent import root_agent

PROJECT_ID = "gen-lang-client-0125196626"
LOCATION = "europe-southwest1"
BUCKET = "gs://nico-awesome-weather_agent"

vertexai.init(
    project=PROJECT_ID,
    location=LOCATION,
    staging_bucket=BUCKET,
)

app = reasoning_engines.AdkApp(
    agent=root_agent,
    enable_tracing=True,
)

remote_app = vertexai.agent_engines.create(
    display_name="Storybook Agent",
    agent_engine=app,
    requirements=[
        "google-cloud-aiplatform[adk,agent_engines]",
        "litellm",
        "openai",
        "httpx",
        "pillow",
    ],
    extra_packages=["storybook_agent"],
    env_vars={
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
    },
)
