"""Dedicated Azure Foundry agent transport, using Entra authentication."""
import asyncio
import os
from urllib.parse import urlparse


class FoundryModel:
    @property
    def label(self):
        return 'Azure Foundry \u00b7 ' + os.getenv('FOUNDRY_AGENT_NAME', '')

    def configured(self):
        endpoint = os.getenv('FOUNDRY_PROJECT_ENDPOINT','')
        parsed = urlparse(endpoint)
        return bool(parsed.scheme == 'https' and parsed.hostname
                    and parsed.hostname.endswith('.services.ai.azure.com')
                    and '/api/projects/' in parsed.path and os.getenv('FOUNDRY_AGENT_NAME'))

    async def respond(self, items, instructions, tools):
        from .chat import ChatError
        if not self.configured():
            raise ChatError('Configure the Marquee Foundry project and agent on the server.')
        try:
            return await asyncio.to_thread(self._respond,items,instructions)
        except Exception as exc:
            # Never return provider response bodies, auth diagnostics, or tokens.
            if isinstance(exc,ChatError): raise
            raise ChatError('Azure could not complete the request. Check Marquee’s Azure sign-in, agent access, and model quota.') from None

    def _respond(self, items, instructions):
        from azure.ai.projects import AIProjectClient
        from azure.identity import AzureCliCredential, ManagedIdentityCredential
        from .chat import ChatError
        # User-assigned managed identity needs its client ID; None keeps system-assigned behavior.
        credential = (ManagedIdentityCredential(client_id=os.getenv('AZURE_CLIENT_ID') or None) if os.getenv('FOUNDRY_AUTH')=='managed_identity'
                      else AzureCliCredential(process_timeout=15))
        with credential, AIProjectClient(endpoint=os.environ['FOUNDRY_PROJECT_ENDPOINT'],credential=credential) as project:
            with project.get_openai_client(max_retries=0) as client:
                inputs = [{'type':'message','role':'developer','content':instructions}]
                inputs.extend({'type':'message',**item} if 'role' in item and 'type' not in item else item for item in items)
                response = client.responses.create(input=inputs,
                    store=False,parallel_tool_calls=False,max_output_tokens=2200,
                    extra_body={'agent_reference':{'type':'agent_reference','name':os.environ['FOUNDRY_AGENT_NAME']}},
                    timeout=45)
                if response.status!='completed':
                    raise ChatError('Azure’s planner could not finish. Try a simpler request.')
                return [item.model_dump(mode='json',exclude_none=True) for item in response.output]
