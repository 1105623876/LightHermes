"""Acceptance oracles use fixed local code; no API or model-generated execution."""
import pytest

from lighthermes.bash import BashExecutor
from scripts.r43_discovery import INPUT, EXPECTED, artifact_bytes, verify


def test_byte_oracle_rejects_newline_conversion_and_input_changes(tmp_path):
    source, output = tmp_path / 'input.cfg', tmp_path / 'output.cfg'
    source.write_bytes(INPUT)
    output.write_bytes(EXPECTED)
    assert verify('bytes', tmp_path, None)['passed']
    output.write_bytes(EXPECTED.replace(b'\r\n', b'\n'))
    assert not verify('bytes', tmp_path, None)['passed']
    output.unlink()
    source.write_bytes(b'modified input')
    result = verify('bytes', tmp_path, None)
    assert result['artifact_present'] and not result['passed']


@pytest.mark.parametrize('correct', [True, False])
def test_transaction_oracle_checks_atomicity_and_caller_ownership(tmp_path, correct):
    source = '''def insert_batch(connection, rows):
    connection.execute('SAVEPOINT batch')
    try:
        connection.executemany('INSERT INTO items VALUES (?)', rows)
    except BaseException:
        connection.execute('ROLLBACK TO batch')
        raise
    finally:
        connection.execute('RELEASE batch')
''' if correct else '''def insert_batch(connection, rows):
    with connection:
        connection.executemany('INSERT INTO items VALUES (?)', rows)
'''
    (tmp_path / 'batch.py').write_text(source)
    result = verify('transaction', tmp_path, BashExecutor(tmp_path, authorized=True).execute)
    assert result['passed'] is correct
    if not correct:
        assert not result['checks']['autocommit_atomic']
        assert not result['checks']['caller_transaction_atomic']
        assert not result['checks']['caller_transaction_owned']


def test_host_artifact_reader_does_not_follow_model_symlinks(tmp_path):
    outside = tmp_path / 'outside'
    outside.write_bytes(b'not task output')
    task = tmp_path / 'task'
    task.mkdir()
    link = task / 'output.cfg'
    link.symlink_to(outside)
    assert artifact_bytes(link) is None
