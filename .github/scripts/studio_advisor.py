"""Studio documentation advisor v1.0.0. Reads Markdown as data; never runs PR code."""
import argparse
import base64
import json
import os
import re
import sys
import urllib.request
from pathlib import Path, PurePosixPath
from urllib.parse import quote

VERSION = '1.0.0'
MARKER = '<!-- zgnal-studio-documentation-advisor -->'
HANDBOOK = 'https://github.com/zgnal-studio/studio-handbook/blob/main/'
TOPICS = {
 'brief': ('Project brief', ['brief','purpose','overview','goals','objective','what it does'], 'brief.md'),
 'prd': ('PRD / requirements', ['prd','requirements','product specification','product spec'], 'prd.md'),
 'audience': ('Audience and problem', ['audience','target users','user needs','problem','who it is for'], 'brief.md'),
 'scope': ('Scope and exclusions', ['scope','non goals','out of scope','boundaries'], 'brief.md'),
 'journeys': ('Journeys and interaction states', ['journeys','user flows','user journey','interaction states','experience'], 'experience.md'),
 'content': ('Content requirements', ['content requirements','content strategy','content structure','copy requirements'], 'experience.md'),
 'positioning': ('Positioning and brand', ['positioning','brand','brand identity','brand promise'], 'brand.md'),
 'tone': ('Tone of voice', ['tone of voice','voice and tone','voice','tone','writing style'], 'brand.md'),
 'visual': ('Visual direction', ['visual direction','visual identity','art direction','design direction'], 'brand.md'),
 'architecture': ('Architecture', ['architecture','technical design','system design'], 'technical.md'),
 'data': ('Data and privacy', ['data model','data handling','data retention','privacy','data and privacy'], 'technical.md'),
 'integrations': ('Integrations and dependencies', ['integrations','dependencies','external services','providers'], 'technical.md'),
 'security': ('Security and permissions', ['security','access and secrets','permissions','access control'], 'technical.md'),
 'acceptance': ('Acceptance and verification', ['acceptance','validation','verification','testing','quality gates','checks'], 'acceptance.md'),
 'status': ('Current status and gaps', ['status','current state','known gaps','known limits','what is implemented','tasks','handoff'], 'status.md'),
 'runbook': ('Runbook / use and recovery', ['runbook','run','run it','setup','usage','how to use','start here','operating','recovery'], 'runbook.md'),
 'decisions': ('Decisions and rationale', ['decisions','decision log','tradeoffs','rationale'], 'decisions-and-lessons.md'),
 'lessons': ('Lessons and corrections', ['lessons','corrections','retrospective','learning'], 'decisions-and-lessons.md'),
 'sources': ('Sources and provenance', ['sources','provenance','evidence register','source register'], 'research.md'),
 'method': ('Research method and evidence limits', ['method','methodology','research method','evidence limits','known gaps'], 'research.md'),
 'delivery': ('Deliverables and formats', ['deliverables','formats','delivery','outputs'], 'brief.md'),
 'skill': ('Skill procedure and triggers', ['procedure','workflow','when to use','pipeline','instructions'], 'skill.md'),
 'compatibility': ('Compatibility and versions', ['compatibility','supported versions','versioning','runtime','requirements'], 'technical.md'),
 'directory': ('Directory and authoritative sources', ['directory','catalog','catalogue','repository map','what is inside','source of truth','browse the library'], 'catalog.md'),
 'maintenance': ('Maintenance and updates', ['maintenance','updates','contributing','source of truth and updates','adding a small shared skill'], 'catalog.md'),
}
COMMON = ['brief','scope','acceptance','status','runbook','decisions','lessons']
PROFILES = {
 'product': COMMON+['prd','audience','journeys','content','positioning','tone','visual','architecture','data','integrations','security'],
 'creative': COMMON+['audience','positioning','tone','visual','content','delivery','sources'],
 'library': COMMON+['architecture','integrations','security','compatibility'],
 'design-system': COMMON+['audience','positioning','tone','visual','delivery','compatibility'],
 'skill': COMMON+['skill','delivery','security','compatibility'],
 'research': COMMON+['audience','sources','method','data','delivery'],
 'catalog': ['brief','scope','directory','maintenance','status','acceptance'],
}

def norm(value):
 return re.sub(r'[^a-z0-9]+',' ',value.lower()).strip()

def allowed_path(path):
 p=PurePosixPath(path)
 return bool(path) and not p.is_absolute() and '..' not in p.parts and '\\' not in path and ':' not in path

def sections(text):
 lines=text.splitlines()
 headings=[]
 fence=False
 for i,line in enumerate(lines):
  if line.lstrip().startswith(('```','~~~')): fence=not fence
  if fence: continue
  m=re.match(r'^(#{1,6})\s+(.+?)\s*#*$',line)
  if m: headings.append((i,len(m[1]),m[2]))
 result=[]
 for n,(start,level,title) in enumerate(headings):
  end=next((x[0] for x in headings[n+1:] if x[1]<=level),len(lines))
  result.append((norm(title),'\n'.join(lines[start+1:end])))
 return result

