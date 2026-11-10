"""Native local Jobby tools. Registration is deliberately dependency and state free."""
import json
from pathlib import Path

NAMES = ('initialize', 'intake', 'overview', 'prepare', 'review', 'attempt', 'discover')

def register(ctx):
    schemas = json.loads((Path(__file__).parent / 'tool-schemas.json').read_text())
    for action in NAMES:
        def handler(args, _action=action, **kwargs):
            try:
                from .plugin import dispatch
                return json.dumps(dispatch(_action, args))
            except Exception:
                return json.dumps(dict(ok=False, error='jobby_runtime_unavailable', message='Install the bundled Jobby package and declared dependencies in the Hermes runtime.'))
        ctx.register_tool(name='jobby_' + action, toolset='jobby',
                          schema=schemas[action], handler=handler)

    ctx.register_skill('assisted-application', Path(__file__).parent / 'skills' / 'assisted-application' / 'SKILL.md',
                       'Prepare selected applications with native local Jobby tools; external browser actions remain separate.')
