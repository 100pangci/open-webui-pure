from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

from authlib.integrations.starlette_client import OAuth

from pydantic import BaseModel

from open_webui.env import (
    DATABASE_URL,
    DATA_DIR,
    ENABLE_ADMIN_CHAT_ACCESS,
    ENABLE_ADMIN_EXPORT,
    ENABLE_DB_MIGRATIONS,
    ENV,
    FRONTEND_BUILD_DIR,
    OPEN_WEBUI_DIR,
    WEBUI_AUTH,
    WEBUI_FAVICON_URL,
    WEBUI_NAME,
    log,
)
from open_webui.models.config import Config


UPLOAD_DIR = DATA_DIR / 'uploads'
CACHE_DIR = DATA_DIR / 'cache'
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)


####################################
# Database migrations
####################################


def run_migrations():
    log.info('Running migrations')
    try:
        from alembic import command
        from alembic.config import Config as AlembicConfig

        alembic_cfg = AlembicConfig(OPEN_WEBUI_DIR / 'alembic.ini')

        migrations_path = OPEN_WEBUI_DIR / 'migrations'
        alembic_cfg.set_main_option('script_location', str(migrations_path))

        command.upgrade(alembic_cfg, 'head')
    except Exception as e:
        log.exception(f'Error running migrations: {e}')
        raise


if ENABLE_DB_MIGRATIONS:
    run_migrations()


####################################
# Static DIR
####################################

STATIC_DIR = Path(os.getenv('STATIC_DIR', OPEN_WEBUI_DIR / 'static')).resolve()

try:
    if STATIC_DIR.exists():
        for item in STATIC_DIR.iterdir():
            if item.is_file() or item.is_symlink():
                try:
                    item.unlink()
                except Exception:
                    pass
except Exception:
    pass

for file_path in (FRONTEND_BUILD_DIR / 'static').glob('**/*'):
    if file_path.is_file():
        target_path = STATIC_DIR / file_path.relative_to(FRONTEND_BUILD_DIR / 'static')
        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copyfile(file_path, target_path)
        except Exception as e:
            logging.error(f'An error occurred copying static assets: {e}')

STORAGE_PROVIDER = 'local'
STORAGE_LOCAL_CACHE = True

BYPASS_ADMIN_ACCESS_CONTROL = os.getenv('BYPASS_ADMIN_ACCESS_CONTROL', 'True').lower() == 'true'
ENABLE_DIRECT_CONNECTIONS = os.getenv('ENABLE_DIRECT_CONNECTIONS', 'False').lower() == 'true'
ENABLE_BASE_MODELS_CACHE = os.getenv('ENABLE_BASE_MODELS_CACHE', 'False').lower() == 'true'

ENABLE_OPENAI_API = os.getenv('ENABLE_OPENAI_API', 'True').lower() == 'true'


OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
OPENAI_API_BASE_URL = os.getenv('OPENAI_API_BASE_URL', '')

if OPENAI_API_BASE_URL == '':
    OPENAI_API_BASE_URL = 'https://api.openai.com/v1'
else:
    if OPENAI_API_BASE_URL.endswith('/'):
        OPENAI_API_BASE_URL = OPENAI_API_BASE_URL[:-1]

OPENAI_API_KEYS = os.getenv('OPENAI_API_KEYS', '')
OPENAI_API_KEYS = OPENAI_API_KEYS if OPENAI_API_KEYS != '' else OPENAI_API_KEY

OPENAI_API_KEYS = [url.strip() for url in OPENAI_API_KEYS.split(';')]
OPENAI_API_KEYS = OPENAI_API_KEYS

OPENAI_API_BASE_URLS = os.getenv('OPENAI_API_BASE_URLS', '')
OPENAI_API_BASE_URLS = OPENAI_API_BASE_URLS if OPENAI_API_BASE_URLS != '' else OPENAI_API_BASE_URL

OPENAI_API_BASE_URLS = [
    url.strip() if url != '' else 'https://api.openai.com/v1' for url in OPENAI_API_BASE_URLS.split(';')
]
OPENAI_API_BASE_URLS = OPENAI_API_BASE_URLS

OPENAI_API_CONFIGS = {}
_openai_api_configs = os.getenv('OPENAI_API_CONFIGS', '')
if _openai_api_configs:
    try:
        parsed = json.loads(_openai_api_configs)
        if isinstance(parsed, dict):
            OPENAI_API_CONFIGS = parsed
        else:
            log.warning('OPENAI_API_CONFIGS must be a JSON object, ignoring')
    except (json.JSONDecodeError, TypeError):
        log.warning('OPENAI_API_CONFIGS is not valid JSON, ignoring')

# Get the actual OpenAI API key based on the base URL
OPENAI_API_KEY = ''
try:
    OPENAI_API_KEY = OPENAI_API_KEYS[OPENAI_API_BASE_URLS.index('https://api.openai.com/v1')]
except Exception:
    pass
OPENAI_API_BASE_URL = 'https://api.openai.com/v1'


####################################


####################################
# WEBUI
####################################


WEBUI_URL = os.getenv('WEBUI_URL', '')


ENABLE_SIGNUP = False if not WEBUI_AUTH else os.getenv('ENABLE_SIGNUP', 'True').lower() == 'true'

ENABLE_LOGIN_FORM = os.getenv('ENABLE_LOGIN_FORM', 'True').lower() == 'true'

ENABLE_PASSWORD_CHANGE_FORM = os.getenv('ENABLE_PASSWORD_CHANGE_FORM', 'True').lower() == 'true'

ENABLE_PASSWORD_AUTH = os.getenv('ENABLE_PASSWORD_AUTH', 'True').lower() == 'true'

DEFAULT_LOCALE = os.getenv('DEFAULT_LOCALE', '')

DEFAULT_MODELS = os.getenv('DEFAULT_MODELS', None)

DEFAULT_PINNED_MODELS = os.getenv('DEFAULT_PINNED_MODELS', None)

try:
    default_prompt_suggestions = json.loads(os.getenv('DEFAULT_PROMPT_SUGGESTIONS', '[]'))
except Exception as e:
    log.exception(f'Error loading DEFAULT_PROMPT_SUGGESTIONS: {e}')
    default_prompt_suggestions = []
if default_prompt_suggestions == []:
    default_prompt_suggestions = [
        {
            'title': ['Help me study', 'vocabulary for a college entrance exam'],
            'content': "Help me study vocabulary: write a sentence for me to fill in the blank, and I'll try to pick the correct option.",
        },
        {
            'title': ['Give me ideas', "for what to do with my kids' art"],
            'content': "What are 5 creative things I could do with my kids' art? I don't want to throw them away, but it's also so much clutter.",
        },
        {
            'title': ['Tell me a fun fact', 'about the Roman Empire'],
            'content': 'Tell me a random fun fact about the Roman Empire',
        },
        {
            'title': ['Show me a code snippet', "of a website's sticky header"],
            'content': "Show me a code snippet of a website's sticky header in CSS and JavaScript.",
        },
        {
            'title': [
                'Explain options trading',
                "if I'm familiar with buying and selling stocks",
            ],
            'content': "Explain options trading in simple terms if I'm familiar with buying and selling stocks.",
        },
        {
            'title': ['Overcome procrastination', 'give me tips'],
            'content': 'Could you start by asking me about instances when I procrastinate the most and then give me some suggestions to overcome it?',
        },
    ]

DEFAULT_PROMPT_SUGGESTIONS = default_prompt_suggestions

try:
    model_order_list = json.loads(os.getenv('MODEL_ORDER_LIST', '[]'))
except Exception as e:
    log.exception(f'Error loading MODEL_ORDER_LIST: {e}')
    model_order_list = []

MODEL_ORDER_LIST = model_order_list

try:
    default_model_metadata = json.loads(os.getenv('DEFAULT_MODEL_METADATA', '{}'))
except Exception as e:
    log.exception(f'Error loading DEFAULT_MODEL_METADATA: {e}')
    default_model_metadata = {}