def substantive(text):
 text=re.sub(r'<!--.*?-->','',text,flags=re.S)
 text=re.sub(r'```.*?```','',text,flags=re.S)
 text=re.sub(r'\[[^]]+\]\([^)]*\)','',text)
 words=re.findall(r'[A-Za-z0-9]+',text)
 placeholder=bool(re.search(r'(?im)^\s*(?:[-*]\s*)?(?:TODO|TBD|INSERT HERE|FILL IN|REPLACE ME)(?:\b|:)',text))
 return len(words)>=16 and not placeholder

def audit(files,config):
 findings=[]
 found={}
 profiles=config.get('profiles',[])
 if not isinstance(profiles,list) or not profiles or any(x not in PROFILES for x in profiles):
  return {'findings':[('configuration','Missing or invalid profiles in .studio/project.json.')],'found':{},'required':[],'exceptions':[]}
 required=list(dict.fromkeys(t for p in profiles for t in PROFILES[p]))
 mappings=config.get('documents',{})
 if not isinstance(mappings,dict): mappings={}
 skip={'templates','collections','fixtures','tests','node_modules','vendor','examples','archive','archived'}
 docs={p:t for p,t in files.items() if p.lower().endswith('.md') and not any(x.lower() in skip for x in PurePosixPath(p).parts)}
 cache={p:sections(t) for p,t in docs.items()}
 exceptions=[]
 declared=config.get('not_applicable',{})
 if not isinstance(declared,dict): declared={}
 for topic in required:
  if topic in declared:
   reason=declared[topic]
   if isinstance(reason,str) and len(reason.strip())>=30:
    exceptions.append(topic)
    continue
   findings.append((topic,'Not-applicable declaration needs a specific explanation for reviewer judgment.'))
   continue
  aliases=TOPICS[topic][1]
  candidates=[]
  mapped=mappings.get(topic)
  if mapped is not None:
   if not isinstance(mapped,list) or not mapped or any(not isinstance(p,str) or not allowed_path(p.split('#')[0]) for p in mapped):
    findings.append((topic,'Invalid document mapping; use repository-relative Markdown paths.'))
    continue
   for ref in mapped:
    path,_,anchor=ref.partition('#')
    if path not in files: continue
    if anchor:
     candidates.extend((path,body) for title,body in sections(files[path]) if title==norm(anchor))
    else: candidates.append((path,files[path]))
  else:
   for path,text in docs.items():
    stem=norm(PurePosixPath(path).stem)
    if stem in aliases: candidates.append((path,text))
    candidates.extend((path,body) for title,body in cache[path] if any(title==a or title.startswith(a+' ') or title.endswith(' '+a) for a in aliases))
  good=next((p for p,t in candidates if substantive(t)),None)
  if good: found[topic]=good
  else:
   findings.append((topic,'Document or section not found, too brief, or still contains an explicit placeholder.'))
 return {'findings':findings,'found':found,'required':required,'exceptions':exceptions}

def render(result,sha,profiles,changed_controls=False,unavailable=None):
 title='CRITICAL DOCUMENTATION GAPS' if result['findings'] or unavailable else 'Documentation review reminder'
 lines=[MARKER,'## '+title,'',f'**Advisory only — this report does not block merging.** Reviewed `{sha[:12]}` with advisor {VERSION}.','']
 if unavailable:
  lines+=['**Review incomplete:** '+unavailable,'Do not treat this as a clean documentation review.','']
 if result['findings']:
  lines+=['These topics need documentation or an explicit reviewer decision before merging:','', '| Gap | What needs attention | Guide |','|---|---|---|']
  for topic,reason in result['findings']:
   label,_,template=TOPICS.get(topic,(topic,[], 'catalog.md'))
   lines.append(f'| {label} | {reason} | [Template]({HANDBOOK}templates/project/{template}) |')
 elif not unavailable:
  lines+=['No structural gaps were detected in the scanned documents. **This is not approval of their accuracy, completeness or product quality.**','']
 if result['exceptions']:
  lines+=['**Declared not applicable — reviewer confirmation needed:** '+', '.join(TOPICS[t][0] for t in result['exceptions'])+'.','']
 if changed_controls:
  lines+=['**Review advisor changes:** this PR modifies the workflow, advisor or document mappings. Check that it does not hide gaps. The current report uses the trusted base-branch advisor.','']
 lines+=['### Before merging','1. Confirm that the PRD/brief, tone, journeys and technical details match the change where applicable.','2. Address the gaps, or record **Documentation gap decision:** followed by what is deferred/not applicable, why, and the follow-up owner or trigger.','3. Review the actual content. Headings and file presence do not establish quality.','',f'[Studio-wide guidelines]({HANDBOOK}standards/STUDIO-WIDE.md) · [Project guidelines]({HANDBOOK}standards/PROJECT-GUIDELINES.md)','', 'Scope: Markdown and configured document paths in the PR head; templates and historical copies are excluded from automatic discovery. The report updates when the PR changes.']
 return '\n'.join(lines)+'\n'

