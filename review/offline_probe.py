"""Offline review probes; no model calls or writes to the app warehouse/state.

Run from aco-chat-app with a compatible Python, DuckDB, pandas and anthropic.
Synthetic timings are narrow-table microbenchmarks, not production capacity tests.
"""
import os
import sys
import time
import json
from pathlib import Path

os.environ['SECRET_KEY'] = 'offline-review-only'
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import duckdb
from app.data import Warehouse, Column
from app.portfolio import PortfolioCalc, build_spec, LeadSpec
from app.agent import Agent

root = Path(__file__).resolve().parents[1]
con = duckdb.connect(str(root / 'data/warehouse.duckdb'), read_only=True)
con.execute('SET enable_external_access=false')
con.execute('SET lock_configuration=true')
wh = Warehouse(con)
for table, source, program in con.execute('SELECT * FROM _tables').fetchall():
    wh.tables[table] = {'rows': con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0],
                        'source': source, 'program': program}
    cols = con.execute('SELECT column_name,data_type FROM information_schema.columns WHERE table_name=?', [table]).fetchall()
    wh.columns.extend(Column(table, name, dtype) for name, dtype in cols)
wh._build_programs()
print('SHAPES', json.dumps({p: {k: v for k, v in x.items() if k in ['rows', 'columns']} for p, x in wh.programs.items()}))
calc = PortfolioCalc(wh, build_spec(wh, 'LEAD'))
tins = ['10198331', '10211494', '10211501', '10211534', '10211551']
start = time.perf_counter()
result = calc.metrics(tins, .85)
print('GOLDEN', json.dumps({'seconds': round(time.perf_counter()-start, 3), 'combined': result['combined'], 'cohorts': result['cohorts']}))
agent = Agent.__new__(Agent)  # Deliberately bypass construction of an API client.
agent.wh = wh
agent.default_program = None
agent.calcs = {'LEAD': calc}
other = wh.tables_for('MSSP')[0]
text, _ = agent._run_tool('run_sql', {'sql': f'SELECT count(*) FROM "{other}"', 'purpose': 'scope check'}, {'program': 'LEAD'})
print('CROSS_PROGRAM_FROM_LEAD', text)
print('ONE_ROW_PAYLOAD_BYTES', len(json.dumps(wh.query("SELECT repeat('x', 1000000) AS payload", 200))))
state = {'program': 'LEAD', 'portfolio': tins, 'target_mlr': .85}
agent._portfolio_metrics({'action': 'current', 'save': False, 'target_mlr': .9}, state, 'LEAD')
print('WHAT_IF_SAVED_TARGET', state['target_mlr'])
con.close()

# Small column count; deliberately does not simulate ingestion of 2,605 columns.
con = duckdb.connect(':memory:')
con.execute("CREATE TABLE synth AS SELECT CAST(i AS VARCHAR) tin, CAST(i AS VARCHAR) npi, 'Org '||i org, 'Low' cls, 1000.0 py, 1000.0 benes, 1000000.0 bm, (700000.0+(i%600)*1000) ex FROM range(200000) t(i)")
spec = LeadSpec(program='SYNTH', table='synth', tin='tin', npi='npi', org='org', cls='cls', cls_header='Class', py='py', benes='benes', bm_usd='bm', exp_usd='ex', cohorts=[], net_key='net_shared_savings_usd')
calc = PortfolioCalc(Warehouse(con), spec)
start = time.perf_counter()
result = calc.suggest(['599'], .85)
print('SYNTH_200K_SUGGEST', json.dumps({'seconds': round(time.perf_counter()-start, 3), 'screened': result['candidates']['screened']}))
start = time.perf_counter()
result = calc.metrics([str(i) for i in range(10000)], .85)
payload = json.dumps(result)
print('SYNTH_10K_PORTFOLIO', json.dumps({'seconds': round(time.perf_counter()-start, 3), 'json_bytes': len(payload.encode()), 'rough_tokens_chars_div4': len(payload)//4}))
con.execute("INSERT INTO synth VALUES ('nullcase','nullcase','Missing expense','Low',1000,1000,1000000,NULL)")
result = calc.metrics(['nullcase'], .85)
print('NULL_EXPENSE', json.dumps({'combined': result['combined'], 'warnings': result['warnings']}))
con.close()
