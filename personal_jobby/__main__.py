import argparse
import json
import sys
from contextlib import redirect_stdout
from io import StringIO
from personal_jobby.store import Store

def main():
    p=argparse.ArgumentParser(description='Private deterministic Jobby. No AI APIs. External Hermes agent executes browser actions.')
    sub=p.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init'); init.add_argument('--pdf',required=True); init.add_argument('--replace',action='store_true',help='Back up old private profile and invalidate documents')
    status=sub.add_parser('status');status.add_argument('--brief',action='store_true',help='Safe counts and short job summaries (also the default)')
    add=sub.add_parser('add'); add.add_argument('json_file',help='Posting JSON path (or - for stdin)')
    search=sub.add_parser('search'); search.add_argument('term'); search.add_argument('--limit',type=int,default=10);search.add_argument('--location',default='Toronto, ON, Canada');search.add_argument('--remote',action='store_true',default=None);search.add_argument('--hours-old',type=int,default=72)
    show=sub.add_parser('show',help='Sanitized job, events and current immutable materials'); show.add_argument('job_id',type=int)
    sub.add_parser('profile',help='Public source facts and answers; phone presence only')
    fit=sub.add_parser('fit',help='Record source-grounded fit evidence'); fit.add_argument('job_id',type=int); fit.add_argument('--evidence',required=True,help='Private JSON, no symlinks, at most 16000 bytes')
    approve=sub.add_parser('approve',help='Record actual operator visual review of the exact current generation'); approve.add_argument('job_id',type=int); approve.add_argument('--review',required=True,help='Private JSON with reviewer, note and exact review_token; at most 16000 bytes')
    prep=sub.add_parser('prepare'); prep.add_argument('job_id',type=int)
    receipt=sub.add_parser('receipt',help='Record an existing receipt; DOES NOT submit'); receipt.add_argument('job_id',type=int); receipt.add_argument('--text',default=''); receipt.add_argument('--url',default=''); receipt.add_argument('--timestamp',required=True);receipt.add_argument('--attempt-id',default=None,help='Explicit captured manifest; omit to record documents unknown')
    attempt=sub.add_parser('attempt',help='Capture an external operator manifest; DOES NOT submit');attempt.add_argument('job_id',type=int);attempt.add_argument('--manifest',required=True,help='Local JSON manifest with approved generation, filenames and hashes')
    screenshot=sub.add_parser('screenshot',help='Ingest an already reviewed phone-sanitized PNG locally');screenshot.add_argument('attempt_id');screenshot.add_argument('png_file');screenshot.add_argument('--kind',choices=['filled_form','employer_confirmation'],required=True);screenshot.add_argument('--qa-note',required=True);screenshot.add_argument('--phone-redacted',action='store_true',help='Attest phone field was masked/removed BEFORE capture and PNG visually checked')
    from personal_jobby.daily import add_parser
    add_parser(sub)
    args=p.parse_args()
    try:
        # Backend imports and operations may print private data; discard it.
        with redirect_stdout(StringIO()):
            store=Store()
            if args.command=='daily':
                from personal_jobby.daily import dispatch
                result=dispatch(store,args)
            elif args.command in ('show','profile','fit','approve'):
                from personal_jobby import cli_operations as operations
                if args.command=='profile': result=operations.profile(store)
                elif args.command=='show': result=operations.show(store,args.job_id)
                elif args.command=='fit': result=operations.fit(store,args.job_id,args.evidence)
                else: result=operations.approve(store,args.job_id,args.review)
            elif args.command=='init':
                from personal_jobby.import_profile import initialize
                result=initialize(store,args.pdf,args.replace)
            elif args.command=='status':
                from personal_jobby.daily import Daily
                control=Daily(store).status()
                jobs=store.jobs();profile=store.profile()
                result=dict(settings=store.settings(),job_count=len(jobs),status_counts={status:sum(j['status']==status for j in jobs) for status in sorted({j['status'] for j in jobs})},jobs=[{k:j[k] for k in ('id','title','company','status','eligibility')} for j in jobs],candidate_initialized=(store.root/'candidate.json').exists(),fact_count=len(profile['facts']),phone_present=bool(profile['answers'].get('phone')),missing_answers=[k for k in ('work_eligibility',) if not profile['answers'].get(k)],submission_adapter='external Hermes cron agent' if control['policy']['cron_job_id'] else 'unavailable; external Hermes browser operator assisted path',submission_active=control['submission_active'],executor_type=control['executor_type'],executor_enabled=control['executor_enabled'],executor_note=control['capability'])
            elif args.command=='add':
                from pathlib import Path
                result=store.add(json.loads(sys.stdin.read() if args.json_file=='-' else Path(args.json_file).read_text()))
            elif args.command=='search':
                from personal_jobby.search import discover
                result=discover(store,args.term,args.limit,location=args.location,remote=args.remote,hours_old=args.hours_old)
            elif args.command=='prepare':
                from personal_jobby.documents import prepare
                result=prepare(store,args.job_id)
            elif args.command=='attempt':
                from personal_jobby.audit import create_attempt
                from personal_jobby import private_fs as fs
                result=create_attempt(store,args.job_id,json.loads(fs.read_text(args.manifest)))
            elif args.command=='screenshot':
                from personal_jobby.audit import add_screenshot
                result=add_screenshot(store,args.attempt_id,args.png_file,args.kind,args.qa_note,args.phone_redacted)
            else: result=store.receipt(args.job_id,args.text,args.timestamp,args.url,args.attempt_id)
            output=json.dumps(store.redact(result),indent=2)
        print(output)
    except Exception as e:
        p.exit(1,'Error: command failed ('+type(e).__name__+'); input values withheld. Check validation, source availability and private paths.\n')

if __name__=='__main__': main()