DEFAULT_MODEL_METADATA = default_model_metadata

try:
    default_model_params = json.loads(os.getenv('DEFAULT_MODEL_PARAMS', '{}'))
except Exception as e:
    log.exception(f'Error loading DEFAULT_MODEL_PARAMS: {e}')
    default_model_params = {}

DEFAULT_MODEL_PARAMS = default_model_params


try:
    default_interface_settings = json.loads(os.getenv('DEFAULT_INTERFACE_SETTINGS', '{}'))
except Exception as e:
    log.exception(f'Error loading DEFAULT_INTERFACE_SETTINGS: {e}')
    default_interface_settings = {}

DEFAULT_INTERFACE_SETTINGS = default_interface_settings if isinstance(default_interface_settings, dict) else {}

DEFAULT_USER_ROLE = os.getenv('DEFAULT_USER_ROLE', 'pending')

DEFAULT_GROUP_ID = os.getenv('DEFAULT_GROUP_ID', '')

PENDING_USER_OVERLAY_TITLE = os.getenv('PENDING_USER_OVERLAY_TITLE', '')

PENDING_USER_OVERLAY_CONTENT = os.getenv('PENDING_USER_OVERLAY_CONTENT', '')


RESPONSE_WATERMARK = os.getenv('RESPONSE_WATERMARK', '')

IFRAME_CSP = os.getenv('IFRAME_CSP', '')


####################################
# USER PERMISSIONS
####################################

USER_PERMISSIONS_WORKSPACE_MODELS_ACCESS = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_MODELS_ACCESS', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_PROMPTS_ACCESS = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_PROMPTS_ACCESS', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_MODELS_IMPORT = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_MODELS_IMPORT', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_MODELS_EXPORT = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_MODELS_EXPORT', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_PROMPTS_IMPORT = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_PROMPTS_IMPORT', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_PROMPTS_EXPORT = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_PROMPTS_EXPORT', 'False').lower() == 'true'
)


USER_PERMISSIONS_WORKSPACE_MODELS_ALLOW_SHARING = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_MODELS_ALLOW_SHARING', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_MODELS_ALLOW_PUBLIC_SHARING = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_MODELS_ALLOW_PUBLIC_SHARING', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_PROMPTS_ALLOW_SHARING = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_PROMPTS_ALLOW_SHARING', 'False').lower() == 'true'
)

USER_PERMISSIONS_WORKSPACE_PROMPTS_ALLOW_PUBLIC_SHARING = (
    os.getenv('USER_PERMISSIONS_WORKSPACE_PROMPTS_ALLOW_PUBLIC_SHARING', 'False').lower() == 'true'
)


USER_PERMISSIONS_FOLDERS_ALLOW_SHARING = os.getenv('USER_PERMISSIONS_FOLDERS_ALLOW_SHARING', 'False').lower() == 'true'


USER_PERMISSIONS_ACCESS_GRANTS_ALLOW_USERS = (
    os.getenv('USER_PERMISSIONS_ACCESS_GRANTS_ALLOW_USERS', 'True').lower() == 'true'
)
USER_PERMISSIONS_ACCESS_GRANTS_ALLOW_GROUPS = (
    os.getenv('USER_PERMISSIONS_ACCESS_GRANTS_ALLOW_GROUPS', 'True').lower() == 'true'
)


