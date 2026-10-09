"""Small native operations sharing the API's validators and store semantics."""
import json
import io
from contextlib import redirect_stdout
from personal_jobby import private_fs as fs
from personal_jobby.core import Job, assess
from personal_jobby.store import now


def private_json(path):
    return json.loads(fs.read_bytes(path, max_bytes=16000))


def profile(store):
    return dict(profile=store.public_profile(),
                phone_present=bool(store.profile().get('answers', {}).get('phone')))


def show(store, id):
    job = store.get(id)
    directory = None
    try:
        folder = store.artifact_dir(id)
        # Check every ancestor, and report only an existing immutable directory.
        fd = fs.directory(folder)
        import os
        os.close(fd)
        directory = str(folder)
    except (FileNotFoundError, ValueError, OSError):
        pass
    return store.redact(dict(job=job, events=store.events(id),
                             materials=job['materials'], current_artifact_directory=directory))


def fit(store, id, path):
    with redirect_stdout(io.StringIO()):
        from personal_jobby.app import Fit
    data = Fit.model_validate(private_json(path))
    job = store.get(id)
    job.update(store.redact(data.model_dump()))
    eligibility, _ = assess(job, store.settings(), store.profile())
    with store.connect() as connection:
        connection.execute('UPDATE jobs SET data=?,updated=? WHERE id=?',
                           (json.dumps({key: job[key] for key in Job.model_fields}), now(), id))
        if job['status'] in ('discovered', 'needs_review', 'eligible'):
            connection.execute('UPDATE jobs SET status=? WHERE id=?', (eligibility, id))
        store.event(connection, id, 'fit_verification', data.model_dump())
    return store.redact(store.get(id))


def approve(store, id, path):
    with redirect_stdout(io.StringIO()):
        from personal_jobby.app import Approval
    from personal_jobby.artifacts import approve as approve_artifacts
    data = Approval.model_validate(private_json(path))
    store.get(id)
    return approve_artifacts(store, id, data.review_token,
                             dict(reviewer=data.reviewer, note=data.note))
