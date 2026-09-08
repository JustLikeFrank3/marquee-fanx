"""Read-only API smoke test. Never prints credentials, URLs or raw responses."""
import asyncio
from datetime import date,timedelta
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
from server.data import EventSource,DataError
from server.models import Search
load_dotenv(Path(__file__).resolve().parent.parent/'.env')
async def main():
    try:
        rows,_=await EventSource('live').search(Search(city='Atlanta',date_from=date.today(),date_to=date.today()+timedelta(days=30),limit=1))
        print('SeatGeek access verified. Events returned:',len(rows))
        if rows:
            print('Event fields:', ', '.join(sorted(rows[0].keys())))
            print('Price statistics present:', bool(rows[0].get('stats')))
            print('Statistics field names:', ', '.join(sorted((rows[0].get('stats') or {}).keys())))
            print('Venue field names:', ', '.join(sorted((rows[0].get('venue') or {}).keys())))
            detail,_=await EventSource('live').detail(rows[0]['id'])
            print('Detail price statistics present:',bool(detail.get('stats')))
    except DataError as exc:
        print(str(exc));sys.exit(1)
asyncio.run(main())
