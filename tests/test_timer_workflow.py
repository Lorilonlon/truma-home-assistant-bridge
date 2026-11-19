# SPDX-License-Identifier: MIT
# Isolated interpreter for generated HA actions; never contacts hardware.
import importlib.util,json,re,unittest
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
try:
 from jinja2.nativetypes import NativeEnvironment
 from jinja2 import StrictUndefined
except ImportError:
 raise unittest.SkipTest('Optional workflow simulation requires jinja2')
from pathlib import Path
R=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('build',R/'scripts/build_timer_workflow.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
class Stop(Exception):
 def __init__(self,error=False): self.error=error
class Sim:
 def __init__(self):
  self.now=datetime(2026,11,15,12,0,tzinfo=ZoneInfo('Europe/Berlin'));self.calls=[];self.drop=False
  self.states={b.JOB:'',b.PREVIOUS:'',b.WHEN:'',b.CLIMATE:'heat',b.WATER:'Aus','binary_sensor.truma_inet_verbindung':'on','sensor.truma_inet_timer':'Aus','script.truma_heizung_neu_starten':'off','automation.truma_timer_zeitplan':'on','sensor.truma_inet_letzte_aktualisierung':self.now.isoformat()}
  self.attrs={b.CLIMATE:{'temperature':5,'fan_mode':'Eco'}}
  self.env=NativeEnvironment(undefined=StrictUndefined)
  def dt(v):
   if isinstance(v,datetime):return v
   if isinstance(v,(int,float)):return datetime.fromtimestamp(v,ZoneInfo('UTC'))
   return datetime.fromisoformat(v)
  def ts(v,default=None):
   try:return dt(v).timestamp()
   except:return default
  self.env.globals.update(states=lambda e:self.states.get(e,'unknown'),state_attr=lambda e,a:self.attrs.get(e,{}).get(a),is_state=lambda e,v:self.states.get(e)==v,is_state_attr=lambda e,a,v:self.attrs.get(e,{}).get(a)==v,now=lambda:self.now,as_datetime=dt,as_timestamp=ts,as_local=lambda v:dt(v).astimezone(self.now.tzinfo),today_at=lambda v:self.now.replace(hour=int(v[:2]),minute=int(v[3:5]),second=0,microsecond=0),timedelta=timedelta,strptime=lambda v,f,default=None:datetime.strptime(v,f) if v else default)
  def parse(v,default):
   try:return json.loads(v)
   except:return default
  self.env.filters.update(to_json=lambda v:json.dumps(v,separators=(',',':')),from_json=parse,regex_match=lambda v,p:bool(re.match(p,v)),timestamp_custom=lambda v,f,local:datetime.fromtimestamp(v,self.now.tzinfo).strftime(f))
 def render(self,x,v):
  if isinstance(x,str) and ('{{'in x or '{%'in x):return self.env.from_string(x).render(v)
  if isinstance(x,list):return [self.render(i,v)for i in x]
  if isinstance(x,dict):return {k:self.render(i,v)for k,i in x.items()}
  return x
 def cond(self,c,v):
  t=c['condition']
  if t=='template':return bool(self.render(c['value_template'],v))
  if t=='not':return not all(self.cond(i,v)for i in c['conditions'])
  if t=='state':
   actual=self.attrs.get(c['entity_id'],{}).get(c['attribute'])if 'attribute'in c else self.states.get(c['entity_id'])
   want=self.render(c['state'],v);return actual in want if isinstance(want,list)else actual==want
  raise Exception(t)
 def advance(self,s):
  self.now+=timedelta(seconds=s);self.states['sensor.truma_inet_letzte_aktualisierung']=self.now.isoformat()
 def seq(self,seq,v):
  for a in seq:
   if 'variables'in a:
    for k,x in a['variables'].items():v[k]=self.render(x,v)
   elif 'if'in a:self.seq(a['then']if all(self.cond(c,v)for c in a['if'])else a.get('else',[]),v)
   elif 'choose'in a:
    for c in a['choose']:
     if all(self.cond(x,v)for x in c['conditions']):self.seq(c['sequence'],v);break
   elif 'condition'in a:
    if not self.cond(a,v):raise Stop()
   elif 'repeat'in a:
    for i in range(a['repeat']['count']):v['repeat']={'index':i+1};self.seq(a['repeat']['sequence'],v)
   elif 'wait_template'in a:
    yes=bool(self.render(a['wait_template'],v))
    if not yes:self.advance(a['timeout']['seconds']);yes=bool(self.render(a['wait_template'],v))
    v['wait']={'completed':yes}
   elif 'delay'in a:self.advance(a['delay']['seconds'])
   elif 'stop'in a:raise Stop(a.get('error',False))
   elif 'action'in a:
    s=a['action'];e=self.render(a.get('target',{}).get('entity_id'),v);d=self.render(a.get('data',{}),v);self.calls.append((s,e,d))
    if s=='input_text.set_value':assert isinstance(d['value'],str);assert len(d['value'])<=255;self.states[e]=d['value']
    elif s=='input_datetime.set_datetime':self.states[e]=d['timestamp']
    elif s.startswith('climate.') and not self.drop:
     if s.endswith('set_temperature'):self.attrs[e]['temperature']=d['temperature']
     if s.endswith('set_hvac_mode'):
      self.states[e]=d['hvac_mode'];self.attrs[e]['fan_mode']='Aus'if d['hvac_mode']=='off'else'Eco'
     if s.endswith('set_fan_mode'):self.attrs[e]['fan_mode']=d['fan_mode']
    elif s=='select.select_option'and not self.drop:self.states[e]=d['option']
   else:raise Exception(a)
 def run(self,operation,**extra):
  v={**b.build()['timer-script.json']['variables'],'operation':operation,**extra}
  try:self.seq(b.build()['timer-script.json']['sequence'],v);return False
  except Stop as s:return s.error
 def job(self,slot=0):return json.loads(self.states.get(b.JOBS[slot],'') or '{}')
 def submit(self,**kw):return self.run('submit',request_id='test-id-12345',start_at='2026-11-15T12:10',end_at='2026-11-15T12:30',temperature='19',fan='Eco',water='Niedrig',daily=kw.pop('daily',False),use_end=kw.pop('use_end',False),**kw)
 def due(self,slot=0):self.now=datetime.fromtimestamp(self.job(slot)['e']if self.job(slot)['p']=='running'else self.job(slot)['s'],self.now.tzinfo)
class Tests(unittest.TestCase):
 def test_no_writes_before_start(self):
  s=Sim();self.assertFalse(s.submit());s.run('tick');self.assertEqual(s.job()['p'],'armed');self.assertFalse(any(x[0].startswith('climate.')for x in s.calls))
 def test_once_no_end(self):
  s=Sim();s.submit();s.due();s.run('tick');self.assertEqual(s.job()['p'],'done');self.assertEqual(s.attrs[b.CLIMATE]['temperature'],19);n=len(s.calls);s.advance(86400);s.run('tick');self.assertEqual(n,len(s.calls))
 def test_restore_frost(self):
  s=Sim();s.submit(use_end=True);s.due();s.run('tick');self.assertEqual(s.job()['p'],'running');self.assertEqual(json.loads(s.states[b.PREVIOUS])['t'],5);s.due();s.run('tick');self.assertEqual(s.job()['p'],'done');self.assertEqual(s.attrs[b.CLIMATE]['temperature'],5);self.assertEqual(s.states[b.WATER],'Aus')
 def test_restore_off_preset(self):
  s=Sim();s.states[b.CLIMATE]='off';s.attrs[b.CLIMATE]['fan_mode']='Aus';s.submit(use_end=True);s.due();s.run('tick');s.due();s.run('tick');self.assertEqual(s.states[b.CLIMATE],'off');self.assertEqual(s.attrs[b.CLIMATE]['temperature'],5)
 def test_daily(self):
  s=Sim();s.submit(daily=True,use_end=True);s.due();s.run('tick');s.due();s.run('tick');self.assertEqual(s.job()['p'],'waiting');self.assertEqual(datetime.fromtimestamp(s.job()['s'],s.now.tzinfo).isoformat(),'2026-11-16T12:10:00+01:00')
 def test_missing_confirmation_fails(self):
  s=Sim();s.submit();s.drop=True;s.due();self.assertTrue(s.run('tick'));self.assertEqual(s.job()['p'],'error');self.assertEqual(sum(x[0]=='climate.set_temperature'for x in s.calls),3)
 def test_missed_no_replay(self):
  s=Sim();s.submit();s.due();s.advance(120);self.assertTrue(s.run('tick'));self.assertEqual(s.job()['r'],'missed');self.assertFalse(any(x[0].startswith('climate.')for x in s.calls))
 def test_cancel(self):
  s=Sim();s.submit();s.run('cancel');self.assertEqual(s.job()['p'],'cancelled');s.advance(900);s.run('tick');self.assertFalse(any(x[0].startswith('climate.')for x in s.calls))
 def test_restart_partial_no_replay(self):
  s=Sim();s.submit();s.states[b.JOB]=json.dumps(dict(s.job(),p='executing'));self.assertTrue(s.run('tick'));self.assertEqual(s.job()['r'],'interrupted')
 def test_invalid_no_mutation(self):
  s=Sim();self.assertTrue(s.run('submit',request_id='valid-id',temperature='99'));self.assertEqual(s.calls,[])
 def test_live_snapshot_not_submit_snapshot(self):
  s=Sim();s.submit(use_end=True);s.attrs[b.CLIMATE]['temperature']=7;s.due();s.run('tick');self.assertEqual(json.loads(s.states[b.PREVIOUS])['t'],7)
 def test_native_timer_conflict(self):
  s=Sim();s.submit();s.states['sensor.truma_inet_timer']='Aktiv';s.due();s.run('tick');self.assertEqual(s.job()['p'],'error');self.assertFalse(any(x[0].startswith('climate.')for x in s.calls))
 def second(self,s,consent=True,**extra):
  return s.run('submit',slot=1,request_id='second-id-1234',start_at='2026-11-15T12:20',end_at='2026-11-15T12:40',temperature='21',fan='High',water='Hoch',daily=False,use_end=True,overlap_ids=['test-id-12345'] if consent else [],**extra)
 def test_overlap_requires_consent(self):
  s=Sim();s.submit(use_end=True);count=len(s.calls);self.assertTrue(self.second(s,False));self.assertEqual(count,len(s.calls));self.assertEqual(s.job(1),{})
 def test_later_owner_prevents_old_restore(self):
  s=Sim();s.submit(use_end=True);self.assertFalse(self.second(s));s.due();s.run('tick');s.due(1);s.run('tick',slot=1);self.assertEqual(s.attrs[b.CLIMATE]['temperature'],21)
  s.due();count=len(s.calls);s.run('tick');self.assertEqual(s.job()['r'],'superseded');self.assertEqual(s.attrs[b.CLIMATE]['temperature'],21);self.assertFalse(any(x[0].startswith('climate.')for x in s.calls[count:]))
  s.due(1);s.run('tick',slot=1);self.assertEqual(s.attrs[b.CLIMATE]['temperature'],19);self.assertEqual(s.job(1)['p'],'done')
 def test_stale_consent_rejected(self):
  s=Sim();s.submit(use_end=True);s.states[b.JOB]=json.dumps(dict(s.job(),id='changed-id'));self.assertTrue(self.second(s));self.assertEqual(s.job(1),{})
 def test_daily_overlap_on_later_date(self):
  s=Sim();s.submit(daily=True,use_end=True);self.assertTrue(s.run('submit',slot=1,request_id='another-id-1234',start_at='2026-11-20T12:20',end_at='',temperature='21',fan='Eco',water='Aus',daily=False,use_end=False,overlap_ids=[]))
 def test_nonoverlap_allowed(self):
  s=Sim();s.submit(use_end=True);self.assertFalse(s.run('submit',slot=1,request_id='another-id-1234',start_at='2026-11-15T12:35',end_at='',temperature='21',fan='Eco',water='Aus',daily=False,use_end=False,overlap_ids=[]))
 def test_cancel_other_does_not_cancel_first(self):
  s=Sim();s.submit(use_end=True);self.second(s);s.run('cancel',slot=1);self.assertEqual(s.job()['p'],'armed');self.assertEqual(s.job(1)['p'],'cancelled')
 def edit(self,s,expected,**kw):
  data=dict(slot=0,request_id='edited-id-1234',expected_job=expected,start_at='2026-11-15T12:15',end_at='',temperature='21',fan='High',water='Aus',daily=False,use_end=False,overlap_ids=[]);data.update(kw)
  return s.run('submit',**data)
 def test_edit_pending_in_place(self):
  s=Sim();s.submit();old=s.job();s.calls=[];self.assertFalse(self.edit(s,old));self.assertEqual(s.job()['t'],'21');self.assertEqual(s.job()['id'],'edited-id-1234');self.assertEqual(s.job()['p'],'armed');self.assertFalse(any(x[0].startswith(('climate.','select.'))for x in s.calls))
 def test_edit_invalid_keeps_original(self):
  s=Sim();s.submit();old=s.job();s.calls=[];self.assertTrue(self.edit(s,old,temperature='99'));self.assertEqual(s.job(),old);self.assertEqual(s.calls,[])
 def test_edit_stale_or_started_keeps_original(self):
  for phase in ['armed','executing','running','restoring','done','cancelled']:
   s=Sim();s.submit();old=s.job();changed=dict(old,p=phase,t='22');s.states[b.JOB]=json.dumps(changed);s.calls=[]
   self.assertTrue(self.edit(s,old));self.assertEqual(s.job(),changed);self.assertEqual(s.calls,[])
 def test_edit_overlap_keeps_original_without_consent(self):
  s=Sim();s.submit(use_end=True);self.second(s);old=s.job();s.calls=[];self.assertTrue(self.edit(s,old));self.assertEqual(s.job(),old);self.assertEqual(s.calls,[])
  self.assertFalse(self.edit(s,old,overlap_ids=['second-id-1234']))
 def test_edit_waiting_daily(self):
  s=Sim();s.submit(daily=True);s.due();s.run('tick');old=s.job();self.assertEqual(old['p'],'waiting');self.assertFalse(self.edit(s,old,start_at='2026-11-16T13:00',daily=True));self.assertEqual(s.job()['p'],'armed')
 def test_done_has_completion_time_and_removal_no_heater_writes(self):
  s=Sim();s.submit();s.due();s.run('tick');j=s.job();self.assertEqual(j['finished'],int(s.now.timestamp()));s.calls=[];self.assertFalse(s.run('cancel',expected_job=j));self.assertEqual(s.job()['p'],'cancelled');self.assertFalse(any(x[0].startswith(('climate.','select.'))for x in s.calls))
 def test_stale_remove_cannot_cancel_replaced_timer(self):
  s=Sim();s.submit();old=s.job();self.edit(s,old);s.calls=[];self.assertTrue(s.run('cancel',expected_job=old));self.assertEqual(s.job()['p'],'armed');self.assertEqual(s.calls,[])
if __name__=='__main__':unittest.main()
