"""M2 — 하루 호출 카운터는 동시에 올려도 셈이 빠지지 않는다(flock + 임시파일 → os.replace)."""
import threading

from llm import cli


def test_concurrent_bumps_are_not_lost(tmp_path):
    storage = str(tmp_path)
    barrier = threading.Barrier(20)

    def worker():
        barrier.wait()
        for _ in range(5):
            cli._bump(storage)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert cli.calls_today(storage) == 100
    # 임시 파일이 남지 않는다.
    assert not list((tmp_path / "llm").glob("*.tmp"))
