import asyncio
from unittest.mock import MagicMock,patch
import pytest
from server.foundry import FoundryModel
from server.chat import ChatError,ChatService
from server.evidence import EvidenceStore

def configure(monkeypatch):
    monkeypatch.setenv('MARQUEE_AI_PROVIDER','azure_foundry')
    monkeypatch.setenv('FOUNDRY_PROJECT_ENDPOINT','https://marquee-frank-foundry.services.ai.azure.com/api/projects/marquee')
    monkeypatch.setenv('FOUNDRY_AGENT_NAME','marquee-planner')

def test_azure_provider_and_invalid_endpoint(monkeypatch):
    configure(monkeypatch)
    assert isinstance(ChatService(None,EvidenceStore()).model,FoundryModel)
    assert FoundryModel().configured()
    monkeypatch.setenv('FOUNDRY_PROJECT_ENDPOINT','http://example.com/api/projects/marquee')
    assert not FoundryModel().configured()

def test_agent_reference_and_no_api_key(monkeypatch):
    configure(monkeypatch)
    with patch('azure.ai.projects.AIProjectClient') as project,patch('azure.identity.AzureCliCredential'):
        client=project.return_value.__enter__.return_value.get_openai_client.return_value.__enter__.return_value
        client.responses.create.return_value.status='completed'
        item=MagicMock();item.model_dump.return_value={'type':'message'}
        client.responses.create.return_value.output=[item]
        assert asyncio.run(FoundryModel().respond([], 'instructions', []))==[{'type':'message'}]
        args=client.responses.create.call_args.kwargs
        assert args['extra_body']['agent_reference']['name']=='marquee-planner'
        assert args['store'] is False and 'api_key' not in args
        assert 'instructions' not in args
        assert args['input'][0]['type']=='message'
        assert args['input'][0]['role']=='developer'

def test_provider_errors_do_not_expose_details(monkeypatch):
    configure(monkeypatch)
    with patch.object(FoundryModel,'_respond',side_effect=RuntimeError('sensitive diagnostic')):
        with pytest.raises(ChatError) as exc: asyncio.run(FoundryModel().respond([], '', []))
    assert 'sensitive' not in str(exc.value)