USER_PERMISSIONS_CHAT_CONTROLS = os.getenv('USER_PERMISSIONS_CHAT_CONTROLS', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_SYSTEM_PROMPT = os.getenv('USER_PERMISSIONS_CHAT_SYSTEM_PROMPT', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_PARAMS = os.getenv('USER_PERMISSIONS_CHAT_PARAMS', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_FILE_UPLOAD = os.getenv('USER_PERMISSIONS_CHAT_FILE_UPLOAD', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_DELETE = os.getenv('USER_PERMISSIONS_CHAT_DELETE', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_DELETE_MESSAGE = os.getenv('USER_PERMISSIONS_CHAT_DELETE_MESSAGE', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_CONTINUE_RESPONSE = os.getenv('USER_PERMISSIONS_CHAT_CONTINUE_RESPONSE', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_REGENERATE_RESPONSE = (
    os.getenv('USER_PERMISSIONS_CHAT_REGENERATE_RESPONSE', 'True').lower() == 'true'
)

USER_PERMISSIONS_CHAT_EDIT = os.getenv('USER_PERMISSIONS_CHAT_EDIT', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_SHARE = os.getenv('USER_PERMISSIONS_CHAT_SHARE', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_ALLOW_PUBLIC_SHARING = (
    os.getenv('USER_PERMISSIONS_CHAT_ALLOW_PUBLIC_SHARING', 'False').lower() == 'true'
)

USER_PERMISSIONS_CHAT_ALLOW_OPEN_SHARING = (
    os.getenv('USER_PERMISSIONS_CHAT_ALLOW_OPEN_SHARING', 'False').lower() == 'true'
)

USER_PERMISSIONS_CHAT_EXPORT = os.getenv('USER_PERMISSIONS_CHAT_EXPORT', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_IMPORT = os.getenv('USER_PERMISSIONS_CHAT_IMPORT', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_MULTIPLE_MODELS = os.getenv('USER_PERMISSIONS_CHAT_MULTIPLE_MODELS', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_TEMPORARY = os.getenv('USER_PERMISSIONS_CHAT_TEMPORARY', 'True').lower() == 'true'

USER_PERMISSIONS_CHAT_TEMPORARY_ENFORCED = (
    os.getenv('USER_PERMISSIONS_CHAT_TEMPORARY_ENFORCED', 'False').lower() == 'true'
)


USER_PERMISSIONS_FEATURES_IMAGE_GENERATION = (
    os.getenv('USER_PERMISSIONS_FEATURES_IMAGE_GENERATION', 'True').lower() == 'true'
)

USER_PERMISSIONS_FEATURES_FOLDERS = os.getenv('USER_PERMISSIONS_FEATURES_FOLDERS', 'True').lower() == 'true'

USER_PERMISSIONS_FEATURES_API_KEYS = os.getenv('USER_PERMISSIONS_FEATURES_API_KEYS', 'False').lower() == 'true'

USER_PERMISSIONS_SETTINGS_INTERFACE = os.getenv('USER_PERMISSIONS_SETTINGS_INTERFACE', 'True').lower() == 'true'


DEFAULT_USER_PERMISSIONS = {
    'workspace': {
        'models': USER_PERMISSIONS_WORKSPACE_MODELS_ACCESS,
        'prompts': USER_PERMISSIONS_WORKSPACE_PROMPTS_ACCESS,
        'models_import': USER_PERMISSIONS_WORKSPACE_MODELS_IMPORT,
        'models_export': USER_PERMISSIONS_WORKSPACE_MODELS_EXPORT,
        'prompts_import': USER_PERMISSIONS_WORKSPACE_PROMPTS_IMPORT,
        'prompts_export': USER_PERMISSIONS_WORKSPACE_PROMPTS_EXPORT,
    },
    'sharing': {
        'models': USER_PERMISSIONS_WORKSPACE_MODELS_ALLOW_SHARING,
        'public_models': USER_PERMISSIONS_WORKSPACE_MODELS_ALLOW_PUBLIC_SHARING,
        'prompts': USER_PERMISSIONS_WORKSPACE_PROMPTS_ALLOW_SHARING,
        'public_prompts': USER_PERMISSIONS_WORKSPACE_PROMPTS_ALLOW_PUBLIC_SHARING,
        'folders': USER_PERMISSIONS_FOLDERS_ALLOW_SHARING,
        'public_chats': USER_PERMISSIONS_CHAT_ALLOW_PUBLIC_SHARING,
        'open_chats': USER_PERMISSIONS_CHAT_ALLOW_OPEN_SHARING,
    },
    'access_grants': {
        'allow_users': USER_PERMISSIONS_ACCESS_GRANTS_ALLOW_USERS,
        'allow_groups': USER_PERMISSIONS_ACCESS_GRANTS_ALLOW_GROUPS,
    },
    'chat': {
        'controls': USER_PERMISSIONS_CHAT_CONTROLS,
        'system_prompt': USER_PERMISSIONS_CHAT_SYSTEM_PROMPT,
        'params': USER_PERMISSIONS_CHAT_PARAMS,
        'file_upload': USER_PERMISSIONS_CHAT_FILE_UPLOAD,
        'delete': USER_PERMISSIONS_CHAT_DELETE,
        'delete_message': USER_PERMISSIONS_CHAT_DELETE_MESSAGE,
        'continue_response': USER_PERMISSIONS_CHAT_CONTINUE_RESPONSE,
        'regenerate_response': USER_PERMISSIONS_CHAT_REGENERATE_RESPONSE,
        'edit': USER_PERMISSIONS_CHAT_EDIT,
        'share': USER_PERMISSIONS_CHAT_SHARE,
        'export': USER_PERMISSIONS_CHAT_EXPORT,
        'import': USER_PERMISSIONS_CHAT_IMPORT,
        'multiple_models': USER_PERMISSIONS_CHAT_MULTIPLE_MODELS,
        'temporary': USER_PERMISSIONS_CHAT_TEMPORARY,
        'temporary_enforced': USER_PERMISSIONS_CHAT_TEMPORARY_ENFORCED,
    },
    'features': {
        'api_keys': USER_PERMISSIONS_FEATURES_API_KEYS,
        'folders': USER_PERMISSIONS_FEATURES_FOLDERS,
        'image_generation': USER_PERMISSIONS_FEATURES_IMAGE_GENERATION,
    },
    'settings': {
        'interface': USER_PERMISSIONS_SETTINGS_INTERFACE,
    },
}

USER_PERMISSIONS = DEFAULT_USER_PERMISSIONS

ENABLE_FOLDERS = os.getenv('ENABLE_FOLDERS', 'True').lower() == 'true'

FOLDER_MAX_FILE_COUNT = os.getenv('FOLDER_MAX_FILE_COUNT', '')

ENABLE_USER_STATUS = os.getenv('ENABLE_USER_STATUS', 'True').lower() == 'true'


####################################
# ADMIN
####################################

ENABLE_COMMUNITY_SHARING = os.getenv('ENABLE_COMMUNITY_SHARING', 'True').lower() == 'true'

THREAD_POOL_SIZE = os.getenv('THREAD_POOL_SIZE', None)
THREAD_POOL_THREAD_NAME_PREFIX = os.getenv('THREAD_POOL_THREAD_NAME_PREFIX', '')

if THREAD_POOL_SIZE is not None and isinstance(THREAD_POOL_SIZE, str):
    try:
        THREAD_POOL_SIZE = int(THREAD_POOL_SIZE)
    except ValueError:
        log.warning(f'THREAD_POOL_SIZE is not a valid integer: {THREAD_POOL_SIZE}. Defaulting to None.')
        THREAD_POOL_SIZE = None


def validate_cors_origin(origin):
    parsed_url = urlparse(origin)

    # Check if the scheme is either http or https, or a custom scheme
    schemes = ['http', 'https'] + CORS_ALLOW_CUSTOM_SCHEME
    if parsed_url.scheme not in schemes:
        raise ValueError(
            f"Invalid scheme in CORS_ALLOW_ORIGIN: '{origin}'. Only 'http' and 'https' and CORS_ALLOW_CUSTOM_SCHEME are allowed."
        )

    # Ensure that the netloc (domain + port) is present, indicating it's a valid URL
    if not parsed_url.netloc:
        raise ValueError(f"Invalid URL structure in CORS_ALLOW_ORIGIN: '{origin}'.")


# For production, you should only need one host as
# fastapi serves the svelte-kit built frontend and backend from the same host and port.
# To test CORS_ALLOW_ORIGIN locally, you can set something like
# CORS_ALLOW_ORIGIN=http://localhost:5173;http://localhost:8080
# in your .env file depending on your frontend port, 5173 in this case.
CORS_ALLOW_ORIGIN = os.getenv('CORS_ALLOW_ORIGIN', '*').split(';')

# Allows custom URL schemes (e.g., app://) to be used as origins for CORS.
# Useful for local development or desktop clients with schemes like app:// or other custom protocols.
# Provide a semicolon-separated list of allowed schemes in the environment variable CORS_ALLOW_CUSTOM_SCHEMES.
CORS_ALLOW_CUSTOM_SCHEME = os.getenv('CORS_ALLOW_CUSTOM_SCHEME', '').split(';')

if CORS_ALLOW_ORIGIN == ['*']:
    log.warning("\n\nWARNING: CORS_ALLOW_ORIGIN IS SET TO '*' - NOT RECOMMENDED FOR PRODUCTION DEPLOYMENTS.\n")
else:
    # You have to pick between a single wildcard or a list of origins.
    # Doing both will result in CORS errors in the browser.
    for origin in CORS_ALLOW_ORIGIN:
        validate_cors_origin(origin)



class BannerModel(BaseModel):
    id: str
    type: str
    title: str | None = None
    content: str
    dismissible: bool
    timestamp: int


try:
    banners = json.loads(os.getenv('WEBUI_BANNERS', '[]'))
    banners = [BannerModel(**banner) for banner in banners]
except Exception as e:
    log.exception(f'Error loading WEBUI_BANNERS: {e}')
    banners = []

WEBUI_BANNERS = banners


SHOW_ADMIN_DETAILS = os.getenv('SHOW_ADMIN_DETAILS', 'true').lower() == 'true'

ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', None)



####################################
# TASKS
####################################


TASK_MODEL = os.getenv('TASK_MODEL', '')

TASK_MODEL_EXTERNAL = os.getenv('TASK_MODEL_EXTERNAL', '')

try:
    task_model_params = json.loads(os.getenv('TASK_MODEL_PARAMS', '{}'))
except Exception as e:
    log.exception(f'Error loading TASK_MODEL_PARAMS: {e}')
    task_model_params = {}

TASK_MODEL_PARAMS = task_model_params

CONTEXT_COMPACTION_MODEL = os.getenv('CONTEXT_COMPACTION_MODEL', '')

ENABLE_CONTEXT_COMPACTION = os.getenv('ENABLE_CONTEXT_COMPACTION', 'False').lower() == 'true'


CONTEXT_COMPACTION_TOKEN_THRESHOLD = int(os.getenv('CONTEXT_COMPACTION_TOKEN_THRESHOLD', '80000'))

_CONTEXT_COMPACTION_TOKEN_CAP = os.getenv('CONTEXT_COMPACTION_TOKEN_CAP')
CONTEXT_COMPACTION_TOKEN_CAP = int(_CONTEXT_COMPACTION_TOKEN_CAP) if _CONTEXT_COMPACTION_TOKEN_CAP else None

CONTEXT_COMPACTION_RETENTION_PERCENTAGE = min(
    50, max(10, int(os.getenv('CONTEXT_COMPACTION_RETENTION_PERCENTAGE', '40')))
)

CONTEXT_COMPACTION_PROMPT_TEMPLATE = os.getenv('CONTEXT_COMPACTION_PROMPT_TEMPLATE', '')

TITLE_GENERATION_PROMPT_TEMPLATE = os.getenv('TITLE_GENERATION_PROMPT_TEMPLATE', '')

DEFAULT_TITLE_GENERATION_PROMPT_TEMPLATE = """### Task:
Generate a concise title summarizing the chat history.
### Guidelines:
- The title should clearly represent the main theme or subject of the conversation.
- Keep it short: 2-4 words is best.
- Do not use emojis, quotation marks, or special formatting.
- Write the title in the chat's primary language; default to English if multilingual.
- Prioritize accuracy over creativity.
- Your entire response must consist solely of the JSON object, without any introductory or concluding text.
- The output must be a single, raw JSON object, without any markdown code fences or other encapsulating text.
- Ensure no conversational text, affirmations, or explanations precede or follow the raw JSON output, as this will cause direct parsing failure.
### Output:
JSON format: { "title": "your concise title here" }
### Examples:
- { "title": "Stock Trends" },
- { "title": "Chocolate Chip Cookies" },
- { "title": "Music Streaming" },
- { "title": "Remote Work" }
### Chat History:
<chat_history>
{{MESSAGES:END:2}}
</chat_history>"""

TAGS_GENERATION_PROMPT_TEMPLATE = os.getenv('TAGS_GENERATION_PROMPT_TEMPLATE', '')

DEFAULT_TAGS_GENERATION_PROMPT_TEMPLATE = """### Task:
Generate 1-3 broad tags categorizing the main themes of the chat history, along with 1-3 more specific subtopic tags.

### Guidelines:
- Start with high-level domains (e.g. Science, Technology, Philosophy, Arts, Politics, Business, Health, Sports, Entertainment, Education)
- Consider including relevant subfields/subdomains if they are strongly represented throughout the conversation
- If content is too short (less than 3 messages) or too diverse, use only ["General"]
- Use the chat's primary language; default to English if multilingual
- Prioritize accuracy over specificity

### Output:
JSON format: { "tags": ["tag1", "tag2", "tag3"] }

### Chat History:
<chat_history>
{{MESSAGES:END:6}}
</chat_history>"""

IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE = os.getenv('IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE', '')

DEFAULT_IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE = """### Task:
Generate a detailed prompt for am image generation task based on the given language and context. Describe the image as if you were explaining it to someone who cannot see it. Include relevant details, colors, shapes, and any other important elements.

### Guidelines:
- Be descriptive and detailed, focusing on the most important aspects of the image.
- Avoid making assumptions or adding information not present in the image.
- Use the chat's primary language; default to English if multilingual.
- If the image is too complex, focus on the most prominent elements.

### Output:
Strictly return in JSON format:
{
    "prompt": "Your detailed description here."
}

### Chat History:
<chat_history>
{{MESSAGES:END:6}}
</chat_history>"""


FOLLOW_UP_GENERATION_PROMPT_TEMPLATE = os.getenv('FOLLOW_UP_GENERATION_PROMPT_TEMPLATE', '')

DEFAULT_FOLLOW_UP_GENERATION_PROMPT_TEMPLATE = """### Task:
Suggest 3-5 relevant follow-up questions or prompts that the user might naturally ask next in this conversation as a **user**, based on the chat history, to help continue or deepen the discussion.
### Guidelines:
- Write all follow-up questions from the user’s point of view, directed to the assistant.
- Make questions concise, clear, and directly related to the discussed topic(s).
- Only suggest follow-ups that make sense given the chat content and do not repeat what was already covered.
- If the conversation is very short or not specific, suggest more general (but relevant) follow-ups the user might ask.
- Use the conversation's primary language; default to English if multilingual.
- Response must be a JSON object with a "follow_ups" key containing an array of strings, no extra text or formatting.
### Output:
JSON format: { "follow_ups": ["Question 1?", "Question 2?", "Question 3?"] }
### Chat History:
<chat_history>
{{MESSAGES:END:6}}
</chat_history>"""

ENABLE_FOLLOW_UP_GENERATION = os.getenv('ENABLE_FOLLOW_UP_GENERATION', 'True').lower() == 'true'

ENABLE_TAGS_GENERATION = os.getenv('ENABLE_TAGS_GENERATION', 'True').lower() == 'true'

ENABLE_TITLE_GENERATION = os.getenv('ENABLE_TITLE_GENERATION', 'True').lower() == 'true'


ENABLE_AUTOCOMPLETE_GENERATION = os.getenv('ENABLE_AUTOCOMPLETE_GENERATION', 'False').lower() == 'true'

AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH = int(os.getenv('AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH', '-1'))

AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE = os.getenv('AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE', '')


DEFAULT_AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE = """### Task:
You are an autocompletion system. Continue the text in `<text>` based on the **completion type** in `<type>` and the given language.  

### **Instructions**:
1. Analyze `<text>` for context and meaning.  
2. Use `<type>` to guide your output:  
   - **General**: Provide a natural, concise continuation.  
   - **Search Query**: Complete as if generating a realistic search query.  
3. Start as if you are directly continuing `<text>`. Do **not** repeat, paraphrase, or respond as a model. Simply complete the text.  
4. Ensure the continuation:
   - Flows naturally from `<text>`.  
   - Avoids repetition, overexplaining, or unrelated ideas.  
5. If unsure, return: `{ "text": "" }`.  

### **Output Rules**:
- Respond only in JSON format: `{ "text": "<your_completion>" }`.

### **Examples**:
#### Example 1:  
Input:  
<type>General</type>  
<text>The sun was setting over the horizon, painting the sky</text>  
Output:  
{ "text": "with vibrant shades of orange and pink." }

#### Example 2:  
Input:  
<type>Search Query</type>  
<text>Top-rated restaurants in</text>  
Output:  
{ "text": "New York City for Italian cuisine." }  

---
### Context:
<chat_history>
{{MESSAGES:END:6}}
</chat_history>
<type>{{TYPE}}</type>  
<text>{{PROMPT}}</text>  
#### Output:
"""


DEFAULT_MOA_GENERATION_PROMPT_TEMPLATE = """You have been provided with a set of responses from various models to the latest user query: "{{prompt}}"

Your task is to synthesize these responses into a single, high-quality response. It is crucial to critically evaluate the information provided in these responses, recognizing that some of it may be biased or incorrect. Your response should not simply replicate the given answers but should offer a refined, accurate, and comprehensive reply to the instruction. Ensure your response is well-structured, coherent, and adheres to the highest standards of accuracy and reliability.

Responses from models: {{responses}}"""



####################################
# Auth
####################################

ENABLE_API_KEYS = os.getenv('ENABLE_API_KEYS', 'False').lower() == 'true'

ENABLE_API_KEYS_ENDPOINT_RESTRICTIONS = (
    os.getenv(
        'ENABLE_API_KEYS_ENDPOINT_RESTRICTIONS',
        os.getenv('ENABLE_API_KEY_ENDPOINT_RESTRICTIONS', 'False'),
    ).lower()
    == 'true'
)

API_KEYS_ALLOWED_ENDPOINTS = os.getenv('API_KEYS_ALLOWED_ENDPOINTS', os.getenv('API_KEY_ALLOWED_ENDPOINTS', ''))

JWT_EXPIRES_IN = os.getenv('JWT_EXPIRES_IN', '4w')

if JWT_EXPIRES_IN == '-1':
    log.warning(
        "⚠️  SECURITY WARNING: JWT_EXPIRES_IN is set to '-1'\n"
        '    See: https://docs.openwebui.com/reference/env-configuration\n'
    )


OAUTH_CLIENT_TIMEOUT = os.getenv('OAUTH_CLIENT_TIMEOUT', '')


####################################
# OAuth config
####################################

# Master switch for OAuth/OIDC sign-in. Defaults to enabled so existing
# deployments that already have a provider configured keep working; admins can
# turn it off to disable OAuth login without clearing their provider settings.
ENABLE_OAUTH = os.getenv('ENABLE_OAUTH', 'True').lower() == 'true'

ENABLE_OAUTH_SIGNUP = os.getenv('ENABLE_OAUTH_SIGNUP', 'False').lower() == 'true'

OAUTH_AUTO_REDIRECT = os.getenv('OAUTH_AUTO_REDIRECT', 'False').lower() == 'true'

OAUTH_REFRESH_TOKEN_INCLUDE_SCOPE = os.getenv('OAUTH_REFRESH_TOKEN_INCLUDE_SCOPE', 'False').lower() == 'true'


OAUTH_MERGE_ACCOUNTS_BY_EMAIL = os.getenv('OAUTH_MERGE_ACCOUNTS_BY_EMAIL', 'False').lower() == 'true'

OAUTH_PROVIDERS = {}

GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', '')

GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', '')


GOOGLE_OAUTH_SCOPE = os.getenv('GOOGLE_OAUTH_SCOPE', 'openid email profile')

GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', '')

GOOGLE_OAUTH_AUTHORIZE_PARAMS = {}
_google_oauth_authorize_params = os.getenv('GOOGLE_OAUTH_AUTHORIZE_PARAMS', '')
if _google_oauth_authorize_params:
    try:
        _parsed = json.loads(_google_oauth_authorize_params)
        if isinstance(_parsed, dict):
            GOOGLE_OAUTH_AUTHORIZE_PARAMS = _parsed
        else:
            log.warning('GOOGLE_OAUTH_AUTHORIZE_PARAMS must be a JSON object, ignoring')
    except (json.JSONDecodeError, TypeError):
        log.warning('GOOGLE_OAUTH_AUTHORIZE_PARAMS is not valid JSON, ignoring')

MICROSOFT_CLIENT_ID = os.getenv('MICROSOFT_CLIENT_ID', '')

MICROSOFT_CLIENT_SECRET = os.getenv('MICROSOFT_CLIENT_SECRET', '')

MICROSOFT_CLIENT_TENANT_ID = os.getenv('MICROSOFT_CLIENT_TENANT_ID', '')

MICROSOFT_CLIENT_LOGIN_BASE_URL = os.getenv('MICROSOFT_CLIENT_LOGIN_BASE_URL', 'https://login.microsoftonline.com')

MICROSOFT_CLIENT_PICTURE_URL = os.getenv(
    'MICROSOFT_CLIENT_PICTURE_URL',
    'https://graph.microsoft.com/v1.0/me/photo/$value',
)


MICROSOFT_OAUTH_SCOPE = os.getenv('MICROSOFT_OAUTH_SCOPE', 'openid email profile')

MICROSOFT_REDIRECT_URI = os.getenv('MICROSOFT_REDIRECT_URI', '')

GITHUB_CLIENT_ID = os.getenv('GITHUB_CLIENT_ID', '')

GITHUB_CLIENT_SECRET = os.getenv('GITHUB_CLIENT_SECRET', '')

GITHUB_CLIENT_SCOPE = os.getenv('GITHUB_CLIENT_SCOPE', 'user:email')

GITHUB_CLIENT_REDIRECT_URI = os.getenv('GITHUB_CLIENT_REDIRECT_URI', '')

OAUTH_CLIENT_ID = os.getenv('OAUTH_CLIENT_ID', '')

OAUTH_CLIENT_SECRET = os.getenv('OAUTH_CLIENT_SECRET', '')

OPENID_PROVIDER_URL = os.getenv('OPENID_PROVIDER_URL', '')

OPENID_END_SESSION_ENDPOINT = os.getenv('OPENID_END_SESSION_ENDPOINT', '')

OPENID_REDIRECT_URI = os.getenv('OPENID_REDIRECT_URI', '')

OAUTH_SCOPES = os.getenv('OAUTH_SCOPES', 'openid email profile')

OAUTH_TIMEOUT = os.getenv('OAUTH_TIMEOUT', '')

OAUTH_TOKEN_ENDPOINT_AUTH_METHOD = os.getenv('OAUTH_TOKEN_ENDPOINT_AUTH_METHOD', None)

OAUTH_CODE_CHALLENGE_METHOD = os.getenv('OAUTH_CODE_CHALLENGE_METHOD', None)

OAUTH_PROVIDER_NAME = os.getenv('OAUTH_PROVIDER_NAME', 'SSO')

OAUTH_SUB_CLAIM = os.getenv('OAUTH_SUB_CLAIM', None)

OAUTH_USERNAME_CLAIM = os.getenv('OAUTH_USERNAME_CLAIM', 'name')


OAUTH_PICTURE_CLAIM = os.getenv('OAUTH_PICTURE_CLAIM', 'picture')

OAUTH_EMAIL_CLAIM = os.getenv('OAUTH_EMAIL_CLAIM', 'email')

OAUTH_GROUPS_CLAIM = os.getenv('OAUTH_GROUPS_CLAIM', os.getenv('OAUTH_GROUP_CLAIM', 'groups'))

FEISHU_CLIENT_ID = os.getenv('FEISHU_CLIENT_ID', '')

FEISHU_CLIENT_SECRET = os.getenv('FEISHU_CLIENT_SECRET', '')

FEISHU_OAUTH_SCOPE = os.getenv('FEISHU_OAUTH_SCOPE', 'contact:user.base:readonly')

FEISHU_REDIRECT_URI = os.getenv('FEISHU_REDIRECT_URI', '')

ENABLE_OAUTH_ROLE_MANAGEMENT = os.getenv('ENABLE_OAUTH_ROLE_MANAGEMENT', 'False').lower() == 'true'

ENABLE_OAUTH_GROUP_MANAGEMENT = os.getenv('ENABLE_OAUTH_GROUP_MANAGEMENT', 'False').lower() == 'true'

ENABLE_OAUTH_GROUP_CREATION = os.getenv('ENABLE_OAUTH_GROUP_CREATION', 'False').lower() == 'true'


oauth_group_default_share = os.getenv('OAUTH_GROUP_DEFAULT_SHARE', 'true').strip().lower()
OAUTH_GROUP_DEFAULT_SHARE = 'members' if oauth_group_default_share == 'members' else oauth_group_default_share == 'true'


OAUTH_BLOCKED_GROUPS = os.getenv('OAUTH_BLOCKED_GROUPS', '[]')

OAUTH_GROUPS_SEPARATOR = os.getenv('OAUTH_GROUPS_SEPARATOR', ';')

OAUTH_ROLES_CLAIM = os.getenv('OAUTH_ROLES_CLAIM', 'roles')

OAUTH_ROLES_SEPARATOR = os.getenv('OAUTH_ROLES_SEPARATOR', ',')

OAUTH_ALLOWED_ROLES = [
    role.strip()
    for role in os.getenv('OAUTH_ALLOWED_ROLES', f'user{OAUTH_ROLES_SEPARATOR}admin').split(OAUTH_ROLES_SEPARATOR)
    if role
]

OAUTH_ADMIN_ROLES = [
    role.strip() for role in os.getenv('OAUTH_ADMIN_ROLES', 'admin').split(OAUTH_ROLES_SEPARATOR) if role
]

OAUTH_ALLOWED_DOMAINS = [domain.strip() for domain in os.getenv('OAUTH_ALLOWED_DOMAINS', '*').split(',')]

OAUTH_UPDATE_PICTURE_ON_LOGIN = os.getenv('OAUTH_UPDATE_PICTURE_ON_LOGIN', 'False').lower() == 'true'

OAUTH_UPDATE_NAME_ON_LOGIN = os.getenv('OAUTH_UPDATE_NAME_ON_LOGIN', 'False').lower() == 'true'

OAUTH_UPDATE_EMAIL_ON_LOGIN = os.getenv('OAUTH_UPDATE_EMAIL_ON_LOGIN', 'False').lower() == 'true'

OAUTH_ACCESS_TOKEN_REQUEST_INCLUDE_CLIENT_ID = (
    os.getenv('OAUTH_ACCESS_TOKEN_REQUEST_INCLUDE_CLIENT_ID', 'False').lower() == 'true'
)

OAUTH_AUDIENCE = os.getenv('OAUTH_AUDIENCE', '')

OAUTH_AUTHORIZE_PARAMS = {}
_oauth_authorize_params = os.getenv('OAUTH_AUTHORIZE_PARAMS', '')
if _oauth_authorize_params:
    try:
        _parsed = json.loads(_oauth_authorize_params)
        if isinstance(_parsed, dict):
            OAUTH_AUTHORIZE_PARAMS = _parsed
        else:
            log.warning('OAUTH_AUTHORIZE_PARAMS must be a JSON object, ignoring')
    except (json.JSONDecodeError, TypeError):
        log.warning('OAUTH_AUTHORIZE_PARAMS is not valid JSON, ignoring')


def oauth_client_kwargs(scope: str, **kwargs):
    client_kwargs = {
        'scope': scope,
        **kwargs,
        **({'timeout': int(OAUTH_TIMEOUT)} if OAUTH_TIMEOUT else {}),
    }

    if OAUTH_CODE_CHALLENGE_METHOD == 'S256':
        client_kwargs['code_challenge_method'] = 'S256'
    elif OAUTH_CODE_CHALLENGE_METHOD:
        raise Exception(
            'Code challenge methods other than "%s" not supported. Given: "%s"' % ('S256', OAUTH_CODE_CHALLENGE_METHOD)
        )

    return client_kwargs


def load_oauth_providers():
    OAUTH_PROVIDERS.clear()
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:

        def google_oauth_register(oauth: OAuth):
            client = oauth.register(
                name='google',
                client_id=GOOGLE_CLIENT_ID,
                client_secret=GOOGLE_CLIENT_SECRET,
                server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
                client_kwargs=oauth_client_kwargs(GOOGLE_OAUTH_SCOPE),
                redirect_uri=GOOGLE_REDIRECT_URI,
                **({'authorize_params': GOOGLE_OAUTH_AUTHORIZE_PARAMS} if GOOGLE_OAUTH_AUTHORIZE_PARAMS else {}),
            )
            return client

        OAUTH_PROVIDERS['google'] = {
            'register': google_oauth_register,
        }

    if MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET and MICROSOFT_CLIENT_TENANT_ID:

        def microsoft_oauth_register(oauth: OAuth):
            client = oauth.register(
                name='microsoft',
                client_id=MICROSOFT_CLIENT_ID,
                client_secret=MICROSOFT_CLIENT_SECRET,
                server_metadata_url=f'{MICROSOFT_CLIENT_LOGIN_BASE_URL}/{MICROSOFT_CLIENT_TENANT_ID}/v2.0/.well-known/openid-configuration?appid={MICROSOFT_CLIENT_ID}',
                client_kwargs=oauth_client_kwargs(MICROSOFT_OAUTH_SCOPE),
                redirect_uri=MICROSOFT_REDIRECT_URI,
            )
            return client

        OAUTH_PROVIDERS['microsoft'] = {
            'picture_url': MICROSOFT_CLIENT_PICTURE_URL,
            'register': microsoft_oauth_register,
        }

    if GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET:

        def github_oauth_register(oauth: OAuth):
            client = oauth.register(
                name='github',
                client_id=GITHUB_CLIENT_ID,
                client_secret=GITHUB_CLIENT_SECRET,
                access_token_url='https://github.com/login/oauth/access_token',
                authorize_url='https://github.com/login/oauth/authorize',
                api_base_url='https://api.github.com',
                userinfo_endpoint='https://api.github.com/user',
                client_kwargs=oauth_client_kwargs(GITHUB_CLIENT_SCOPE),
                redirect_uri=GITHUB_CLIENT_REDIRECT_URI,
            )
            return client

        OAUTH_PROVIDERS['github'] = {
            'register': github_oauth_register,
            'sub_claim': 'id',
        }

    if OAUTH_CLIENT_ID and (OAUTH_CLIENT_SECRET or OAUTH_CODE_CHALLENGE_METHOD) and OPENID_PROVIDER_URL:

        def oidc_oauth_register(oauth: OAuth):
            client = oauth.register(
                name='oidc',
                client_id=OAUTH_CLIENT_ID,
                client_secret=OAUTH_CLIENT_SECRET,
                server_metadata_url=OPENID_PROVIDER_URL,
                client_kwargs=oauth_client_kwargs(
                    OAUTH_SCOPES,
                    **(
                        {'token_endpoint_auth_method': OAUTH_TOKEN_ENDPOINT_AUTH_METHOD}
                        if OAUTH_TOKEN_ENDPOINT_AUTH_METHOD
                        else {}
                    ),
                ),
                redirect_uri=OPENID_REDIRECT_URI,
            )
            return client

        OAUTH_PROVIDERS['oidc'] = {
            'name': OAUTH_PROVIDER_NAME,
            'register': oidc_oauth_register,
        }

    if FEISHU_CLIENT_ID and FEISHU_CLIENT_SECRET:

        def feishu_oauth_register(oauth: OAuth):
            client = oauth.register(
                name='feishu',
                client_id=FEISHU_CLIENT_ID,
                client_secret=FEISHU_CLIENT_SECRET,
                access_token_url='https://open.feishu.cn/open-apis/authen/v2/oauth/token',
                authorize_url='https://accounts.feishu.cn/open-apis/authen/v1/authorize',
                api_base_url='https://open.feishu.cn/open-apis',
                userinfo_endpoint='https://open.feishu.cn/open-apis/authen/v1/user_info',
                client_kwargs={
                    'scope': FEISHU_OAUTH_SCOPE,
                    **({'timeout': int(OAUTH_TIMEOUT)} if OAUTH_TIMEOUT else {}),
                },
                redirect_uri=FEISHU_REDIRECT_URI,
            )
            return client

        OAUTH_PROVIDERS['feishu'] = {
            'register': feishu_oauth_register,
            'sub_claim': 'user_id',
        }

    configured_providers = []
    if GOOGLE_CLIENT_ID:
        configured_providers.append('Google')
    if MICROSOFT_CLIENT_ID:
        configured_providers.append('Microsoft')
    if GITHUB_CLIENT_ID:
        configured_providers.append('GitHub')
    if FEISHU_CLIENT_ID:
        configured_providers.append('Feishu')

    if configured_providers and not OPENID_PROVIDER_URL and not OPENID_END_SESSION_ENDPOINT:
        provider_list = ', '.join(configured_providers)
        log.warning(
            f'⚠️  OAuth providers configured ({provider_list}) but OPENID_PROVIDER_URL not set - logout will not work!'
        )
        log.warning(
            f"Set OPENID_PROVIDER_URL to your OAuth provider's OpenID Connect discovery endpoint,"
            f' or set OPENID_END_SESSION_ENDPOINT to a custom logout URL to fix logout functionality.'
        )


load_oauth_providers()



####################################
# LDAP
####################################

ENABLE_LDAP = os.getenv('ENABLE_LDAP', 'false').lower() == 'true'

LDAP_SERVER_LABEL = os.getenv('LDAP_SERVER_LABEL', 'LDAP Server')

LDAP_SERVER_HOST = os.getenv('LDAP_SERVER_HOST', 'localhost')

LDAP_SERVER_PORT = int(os.getenv('LDAP_SERVER_PORT', '389'))

LDAP_ATTRIBUTE_FOR_MAIL = os.getenv('LDAP_ATTRIBUTE_FOR_MAIL', 'mail')

LDAP_ATTRIBUTE_FOR_USERNAME = os.getenv('LDAP_ATTRIBUTE_FOR_USERNAME', 'uid')

LDAP_APP_DN = os.getenv('LDAP_APP_DN', '')

LDAP_APP_PASSWORD = os.getenv('LDAP_APP_PASSWORD', '')

LDAP_SEARCH_BASE = os.getenv('LDAP_SEARCH_BASE', '')

LDAP_SEARCH_FILTERS = os.getenv('LDAP_SEARCH_FILTER', os.getenv('LDAP_SEARCH_FILTERS', ''))

LDAP_USE_TLS = os.getenv('LDAP_USE_TLS', 'True').lower() == 'true'

LDAP_CA_CERT_FILE = os.getenv('LDAP_CA_CERT_FILE', '')

LDAP_VALIDATE_CERT = os.getenv('LDAP_VALIDATE_CERT', 'True').lower() == 'true'

LDAP_CIPHERS = os.getenv('LDAP_CIPHERS', 'ALL')

ENABLE_LDAP_GROUP_MANAGEMENT = os.getenv('ENABLE_LDAP_GROUP_MANAGEMENT', 'False').lower() == 'true'

ENABLE_LDAP_GROUP_CREATION = os.getenv('ENABLE_LDAP_GROUP_CREATION', 'False').lower() == 'true'

LDAP_ATTRIBUTE_FOR_GROUPS = os.getenv('LDAP_ATTRIBUTE_FOR_GROUPS', 'memberOf')


####################################
# Images
####################################

IMAGE_GENERATION_MODEL = os.getenv('IMAGE_GENERATION_MODEL', '')

IMAGE_AUTO_SIZE_MODELS_REGEX_PATTERN = os.getenv('IMAGE_AUTO_SIZE_MODELS_REGEX_PATTERN', '^gpt-image')

IMAGE_URL_RESPONSE_MODELS_REGEX_PATTERN = os.getenv('IMAGE_URL_RESPONSE_MODELS_REGEX_PATTERN', '^gpt-image')

IMAGE_SIZE = os.getenv('IMAGE_SIZE', '512x512')

ENABLE_IMAGE_GENERATION = os.getenv('ENABLE_IMAGE_GENERATION', '').lower() == 'true'

ENABLE_IMAGE_PROMPT_GENERATION = os.getenv('ENABLE_IMAGE_PROMPT_GENERATION', 'true').lower() == 'true'

IMAGES_OPENAI_API_BASE_URL = os.getenv('IMAGES_OPENAI_API_BASE_URL', OPENAI_API_BASE_URL)
IMAGES_OPENAI_API_VERSION = os.getenv('IMAGES_OPENAI_API_VERSION', '')

IMAGES_OPENAI_API_KEY = os.getenv('IMAGES_OPENAI_API_KEY', OPENAI_API_KEY)

images_openai_params = os.getenv('IMAGES_OPENAI_PARAMS', '')
try:
    images_openai_params = json.loads(images_openai_params)
except json.JSONDecodeError:
    images_openai_params = {}


IMAGES_OPENAI_API_PARAMS = images_openai_params

ENABLE_IMAGE_EDIT = os.getenv('ENABLE_IMAGE_EDIT', '').lower() == 'true'

IMAGE_EDIT_MODEL = os.getenv('IMAGE_EDIT_MODEL', '')

IMAGE_EDIT_SIZE = os.getenv('IMAGE_EDIT_SIZE', '')

ENABLE_OPENAI_IMAGE_EDIT_NORMALIZATION = os.getenv('ENABLE_OPENAI_IMAGE_EDIT_NORMALIZATION', 'true').lower() == 'true'

IMAGES_EDIT_OPENAI_API_BASE_URL = os.getenv('IMAGES_EDIT_OPENAI_API_BASE_URL', OPENAI_API_BASE_URL)
IMAGES_EDIT_OPENAI_API_VERSION = os.getenv('IMAGES_EDIT_OPENAI_API_VERSION', '')

IMAGES_EDIT_OPENAI_API_KEY = os.getenv('IMAGES_EDIT_OPENAI_API_KEY', OPENAI_API_KEY)


####################################
# FILES
####################################

FILE_MAX_SIZE = int(os.getenv('FILE_MAX_SIZE', str(50)))
FILE_ALLOWED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'tif', 'heic', 'heif', 'avif']
FILE_IMAGE_COMPRESSION_WIDTH = int(os.getenv('FILE_IMAGE_COMPRESSION_WIDTH', '0')) or None
FILE_IMAGE_COMPRESSION_HEIGHT = int(os.getenv('FILE_IMAGE_COMPRESSION_HEIGHT', '0')) or None


####################################
# CONFIG STORE
####################################


async def seed_registered_defaults():
    await Config.repair_config_rows()
    await Config.seed_defaults(DEFAULT_CONFIG)


async def async_reset_config():
    await Config.clear()


DEFAULT_CONFIG = {
    'direct.enable': ENABLE_DIRECT_CONNECTIONS,
    'openai.enable': ENABLE_OPENAI_API,
    'openai.api_keys': OPENAI_API_KEYS,
    'openai.api_base_urls': OPENAI_API_BASE_URLS,
    'openai.api_configs': OPENAI_API_CONFIGS,
    'models.base_models_cache': ENABLE_BASE_MODELS_CACHE,
    'oauth.client.timeout': OAUTH_CLIENT_TIMEOUT,
    'image_generation.enable': ENABLE_IMAGE_GENERATION,
    'image_generation.model': IMAGE_GENERATION_MODEL,
    'image_generation.size': IMAGE_SIZE,
    'image_generation.prompt.enable': ENABLE_IMAGE_PROMPT_GENERATION,
    'image_generation.openai.api_base_url': IMAGES_OPENAI_API_BASE_URL,
    'image_generation.openai.api_version': IMAGES_OPENAI_API_VERSION,
    'image_generation.openai.api_key': IMAGES_OPENAI_API_KEY,
    'image_generation.openai.params': IMAGES_OPENAI_API_PARAMS,
    'images.edit.enable': ENABLE_IMAGE_EDIT,
    'images.edit.model': IMAGE_EDIT_MODEL,
    'images.edit.size': IMAGE_EDIT_SIZE,
    'images.edit.openai.api_base_url': IMAGES_EDIT_OPENAI_API_BASE_URL,
    'images.edit.openai.api_version': IMAGES_EDIT_OPENAI_API_VERSION,
    'images.edit.openai.api_key': IMAGES_EDIT_OPENAI_API_KEY,
    'file.image_compression_width': FILE_IMAGE_COMPRESSION_WIDTH,
    'file.image_compression_height': FILE_IMAGE_COMPRESSION_HEIGHT,
    'file.max_size': FILE_MAX_SIZE,
    'file.allowed_extensions': FILE_ALLOWED_EXTENSIONS,
    'webui.url': WEBUI_URL,
    'ui.enable_signup': ENABLE_SIGNUP,
    'ui.enable_login_form': ENABLE_LOGIN_FORM,
    'ui.enable_password_change_form': ENABLE_PASSWORD_CHANGE_FORM,
    'ui.default_locale': DEFAULT_LOCALE,
    'ui.default_models': DEFAULT_MODELS,
    'ui.default_pinned_models': DEFAULT_PINNED_MODELS,
    'ui.default_interface_settings': DEFAULT_INTERFACE_SETTINGS,
    'ui.prompt_suggestions': DEFAULT_PROMPT_SUGGESTIONS,
    'ui.model_order_list': MODEL_ORDER_LIST,
    'models.default_metadata': DEFAULT_MODEL_METADATA,
    'models.default_params': DEFAULT_MODEL_PARAMS,
    'ui.default_user_role': DEFAULT_USER_ROLE,
    'ui.default_group_id': DEFAULT_GROUP_ID,
    'ui.pending_user_overlay_title': PENDING_USER_OVERLAY_TITLE,
    'ui.pending_user_overlay_content': PENDING_USER_OVERLAY_CONTENT,
    'ui.watermark': RESPONSE_WATERMARK,
    'user.permissions': USER_PERMISSIONS,
    'folders.enable': ENABLE_FOLDERS,
    'folders.max_file_count': FOLDER_MAX_FILE_COUNT,
    'users.enable_status': ENABLE_USER_STATUS,
    'ui.enable_community_sharing': ENABLE_COMMUNITY_SHARING,
    'ui.banners': WEBUI_BANNERS,
    'auth.admin.show': SHOW_ADMIN_DETAILS,
    'auth.admin.email': ADMIN_EMAIL,
    'task.model.default': TASK_MODEL,
    'task.model.external': TASK_MODEL_EXTERNAL,
    'task.model.params': TASK_MODEL_PARAMS,
    'chat.context_compaction.model': CONTEXT_COMPACTION_MODEL,
    'chat.context_compaction.enable': ENABLE_CONTEXT_COMPACTION,
    'chat.context_compaction.token_threshold': CONTEXT_COMPACTION_TOKEN_THRESHOLD,
    'chat.context_compaction.token_cap': CONTEXT_COMPACTION_TOKEN_CAP,
    'chat.context_compaction.retention_percentage': CONTEXT_COMPACTION_RETENTION_PERCENTAGE,
    'chat.context_compaction.prompt_template': CONTEXT_COMPACTION_PROMPT_TEMPLATE,
    'task.title.prompt_template': TITLE_GENERATION_PROMPT_TEMPLATE,
    'task.tags.prompt_template': TAGS_GENERATION_PROMPT_TEMPLATE,
    'task.image.prompt_template': IMAGE_PROMPT_GENERATION_PROMPT_TEMPLATE,
    'task.follow_up.prompt_template': FOLLOW_UP_GENERATION_PROMPT_TEMPLATE,
    'task.follow_up.enable': ENABLE_FOLLOW_UP_GENERATION,
    'task.tags.enable': ENABLE_TAGS_GENERATION,
    'task.title.enable': ENABLE_TITLE_GENERATION,
    'task.autocomplete.enable': ENABLE_AUTOCOMPLETE_GENERATION,
    'task.autocomplete.input_max_length': AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH,
    'task.autocomplete.prompt_template': AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE,
    'auth.enable_api_keys': ENABLE_API_KEYS,
    'auth.api_key.endpoint_restrictions': ENABLE_API_KEYS_ENDPOINT_RESTRICTIONS,
    'auth.api_key.allowed_endpoints': API_KEYS_ALLOWED_ENDPOINTS,
    'auth.jwt_expiry': JWT_EXPIRES_IN,
    'oauth.enable': ENABLE_OAUTH,
    'oauth.enable_signup': ENABLE_OAUTH_SIGNUP,
    'oauth.auto_redirect': OAUTH_AUTO_REDIRECT,
    'oauth.refresh_token.include_scope': OAUTH_REFRESH_TOKEN_INCLUDE_SCOPE,
    'oauth.merge_accounts_by_email': OAUTH_MERGE_ACCOUNTS_BY_EMAIL,
    'oauth.google.client_id': GOOGLE_CLIENT_ID,
    'oauth.google.client_secret': GOOGLE_CLIENT_SECRET,
    'oauth.google.scope': GOOGLE_OAUTH_SCOPE,
    'oauth.google.redirect_uri': GOOGLE_REDIRECT_URI,
    'oauth.microsoft.client_id': MICROSOFT_CLIENT_ID,
    'oauth.microsoft.client_secret': MICROSOFT_CLIENT_SECRET,
    'oauth.microsoft.tenant_id': MICROSOFT_CLIENT_TENANT_ID,
    'oauth.microsoft.login_base_url': MICROSOFT_CLIENT_LOGIN_BASE_URL,
    'oauth.microsoft.picture_url': MICROSOFT_CLIENT_PICTURE_URL,
    'oauth.microsoft.scope': MICROSOFT_OAUTH_SCOPE,
    'oauth.microsoft.redirect_uri': MICROSOFT_REDIRECT_URI,
    'oauth.github.client_id': GITHUB_CLIENT_ID,
    'oauth.github.client_secret': GITHUB_CLIENT_SECRET,
    'oauth.github.scope': GITHUB_CLIENT_SCOPE,
    'oauth.github.redirect_uri': GITHUB_CLIENT_REDIRECT_URI,
    'oauth.client_id': OAUTH_CLIENT_ID,
    'oauth.client_secret': OAUTH_CLIENT_SECRET,
    'oauth.provider_url': OPENID_PROVIDER_URL,
    'oauth.end_session_endpoint': OPENID_END_SESSION_ENDPOINT,
    'oauth.redirect_uri': OPENID_REDIRECT_URI,
    'oauth.scopes': OAUTH_SCOPES,
    'oauth.timeout': OAUTH_TIMEOUT,
    'oauth.token_endpoint_auth_method': OAUTH_TOKEN_ENDPOINT_AUTH_METHOD,
    'oauth.code_challenge_method': OAUTH_CODE_CHALLENGE_METHOD,
    'oauth.provider_name': OAUTH_PROVIDER_NAME,
    'oauth.sub_claim': OAUTH_SUB_CLAIM,
    'oauth.username_claim': OAUTH_USERNAME_CLAIM,
    'oauth.picture_claim': OAUTH_PICTURE_CLAIM,
    'oauth.email_claim': OAUTH_EMAIL_CLAIM,
    'oauth.group_claim': OAUTH_GROUPS_CLAIM,
    'oauth.feishu.client_id': FEISHU_CLIENT_ID,
    'oauth.feishu.client_secret': FEISHU_CLIENT_SECRET,
    'oauth.feishu.scope': FEISHU_OAUTH_SCOPE,
    'oauth.feishu.redirect_uri': FEISHU_REDIRECT_URI,
    'oauth.enable_role_mapping': ENABLE_OAUTH_ROLE_MANAGEMENT,
    'oauth.enable_group_mapping': ENABLE_OAUTH_GROUP_MANAGEMENT,
    'oauth.enable_group_creation': ENABLE_OAUTH_GROUP_CREATION,
    'oauth.group_default_share': OAUTH_GROUP_DEFAULT_SHARE,
    'oauth.blocked_groups': OAUTH_BLOCKED_GROUPS,
    'oauth.roles_claim': OAUTH_ROLES_CLAIM,
    'oauth.allowed_roles': OAUTH_ALLOWED_ROLES,
    'oauth.admin_roles': OAUTH_ADMIN_ROLES,
    'oauth.allowed_domains': OAUTH_ALLOWED_DOMAINS,
    'oauth.update_picture_on_login': OAUTH_UPDATE_PICTURE_ON_LOGIN,
    'oauth.update_name_on_login': OAUTH_UPDATE_NAME_ON_LOGIN,
    'oauth.update_email_on_login': OAUTH_UPDATE_EMAIL_ON_LOGIN,
    'oauth.audience': OAUTH_AUDIENCE,
    'ldap.enable': ENABLE_LDAP,
    'ldap.server.label': LDAP_SERVER_LABEL,
    'ldap.server.host': LDAP_SERVER_HOST,
    'ldap.server.port': LDAP_SERVER_PORT,
    'ldap.server.attribute_for_mail': LDAP_ATTRIBUTE_FOR_MAIL,
    'ldap.server.attribute_for_username': LDAP_ATTRIBUTE_FOR_USERNAME,
    'ldap.server.app_dn': LDAP_APP_DN,
    'ldap.server.app_password': LDAP_APP_PASSWORD,
    'ldap.server.users_dn': LDAP_SEARCH_BASE,
    'ldap.server.search_filter': LDAP_SEARCH_FILTERS,
    'ldap.server.use_tls': LDAP_USE_TLS,
    'ldap.server.ca_cert_file': LDAP_CA_CERT_FILE,
    'ldap.server.validate_cert': LDAP_VALIDATE_CERT,
    'ldap.server.ciphers': LDAP_CIPHERS,
    'ldap.group.enable_management': ENABLE_LDAP_GROUP_MANAGEMENT,
    'ldap.group.enable_creation': ENABLE_LDAP_GROUP_CREATION,
    'ldap.server.attribute_for_groups': LDAP_ATTRIBUTE_FOR_GROUPS,
}


ENABLE_PERSISTENT_CONFIG = os.getenv('ENABLE_PERSISTENT_CONFIG', 'True').lower() == 'true'
ENABLE_OAUTH_PERSISTENT_CONFIG = os.getenv('ENABLE_OAUTH_PERSISTENT_CONFIG', 'False').lower() == 'true'

Config.configure(
    defaults=DEFAULT_CONFIG,
    enable_persistent=ENABLE_PERSISTENT_CONFIG,
    enable_oauth_persistent=ENABLE_OAUTH_PERSISTENT_CONFIG,
)
