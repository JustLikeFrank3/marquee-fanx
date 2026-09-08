"""Fail if a configured credential occurs in the distributable web bundle."""
from pathlib import Path
from dotenv import dotenv_values
root=Path(__file__).resolve().parent.parent
config=dotenv_values(root/'.env')
secrets=[v.encode() for k,v in config.items() if k in ('SEATGEEK_CLIENT_ID','SEATGEEK_CLIENT_SECRET','OPENAI_API_KEY','AZURE_OPENAI_API_KEY','AZURE_MAPS_KEY','LASTFM_API_KEY') and v]
files=[p for p in (root/'web'/'dist').rglob('*') if p.is_file()]
assert files,'Build the frontend before checking it.'
assert not any(secret in path.read_bytes() for path in files for secret in secrets),'Credential found in browser bundle'
print('Browser bundle credential check passed.')