def api(path,method='GET',data=None):
 token=os.environ['GH_TOKEN']
 req=urllib.request.Request('https://api.github.com/'+path,method=method,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'},data=None if data is None else json.dumps(data).encode())
 with urllib.request.urlopen(req,timeout=40) as response: return json.load(response)

def decode_blob(repo,sha):
 data=api(f'repos/{repo}/git/blobs/{sha}')
 return base64.b64decode(data['content']).decode('utf-8')

def publish(repo,number,body,head):
 # Avoid a slow run replacing a report for a newer PR commit.
 current=api(f'repos/{repo}/pulls/{number}')
 if current['head']['sha']!=head: return
 for page in range(1,11):
  comments=api(f'repos/{repo}/issues/{number}/comments?per_page=100&page={page}')
  for c in comments:
   if c.get('user',{}).get('login')=='github-actions[bot]' and MARKER in c.get('body',''):
    api(f"repos/{repo}/issues/comments/{c['id']}",'PATCH',{'body':body})
    return
  if len(comments)<100: break
 api(f'repos/{repo}/issues/{number}/comments','POST',{'body':body})

def main():
 event=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
 repo=os.environ['GITHUB_REPOSITORY']
 if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo): raise ValueError('Invalid repository')
 pr=event['pull_request']; number=int(pr['number']); head=pr['head']['sha']
 if not re.fullmatch(r'[0-9a-f]{40}',head): raise ValueError('Invalid head')
 result={'findings':[],'exceptions':[]}; config={}; unavailable=None; controls=False
 try:
  tree=api(f'repos/{repo}/git/trees/{head}?recursive=1')
  if tree.get('truncated'): raise ValueError('Repository tree exceeds API limit; map a narrower documentation scope.')
  entries={e['path']:e for e in tree['tree'] if e['type']=='blob'}
  config_entry=entries.get('.studio/project.json')
  if not config_entry: raise ValueError('Missing .studio/project.json; declare repository profiles and document mappings.')
  if config_entry.get('size',0)>50000: raise ValueError('Project mapping file is unexpectedly large.')
  config=json.loads(decode_blob(repo,config_entry['sha']))
  if not isinstance(config,dict): raise ValueError('Project mapping must be a JSON object.')
  mapped=set()
  for refs in config.get('documents',{}).values():
   if isinstance(refs,list): mapped.update(p.split('#')[0] for p in refs if isinstance(p,str))
  ignore={'templates','collections','fixtures','tests','node_modules','vendor','examples','archive','archived'}
  selected=[(p,e) for p,e in entries.items() if p in mapped or (p.lower().endswith('.md') and (p.count('/')==0 or p.startswith(('docs/','brand/','.studio/'))) and not any(x.lower() in ignore for x in PurePosixPath(p).parts))]
  if len(selected)>160: raise ValueError('Too many candidate documents; configure specific document mappings.')
  files={}
  for p,e in selected:
   if e.get('mode')=='120000': continue
   if e.get('size',0)>300000: continue
   files[p]=decode_blob(repo,e['sha'])
  result=audit(files,config)
  base=pr['base']['sha']
  base_tree=api(f'repos/{repo}/git/trees/{base}?recursive=1')
  if base_tree.get('truncated'): raise ValueError('Base tree truncated; control-change review incomplete.')
  base_map={e['path']:e['sha'] for e in base_tree['tree']}
  controls=any(base_map.get(p)!=entries.get(p,{}).get('sha') for p in ['.studio/project.json','.github/scripts/studio_advisor.py','.github/workflows/studio-advisory.yml'])
 except Exception as exc:
  # Do not print request URLs, tokens or repository document contents in errors.
  unavailable='Unable to finish structural review ('+type(exc).__name__+'). Check mappings, file sizes, API access and workflow logs.'
  print('::warning::Studio documentation review incomplete; do not treat this as a clean review.')
 body=render(result,head,config.get('profiles',[]),controls,unavailable)
 if os.environ.get('GITHUB_STEP_SUMMARY'): Path(os.environ['GITHUB_STEP_SUMMARY']).write_text(body)
 if result['findings']: print(f"::warning::{len(result['findings'])} critical documentation gaps; advisory only.")
 try: publish(repo,number,body,head)
 except Exception as exc:
  print('::warning::Could not post advisory comment ('+type(exc).__name__+'); read the workflow summary.')
  return 1
 return 0

if __name__=='__main__': sys.exit(main())
